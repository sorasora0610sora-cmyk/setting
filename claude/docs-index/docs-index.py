#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""資料台帳 (DOCS.md) の走査・一覧・オープンと、セッション起動時の案内。

起動時に「○○ の資料をブラウザで開きますか？」と要約付きで提案するための元データを扱う。
台帳はディレクトリごとに 1 枚:
  asunaro-ops  … ws-*/DOCS.md (WS ごと)
  他リポジトリ … ルートの DOCS.md

使い方 (Windows は python、Mac / Linux / クラウドは python3):
  python3 .claude/docs-index.py scan  <dir> [--write] [--limit N]  台帳と実物の差分 (--write で新規の枠を追加・新版へ差し替え)
  python3 .claude/docs-index.py list  <dir>                        提案用の一覧 (この環境で開けるか付き)
  python3 .claude/docs-index.py open  <dir> <番号>...               ブラウザ / 既定アプリで開く (クラウドはリンク表示)
  python3 .claude/docs-index.py stamp <dir> <番号 or 場所>...       要約を書いた資料の指紋・更新日を記録
  python3 .claude/docs-index.py drop  <dir> <番号 or 場所>... [--reason 理由]  節を消して対象外に登録 (次の scan で戻らない)
  python3 .claude/docs-index.py guide                              台帳の書き方 (要約担当向け)
  python3 .claude/docs-index.py session-start                      SessionStart フック (stdin = フック JSON)

正本: ~/src/setting/claude/docs-index/docs-index.py
各リポジトリの .claude/docs-index.py はコピー (setting/install.sh --repo <dir> で配置)。直すのは正本。
標準ライブラリのみ・Python 3.8 以上 (Mac の CLT 付属 python3 でも動かすため)。
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

# Windows の cp932 コンソールで「—」や絵文字を出すと落ちるため
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

LEDGER = "DOCS.md"
DOC_EXT = {
    ".html": "HTML", ".htm": "HTML", ".pdf": "PDF",
    ".docx": "Word", ".doc": "Word",
    ".xlsx": "Excel", ".xlsm": "Excel", ".xls": "Excel",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
    ".gdoc": "Googleドキュメント", ".gsheet": "Googleスプレッドシート", ".gslides": "Googleスライド",
}
GOOGLE_NATIVE = {".gdoc": "document", ".gsheet": "spreadsheets", ".gslides": "presentation"}
# 資料ではないフォルダ (生成物・旧版・データの元ファイル)。名前は小文字で照合する
SKIP_DIRS = {"node_modules", "venv", "__pycache__", "dist", "build", "test-results",
             "htmlcov", "worktrees", "archives", "old", "_old", "sources", "raw", "data", "db",
             "_deprecated", "deprecated"}
SKIP_DIR_PREFIX = ("_退避", "_to_delete", "_archive", "_旧")
SKIP_DIR_SUFFIX = ("_old", "-old", " old", "_db")
COPY_RE = re.compile(r"( - コピー| のコピー|^コピー|^Copy of | - Copy\b)", re.I)
DEFAULT_EXCLUDE = ["today/week-plan-*", "today/master-week-*"]
DOC_URL_HOSTS = ("docs.google.com", "drive.google.com", "notion.so", "notion.site",
                 ".surge.sh", ".github.io")
PH_SUMMARY = "(未作成)"
PH_PRINT = "(未要約)"
FIELD_RE = re.compile(r"^- (場所|URL|種別|版|更新|指紋|関連|要約)[:：][ \t]?(.*)$")
HEAD_RE = re.compile(r"^(検索語|Drive|外部収集|最終走査)[:：][ \t]*(.*)$")
URL_RE = re.compile(r"https?://[^\s)>\]\"'`|<]+")
VER_RE = re.compile(r"[_\-\s]?[vV](\d+(?:[._]\d+)*)(?=$|[_\-\s（(])")
DATE6_HEAD_RE = re.compile(r"^(\d{6})[_\-]")
DATE6_IN_RE = re.compile(r"[_\-](\d{6})(?=$|[_\-])")
ISO_TAIL_RE = re.compile(r"[_\-]\d{4}-?\d{2}-?\d{2}$")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------- 環境
def env_kind() -> str:
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return "cloud"
    if sys.platform == "darwin":
        return "mac"
    if os.name == "nt" or sys.platform.startswith(("msys", "cygwin")):
        return "win"
    return "linux"


ENV_LABEL = {"cloud": "クラウドセッション", "mac": "Mac", "win": "Windows", "linux": "Linux"}


def py_cmd() -> str:
    return "python" if env_kind() == "win" else "python3"


def self_cmd() -> str:
    """Claude に打たせるコマンドの頭 (Bash でも PowerShell でも通るよう / 区切り・引用符付き)。"""
    return '{} "{}"'.format(py_cmd(), Path(__file__).resolve().as_posix())


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false"] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def repo_root(path: Path):
    out = git(path, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out and out.strip() else None


def drive_root():
    """Google Drive (マイドライブ) のローカルの根。Windows はミラー、Mac は CloudStorage。"""
    env = os.environ.get("DOCS_DRIVE_ROOT")
    cands = [Path(env)] if env else []
    home = Path.home()
    cands += [home / "マイドライブ", home / "My Drive"]
    cs = home / "Library" / "CloudStorage"
    try:
        for g in sorted(cs.glob("GoogleDrive-*")):
            cands += [g / "マイドライブ", g / "My Drive"]
            try:  # Mac は NFD の名前で置かれていることがある
                cands += [c for c in g.iterdir() if nfc(c.name) in ("マイドライブ", "My Drive")]
            except OSError:
                pass
    except OSError:
        pass
    cands += [Path("G:/マイドライブ"), Path("G:/My Drive")]
    for c in cands:
        try:
            if c.is_dir():
                return c
        except OSError:
            pass
    return None


def resolve(base: Path, rel: str):
    """base/rel を探す。見つからなければ 1 段ずつ NFC で照合する (Mac の NFD 名対策)。"""
    p = base / rel
    try:
        if p.exists():
            return p
    except OSError:
        return None
    cur = base
    for part in Path(rel).parts:
        if part == "..":
            cur = cur.parent
            continue
        nxt = cur / part
        try:
            if nxt.exists():
                cur = nxt
                continue
            hit = next((c for c in cur.iterdir() if nfc(c.name) == nfc(part)), None)
        except OSError:
            return None
        if hit is None:
            return None
        cur = hit
    return cur


# ---------------------------------------------------------------- 台帳
class Entry:
    def __init__(self, title: str, line: int):
        self.title = title
        self.line = line
        self.f = {}
        self.fline = {}
        self.last = line  # この節の最終フィールド行

    def get(self, k: str) -> str:
        return self.f.get(k, "").strip()

    @property
    def loc(self) -> str:
        return self.get("場所")

    def kind(self) -> str:
        loc = self.loc
        if re.match(r"^https?://", loc):
            return "url"
        if loc.startswith("drive:"):
            return "drive"
        return "file" if loc else "none"


class Ledger:
    def __init__(self, d: Path):
        self.dir = d
        self.path = d / LEDGER
        self.lines = []
        self.entries = []
        self.excludes = []
        self.ex_line = None
        self.head = {"検索語": "", "Drive": [], "外部収集": "", "最終走査": ""}
        self.exists = self.path.is_file()
        if self.exists:
            self._parse()

    def _parse(self):
        self.lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        cur, in_ex, seen = None, False, False
        for i, ln in enumerate(self.lines):
            if ln.startswith("## "):
                seen = True
                title = ln[3:].strip()
                if title.startswith("対象外"):
                    in_ex, cur, self.ex_line = True, None, i
                else:
                    in_ex = False
                    cur = Entry(title, i)
                    self.entries.append(cur)
                continue
            if in_ex:
                m = re.match(r"^- `([^`]+)`", ln) or re.match(r"^- (\S+)", ln)
                if m:
                    self.excludes.append(nfc(m.group(1)))
            elif cur is not None:
                m = FIELD_RE.match(ln)
                if m:
                    cur.f[m.group(1)] = m.group(2)
                    cur.fline[m.group(1)] = i
                    cur.last = i
            elif not seen:
                m = HEAD_RE.match(ln)
                if m:
                    k, v = m.group(1), m.group(2).strip()
                    if k == "Drive":
                        if v and not v.startswith("("):
                            self.head["Drive"].append(v.strip("`/ "))
                    else:
                        self.head[k] = v

    def set_head(self, key: str, val: str):
        """ヘッダ欄 (最初の ## より前) を書き換える。無ければ ## の直前に足す。最後に呼ぶこと (行番号がずれる)。"""
        first = next((i for i, l in enumerate(self.lines) if l.startswith("## ")), len(self.lines))
        for i in range(first):
            if re.match(r"^{}[:：]".format(key), self.lines[i]):
                self.lines[i] = "{}: {}".format(key, val)
                return
        at = first
        while at > 0 and not self.lines[at - 1].strip():
            at -= 1
        self.lines.insert(at, "{}: {}".format(key, val))

    def save(self):
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(self.lines).rstrip("\n") + "\n")

    def excluded(self, loc: str) -> bool:
        loc = nfc(loc)
        for pat in DEFAULT_EXCLUDE + self.excludes:
            if fnmatch.fnmatch(loc, pat) or fnmatch.fnmatch(loc, pat.rstrip("/") + "/*"):
                return True
        return False


def new_ledger_text(d: Path, drive_dirs) -> list:
    drive_line = "Drive: " + (drive_dirs[0] if drive_dirs else "(Google Drive の作業フォルダ。マイドライブからの相対。複数なら行を重ねる)")
    lines = [
        "# 資料台帳 — {}".format(d.name),
        "",
        "> セッション起動時に「○○ の資料をブラウザで開きますか？」と要約付きで提案するための台帳。",
        "> 書き方は `python3 .claude/docs-index.py guide`。場所・種別・更新・指紋はスクリプトが書き、見出し・関連・要約は Claude が書く。",
        "> 1 資料 = 1 節(## 見出し)。版違いは最新だけを載せる(新版が出たら `scan --write` が差し替える)。",
        "> 自動で足すのは「最終走査」より後に増えた・更新された資料だけ。それより古い未登録は `scan --write --backlog N` で足す。",
        "",
        "検索語: (Drive / Notion を検索する語。顧客名・案件名などを読点区切りで)",
    ]
    lines.append(drive_line)
    lines += [l for l in ("Drive: " + x for x in drive_dirs[1:])]
    lines += ["外部収集: (Drive / Notion を最後に検索した日)", ""]
    lines += [
        "## 対象外",
        "",
        "> 台帳に載せないもののパターン(このディレクトリからの相対 / `drive:` 付き / URL・fnmatch)。`- \\`パターン\\` — 理由` の形で書く。",
        "",
    ]
    return lines


def guess_drive_dirs(d: Path, droot) -> list:
    """ws-pjNNN-* なら Drive の */PJ-NNN_* を作業フォルダとみなす (asunaro-ops の命名規則)。"""
    m = re.search(r"pj(\d{3})", d.name, re.I)
    if not m or droot is None:
        return []
    out = []
    try:
        for top in sorted(droot.iterdir()):
            if not top.is_dir():
                continue
            for sub in sorted(top.iterdir()):
                if sub.is_dir() and nfc(sub.name).upper().startswith("PJ-" + m.group(1)):
                    out.append(nfc("{}/{}".format(top.name, sub.name)))
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 実物の走査
class Cand:
    def __init__(self, loc, kind, path, typ, date_s, fp, mtime):
        self.loc, self.kind, self.path, self.typ = loc, kind, path, typ
        self.date, self.fp, self.mtime = date_s, fp, mtime
        self.family, self.rank = family_and_rank(loc, date_s, mtime)


def family_and_rank(loc: str, date_s: str, mtime: float):
    """版違いを 1 家族にまとめる鍵と、家族内の新しさ。
    版番号の大小だけで新しさを決めない (V1.8 が V2.0 より新しい実例がある)。
    家族の鍵には版の「大番号」を含める (V1 系 = AI 詳細版 / V2 系 = 共有版 のように並走する運用があるため)。
    末尾の日付 (-2026-09-23) も外して同じ系列とみなす。
    新しさ = 名前先頭の YYMMDD > 名前末尾の日付 > 更新日 > 版番号 > mtime の順。"""
    head, _, name = loc.rpartition("/")
    stem, ext = os.path.splitext(nfc(name))
    s, d6 = stem, ""
    m = DATE6_HEAD_RE.match(s)
    if m:
        d6, s = m.group(1), s[m.end():]
    ver = ()
    vms = list(VER_RE.finditer(s))
    major = ""
    if vms:
        v = vms[-1]
        ver = tuple(int(x) for x in re.split(r"[._]", v.group(1)) if x.isdigit())
        major = "v{}".format(ver[0]) if ver else ""
        s = s[:v.start()] + s[v.end():]
    s = DATE6_IN_RE.sub("", s)
    m = ISO_TAIL_RE.search(s)
    tail = re.sub(r"\D", "", m.group(0)) if m else ""
    if m:
        s = s[:m.start()]
    key = "{}/{}{}{}".format(head, s.strip("_- ").lower(), major, ext.lower())
    return key, (d6, tail, date_s, ver, mtime)


def skip_dir(name: str) -> bool:
    n = nfc(name)
    low = n.lower()
    return (n.startswith(".") or low in SKIP_DIRS or n.startswith(SKIP_DIR_PREFIX)
            or low.endswith(SKIP_DIR_SUFFIX))


def walk_docs(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not skip_dir(d))
        for fn in filenames:
            stem, ext = os.path.splitext(fn)
            if ext.lower() in DOC_EXT and not fn.startswith("~$") and not COPY_RE.search(nfc(stem)):
                yield Path(dirpath) / fn


def git_index(root: Path, rel: str) -> dict:
    """追跡中のファイル → blob ハッシュ (中身基準なので Mac / Windows / クラウドで一致する)。"""
    out = git(root, "ls-files", "-s", "--", rel or ".") or ""
    res = {}
    for ln in out.splitlines():
        meta, _, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and path:
            res[nfc(path)] = parts[1][:10]
    return res


def git_dates(root: Path, rel: str) -> dict:
    out = git(root, "log", "--format=@@%cs", "--name-only", "--", rel or ".") or ""
    res, cur = {}, ""
    for ln in out.splitlines():
        if ln.startswith("@@"):
            cur = ln[2:].strip()
        elif ln.strip():
            res.setdefault(nfc(ln.strip()), cur)
    return res


def mdate(st) -> str:
    return datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")


class Scanner:
    """台帳のあるディレクトリについて、リポジトリ内と Drive の資料を集める。"""

    def __init__(self, d: Path, led: Ledger):
        self.d, self.led = d, led
        self.root = repo_root(d)
        self.rel = ""
        if self.root is not None:
            try:
                self.rel = nfc(d.resolve().relative_to(self.root.resolve()).as_posix())
            except ValueError:
                self.root = None
        if self.rel == ".":
            self.rel = ""
        self.droot = drive_root() if env_kind() != "cloud" else None
        self._idx = self._dates = None
        if not led.exists and not led.head["Drive"]:  # 作る前の scan も --write と同じ範囲を見る
            led.head["Drive"] = guess_drive_dirs(d, self.droot)

    def idx(self):
        if self._idx is None:
            self._idx = git_index(self.root, self.rel) if self.root else {}
        return self._idx

    def dates(self):
        if self._dates is None:
            self._dates = git_dates(self.root, self.rel) if self.root else {}
        return self._dates

    def repo_key(self, loc: str) -> str:
        return nfc("/".join(x for x in (self.rel, loc) if x))

    def file_cand(self, p: Path):
        loc = nfc(p.relative_to(self.d).as_posix())
        try:
            st = p.stat()
        except OSError:
            return None
        key = self.repo_key(loc)
        blob = self.idx().get(key)
        fp = "git:" + blob if blob else "size:{}".format(st.st_size)
        dt = self.dates().get(key) or mdate(st)
        return Cand(loc, "file", p, DOC_EXT.get(p.suffix.lower(), p.suffix), dt, fp, st.st_mtime)

    def drive_cand(self, p: Path):
        try:
            loc = "drive:" + nfc(p.relative_to(self.droot).as_posix())
            st = p.stat()
        except (OSError, ValueError):
            return None
        return Cand(loc, "drive", p, DOC_EXT.get(p.suffix.lower(), p.suffix), mdate(st),
                    "size:{}".format(st.st_size), st.st_mtime)

    def candidates(self):
        out = []
        for p in walk_docs(self.d):
            c = self.file_cand(p)
            if c and not self.led.excluded(c.loc):
                out.append(c)
        if self.droot is not None:
            for sub in self.led.head["Drive"]:
                base = resolve(self.droot, sub)
                if base is None or not base.is_dir():
                    continue
                for p in walk_docs(base):
                    c = self.drive_cand(p)
                    if c and not self.led.excluded(c.loc):
                        out.append(c)
        return out

    def current(self, e: Entry):
        """台帳の 1 件について、この環境での実物 (Cand) を返す。無ければ None。"""
        k = e.kind()
        if k == "file":
            p = resolve(self.d, e.loc)
            if p is None:
                return None
            if env_kind() == "cloud" and self.root and self.repo_key(e.loc) not in self.idx():
                return None
            return self.file_cand(p)
        if k == "drive" and self.droot is not None:
            p = resolve(self.droot, e.loc[len("drive:"):])
            return self.drive_cand(p) if p is not None else None
        return None


def entry_state(sc: Scanner, e: Entry):
    """(状態, 実物 Cand or None)。状態 = ok / 要約待ち / 変更あり / 見つからない / 未確認(Drive なし)"""
    k = e.kind()
    stored = e.get("指紋")
    pending = (not stored) or stored == PH_PRINT or (not e.get("要約")) or e.get("要約") == PH_SUMMARY
    if k == "url" or k == "none":
        return ("要約待ち" if pending else "ok"), None
    c = sc.current(e)
    if c is None:
        if k == "drive" and sc.droot is None:
            return ("要約待ち" if pending else "未確認"), None
        return "見つからない", None
    if pending:
        return "要約待ち", c
    if stored != c.fp:
        return "変更あり", c
    return "ok", c


def google_native_url(p: Path, ext: str):
    """Drive の .gdoc / .gsheet / .gslides (中身は JSON のポインタ) から Web の URL を作る。"""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        if data.get("url"):
            return str(data["url"])
        if data.get("doc_id"):
            return "https://docs.google.com/{}/d/{}/edit".format(GOOGLE_NATIVE.get(ext, "document"), data["doc_id"])
    return ""


def doc_urls(d: Path) -> list:
    """STATUS / TODO / README / CLAUDE.md に出てくる URL (出現順・重複なし)。"""
    seen, out = set(), []
    for name in ("STATUS.md", "TODO.md", "README.md", "CLAUDE.md"):
        p = d / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in URL_RE.finditer(text):
            u = m.group(0).rstrip(".,、。;:*_")
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def is_doc_url(u: str) -> bool:
    p = urlparse(u)
    host = p.netloc.lower()
    # 説明用の雛形 ({DB_ID} 等)・サービスのトップ・設定画面は資料ではない
    # (surge.sh / github.io はトップページ自体が公開した資料なので、トップでも残す)
    path = p.path.strip("/")
    if "{" in u or "}" in u or path in ("my-integrations",):
        return False
    if path == "" and host in ("notion.so", "www.notion.so", "notion.site", "drive.google.com", "docs.google.com"):
        return False
    return any(host == h.lstrip(".") or host.endswith(h if h.startswith(".") else "." + h) or host == h
               for h in DOC_URL_HOSTS)


def url_type(u: str) -> str:
    host = urlparse(u).netloc.lower()
    if "docs.google.com" in host:
        if "/spreadsheets/" in u:
            return "Googleスプレッドシート"
        if "/presentation/" in u:
            return "Googleスライド"
        return "Googleドキュメント"
    if "drive.google.com" in host:
        return "Google Drive"
    if "notion" in host:
        return "Notion"
    return "Web"


# ---------------------------------------------------------------- scan
def analyze(d: Path):
    led = Ledger(d)
    sc = Scanner(d, led)
    cands = sc.candidates()
    fams = {}
    for c in cands:
        if c.family not in fams or c.rank > fams[c.family].rank:
            fams[c.family] = c
    reg_locs = {nfc(e.loc) for e in led.entries}
    reg_urls = reg_locs | {nfc(e.get("URL")) for e in led.entries if e.get("URL")}
    reg_fams = {}
    for e in led.entries:
        if e.kind() in ("file", "drive"):
            fam, _ = family_and_rank(e.loc, "", 0.0)
            reg_fams.setdefault(fam, e)
    states, newer = [], []
    for e in led.entries:
        st, cur = entry_state(sc, e)
        states.append((e, st, cur))
        if e.kind() in ("file", "drive"):
            if e.get("版") == "固定":
                continue
            fam, _ = family_and_rank(e.loc, "", 0.0)
            best = fams.get(fam)
            if best is not None and nfc(best.loc) != nfc(e.loc) and nfc(best.loc) not in reg_locs:
                if cur is None or best.rank > cur.rank:
                    newer.append((e, best))
    newer_locs = {nfc(b.loc) for _, b in newer}
    unreg = [c for f, c in fams.items()
             if f not in reg_fams and nfc(c.loc) not in reg_locs and nfc(c.loc) not in newer_locs]
    unreg.sort(key=lambda c: (c.date, c.mtime), reverse=True)
    urls = [u for u in doc_urls(d) if nfc(u) not in reg_urls and not led.excluded(u)]
    return led, sc, states, newer, unreg, urls


def cmd_scan(d: Path, write: bool, limit: int, show: int, backlog_n: int = 0):
    led, sc, states, newer, unreg, urls = analyze(d)
    doc_u = [u for u in urls if is_doc_url(u)]
    cnt = {}
    for _, st, _ in states:
        cnt[st] = cnt.get(st, 0) + 1
    print("資料台帳: {} ({})  環境: {}{}".format(
        led.path.as_posix(), "登録 {} 件".format(len(led.entries)) if led.exists else "未作成",
        ENV_LABEL[env_kind()],
        "  Drive: " + sc.droot.as_posix() if sc.droot else "  Drive: (この環境には無い)"))
    if led.head["Drive"]:
        print("  Drive の作業フォルダ: " + " / ".join(led.head["Drive"]))
    print("  要約待ち {} / 変更あり {} / 新版あり {} / 見つからない {} / 未確認 {} / ok {}".format(
        cnt.get("要約待ち", 0), cnt.get("変更あり", 0), len(newer), cnt.get("見つからない", 0),
        cnt.get("未確認", 0), cnt.get("ok", 0)))
    for e, st, _ in states:
        if st not in ("ok", "未確認"):
            print("    [{}] {} — {}".format(st, e.title, e.loc))
    for e, b in newer:
        print("    [新版あり] {} — {} → {}".format(e.title, e.loc, b.loc))
    # 自動で足すのは「最終走査」以後に増えた・更新された資料だけ (台帳を際限なく膨らませないため)。
    # 台帳を作るとき (最終走査なし) は新しい順に limit 件。それより古い残りは backlog として件数だけ出す。
    last = led.head["最終走査"] if re.match(r"^\d{4}-\d{2}-\d{2}$", led.head["最終走査"]) else ""
    fresh = [c for c in unreg if not last or c.date >= last]
    backlog = [c for c in unreg if last and c.date < last]
    print("  未登録の資料 {} 件{} (版違いは最新 1 件にまとめ済み・新しい順):".format(
        len(fresh), " = 最終走査 {} 以後".format(last) if last else ""))
    for c in fresh[:show]:
        print("    + {} {} {}".format(c.date, c.typ, c.loc))
    if len(fresh) > show:
        print("    … ほか {} 件".format(len(fresh) - show))
    if backlog:
        print("  それより古い未登録 {} 件 (自動では足さない。足すなら --backlog N)".format(len(backlog)))
    print("  STATUS 等に出てくる未登録の資料 URL {} 件 (その他の URL {} 件は対象にしない)".format(
        len(doc_u), len(urls) - len(doc_u)))
    for u in doc_u[:show]:
        print("    + " + u)
    if not write:
        if fresh or doc_u or newer:
            print("次: scan {} --write で新しい順に最大 {} 件を台帳へ追加・新版へ差し替え → guide の手順で要約".format(
                d.as_posix(), limit))
        return
    add = fresh[:limit] + backlog[:backlog_n]
    rest = fresh[limit:]
    # ---- 書き込み ----
    if not led.exists:
        led.lines = new_ledger_text(d, led.head["Drive"])
        led.ex_line = next(i for i, l in enumerate(led.lines) if l.startswith("## 対象外"))
    for e, b in newer:  # 新版へ差し替え (要約は残し、指紋を未要約に戻す)
        set_field(led, e, "場所", b.loc)
        set_field(led, e, "種別", b.typ)
        set_field(led, e, "更新", b.date)
        set_field(led, e, "指紋", PH_PRINT)
    blocks = []
    for c in add:
        title = os.path.splitext(c.loc.rpartition("/")[2])[0]
        blk = ["## " + title, "- 場所: " + c.loc]
        ext = os.path.splitext(c.loc)[1].lower()
        if ext in GOOGLE_NATIVE:
            u = google_native_url(c.path, ext)
            if u:
                blk.append("- URL: " + u)
        blk += ["- 種別: " + c.typ, "- 更新: " + c.date, "- 指紋: " + PH_PRINT,
                "- 関連: ", "- 要約: " + PH_SUMMARY, ""]
        blocks += blk
    for u in doc_u:
        p = urlparse(u)
        title = "{} {}".format(url_type(u), (p.netloc + p.path)[:60])
        blocks += ["## " + title, "- 場所: " + u, "- 種別: " + url_type(u), "- 更新: -",
                   "- 指紋: " + PH_PRINT, "- 関連: ", "- 要約: " + PH_SUMMARY, ""]
    if blocks:
        at = led.ex_line if led.ex_line is not None else len(led.lines)
        led.lines[at:at] = blocks
    # 打ち切った分は次回も「以後」に入るよう、最終走査は打ち切った中で最も新しい日付にとどめる
    led.set_head("最終走査", rest[0].date if rest else date.today().isoformat())
    led.save()
    print("書き込み: 新規 {} 件 / URL {} 件 / 新版へ差し替え {} 件 → {}".format(
        len(add), len(doc_u), len(newer), led.path.as_posix()))
    if rest:
        print("  残り {} 件は未登録のまま (次回の scan --write で新しい順に追加)".format(len(rest)))


def set_field(led: Ledger, e: Entry, key: str, val: str):
    text = "- {}: {}".format(key, val)
    if key in e.fline:
        led.lines[e.fline[key]] = text
        e.f[key] = val
        return
    at = e.last + 1
    led.lines.insert(at, text)
    shift = lambda i: i + 1 if i >= at else i  # noqa: E731
    for x in led.entries:
        x.line = shift(x.line)
        x.last = shift(x.last)
        x.fline = {k: shift(v) for k, v in x.fline.items()}
    if led.ex_line is not None:
        led.ex_line = shift(led.ex_line)
    e.fline[key] = at
    e.last = max(e.last, at)
    e.f[key] = val


# ---------------------------------------------------------------- list / open / stamp
def github_url(sc: Scanner, loc: str) -> str:
    if sc.root is None:
        return ""
    origin = (git(sc.root, "remote", "get-url", "origin") or "").strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", origin)
    if not m:
        return ""
    br = (git(sc.root, "rev-parse", "--abbrev-ref", "HEAD") or "main").strip() or "main"
    return "https://github.com/{}/blob/{}/{}".format(m.group(1), quote(br), quote(sc.repo_key(loc)))


def target_of(sc: Scanner, e: Entry, cur):
    """(開く対象 = ローカルパス or URL, 補足)。開けなければ ("", 理由)。"""
    k, url = e.kind(), e.get("URL")
    cloud = env_kind() == "cloud"
    if k == "url":
        return e.loc, ""
    if cur is not None and not cloud:
        return str(cur.path), ""
    if url:
        return url, ""
    if cloud and k == "file" and cur is not None:
        g = github_url(sc, e.loc)
        if g:
            note = "GitHub 上ではソース表示" if e.loc.lower().endswith((".html", ".htm")) else ""
            return g, note
    if k == "drive":
        return "", "Drive の URL 未登録" if cloud or sc.droot is None else "この端末の Drive に無い"
    return "", "この環境に無い"


def cmd_list(d: Path):
    led = Ledger(d)
    if not led.exists:
        print("資料台帳がありません: {} (作るなら: {} scan {} --write)".format(
            led.path.as_posix(), self_cmd(), d.as_posix()))
        return
    sc = Scanner(d, led)
    cloud = env_kind() == "cloud"
    print("資料台帳 {} — {} 件 / 環境: {}{}".format(
        led.path.as_posix(), len(led.entries), ENV_LABEL[env_kind()],
        " (ブラウザは開けない。リンクを示す)" if cloud else " (open <番号> で開ける)"))
    for i, e in enumerate(led.entries, 1):
        st, cur = entry_state(sc, e)
        tgt, note = target_of(sc, e, cur)
        upd = cur.date if cur is not None else e.get("更新")
        flag = {"変更あり": " ⚠要約が古い", "要約待ち": " ⚠要約なし", "見つからない": "", "未確認": ""}.get(st, "")
        print("{:>2}. {} 〔{}・{}〕{}{}".format(i, e.title, e.get("種別") or "?", upd or "-", flag,
                                             "" if tgt else " ✖開けない({})".format(note)))
        if e.get("関連"):
            print("    関連: " + e.get("関連"))
        if e.get("要約") and e.get("要約") != PH_SUMMARY:
            print("    要約: " + e.get("要約"))
        if cloud and tgt:
            print("    リンク: {}{}".format(tgt, " ({})".format(note) if note else ""))


def pick(led: Ledger, keys):
    out = []
    for k in keys:
        if k.isdigit() and 1 <= int(k) <= len(led.entries):
            out.append(led.entries[int(k) - 1])
            continue
        hit = [e for e in led.entries if nfc(e.loc) == nfc(k)]
        if not hit:
            print("見つからない: " + k, file=sys.stderr)
        out += hit
    return out


def cmd_open(d: Path, keys):
    led = Ledger(d)
    sc = Scanner(d, led)
    kind = env_kind()
    for e in pick(led, keys):
        _, cur = entry_state(sc, e)
        tgt, note = target_of(sc, e, cur)
        if not tgt:
            print("✖ 開けない: {} ({})".format(e.title, note))
            continue
        if kind == "cloud":
            print("リンク: {} — {}{}".format(e.title, tgt, " ({})".format(note) if note else ""))
            continue
        try:
            if kind == "mac":
                subprocess.run(["open", tgt], check=False)
            elif kind == "win":
                os.startfile(tgt)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", tgt], check=False)
            print("開きました: {} — {}".format(e.title, tgt))
        except OSError as ex:
            print("✖ 開けない: {} ({})".format(e.title, ex))


def glob_escape(s: str) -> str:
    return "".join("[{}]".format(c) if c in "*?[]" else c for c in s)


def cmd_drop(d: Path, keys, reason: str):
    """節を消し、同じ場所が次の scan で戻ってこないよう「## 対象外」に登録する。"""
    led = Ledger(d)
    if not led.exists:
        sys.exit("資料台帳がありません: " + led.path.as_posix())
    targets = pick(led, keys)
    if not targets:
        sys.exit("消す節がありません")
    starts = [e.line for e in led.entries] + [led.ex_line if led.ex_line is not None else len(led.lines)]
    spans = []
    for e in targets:
        nxt = min(s for s in starts if s > e.line)
        spans.append((e.line, nxt, e))
    for a, b, _ in sorted(spans, key=lambda x: x[0], reverse=True):
        del led.lines[a:b]
    if not any(l.startswith("## 対象外") for l in led.lines):
        led.lines += ["", "## 対象外", ""]
    while led.lines and not led.lines[-1].strip():
        led.lines.pop()
    for _, _, e in spans:
        led.lines.append("- `{}` — {}".format(glob_escape(e.loc), reason or "資料ではない"))
        print("消した: {} — {}".format(e.title, e.loc))
    led.save()
    print("対象外に登録: {} 件 → {}".format(len(spans), led.path.as_posix()))


def cmd_stamp(d: Path, keys):
    led = Ledger(d)
    if not led.exists:
        sys.exit("資料台帳がありません: " + led.path.as_posix())
    sc = Scanner(d, led)
    today = date.today().isoformat()
    n = 0
    for e in pick(led, keys):
        if e.kind() in ("url", "none"):
            set_field(led, e, "指紋", "url")
            set_field(led, e, "更新", today)
        else:
            cur = sc.current(e)
            if cur is None:
                print("✖ この環境に実物が無いので記録しない: {} — {}".format(e.title, e.loc))
                continue
            set_field(led, e, "指紋", cur.fp)
            set_field(led, e, "更新", cur.date)
        n += 1
        if not e.get("要約") or e.get("要約") == PH_SUMMARY:
            print("⚠ 要約が未記入のまま記録した: " + e.title)
    led.save()
    print("記録: {} 件 → {}".format(n, led.path.as_posix()))


# ---------------------------------------------------------------- guide / session-start
GUIDE = """# 資料台帳(DOCS.md)の書き方 — 要約担当向け

## 1 資料 = 1 節
## <人が呼ぶ資料名(例: 生産計画ツール 受注デモ版)>
- 場所: <このディレクトリからの相対パス> | drive:<マイドライブからの相対パス> | https://...
- URL: <任意。Drive / Google ドキュメントの Web URL。クラウドではこれでしか開けない>
- 種別: HTML / PDF / Excel / Word / PowerPoint / Googleドキュメント / Notion / Web
- 版: <任意。「固定」と書くと新版が出ても差し替えない(旧版をあえて残すとき)>
- 更新: <スクリプトが書く>
- 指紋: <スクリプトが書く。手で書かない>
- 関連: <どの作業のときに開く資料か。STATUS.md / TODO.md の語彙でタスク名・キーワード>
- 要約: <何が書いてあるか 2〜3 文。数字・日付・固有名詞は原文どおり。推測は書かない>

## 手順
1. `{cmd} scan <dir>` で 要約待ち / 変更あり / 新版あり / 未登録 を確認する。
2. `{cmd} scan <dir> --write` で未登録の資料の枠を新しい順に追加する(新版は既存の節の場所を差し替える)。
3. 「要約待ち」「変更あり」の資料を 1 つずつ開いて読み、見出し・関連・要約を書く。
   - 読めなかったら 要約: (読めず: 理由) と書く。要約しないで済ませない。
   - 資料ではないもの(ログ・中間生成物・テンプレの写し・送付状の下書き等)は
     `{cmd} drop <dir> <番号>... --reason "理由"` で消す(「## 対象外」に登録され、次の scan で戻ってこない)。
     フォルダごと外すなら「## 対象外」に `- \\`パターン\\` — 理由` を手で足す。
   - 同じ資料の別形式(同名の .html と .pdf 等)・同じ中身の複製は 1 節だけ残し、残りは drop する。
     要約担当(Sonnet)は消さずに候補として報告し、判断はメイン側が行う。
4. 書いた資料ごとに `{cmd} stamp <dir> <番号 or 場所>...` で指紋を記録する(記録しないと次回も要約待ちに出る)。
5. Drive / Notion(`外部収集:` が空か 7 日以上前のとき。コネクタがある環境だけ):
   - Google Drive コネクタで `検索語:` の各語を検索し、作業に使う資料を `場所: https://...` の節で足す。
   - Notion コネクタで同じく検索し、資料にあたるページ(議事録・仕様・まとめ)を足す。タスクのページは足さない。
   - `外部収集:` を今日の日付にする。
6. 最後に台帳だけをパス限定で commit する: git commit -m "docs(<WS>): 資料台帳を更新" -- <dir>/DOCS.md

## 読み方の罠
- xlsx: openpyxl が無い環境がある → zip + XML 直読。空セルは自己終了タグ、sharedStrings の <rPh>(ふりがな)は除去。
- PDF: 康熙部首の別コードポイントが混ざる → NFKC 正規化してから読む。
- Windows で Python が cp932 で落ちる → sys.stdout.reconfigure(encoding="utf-8")。
- Drive のファイルは同期アプリに掴まれることがある(WinError 5)→ 少し待って再試行。
- 中身は機密。外部サービスに送らない。
"""


def cmd_guide():
    print(GUIDE.format(cmd=self_cmd()))


def cmd_session_start():
    data = {}
    if not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            data = {}
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    root = repo_root(base) or base
    ledgers = []
    if (root / LEDGER).is_file():
        ledgers.append(root)
    try:
        subs = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        subs = []
    ledgers += [p for p in subs if (p / LEDGER).is_file()]
    missing = [p.name for p in subs if p.name.startswith("ws-") and not (p / LEDGER).is_file()]
    if not ledgers and not missing:
        return
    kind = env_kind()
    cmd = self_cmd()
    parts = []
    for d in ledgers:
        led = Ledger(d)
        pend = sum(1 for e in led.entries
                   if e.get("指紋") in ("", PH_PRINT) or e.get("要約") in ("", PH_SUMMARY))
        parts.append("{} ({} 件{})".format("." if d == root else d.name, len(led.entries),
                                          "・要約待ち {}".format(pend) if pend else ""))
    out = ["# 資料台帳 — 起動時の資料提案 (環境: {})".format(ENV_LABEL[kind]), ""]
    out.append("このリポジトリには資料台帳 DOCS.md がある。作業に入る前に、これからやる作業に関連する資料を要約付きで提案すること。")
    if parts:
        out.append("台帳: " + "、".join(parts))
    if missing:
        out.append("台帳なし: " + ", ".join(missing) + "(作るなら scan <dir> --write)")
    out += [
        "",
        "手順:",
        "1. 作業対象(WS のディレクトリ or リポジトリ)とやる作業が分かった時点で 1 回だけ行う。資料と関係しない作業(スクリプト修正・設定変更など)なら行わない。",
        "   起動プロンプトに「資料の提案」の手順が含まれているときは、そちらの順番に従い、二重に提案しない。",
        "2. `{} list <dir>` で台帳を見る。".format(cmd),
    ]
    if kind == "cloud":
        out += [
            "3. これからやる作業に効く資料を最大 4 件選び、「資料名 — 要約 1〜2 文(種別・更新日)— リンク」の一覧で示す。",
            "   クラウドではブラウザを起動できないため、リンクを示すだけにする(GitHub 上の HTML はソース表示になる旨を添える)。",
            "   リンクが無い資料(Drive の実体だけ等)は「ローカル(Mac / Windows)で開ける」と添える。",
        ]
    else:
        out += [
            "3. これからやる作業に効く資料を最大 4 件選び、AskUserQuestion(multiSelect)で「どの資料をブラウザで開きますか？」と聞く。",
            "   label = 資料名、description = 要約 1〜2 文 + 種別・更新日。該当が無ければ一言そう伝えて提案しない。",
            "4. 選ばれた資料を `{} open <dir> <番号>...` で開く。".format(cmd),
        ]
    out += [
        "台帳の手入れ: このセッションで資料を作成・改版したら、`{} scan <dir> --write` → 要約を書く → `stamp`。".format(cmd),
        "書き方は `{} guide`。要約(資料を読む作業)は Agent(general-purpose, model: \"sonnet\") に任せてよい。".format(cmd),
    ]
    print("\n".join(out))


# ---------------------------------------------------------------- main
def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "guide":
        return cmd_guide()
    if cmd == "session-start":
        try:
            return cmd_session_start()
        except Exception as ex:  # フックはセッションを止めない
            print("docs-index session-start: {}".format(ex), file=sys.stderr)
            return
    if not rest:
        sys.exit("ディレクトリを指定してください (--help)")
    d = Path(rest[0]).expanduser()
    if not d.is_dir():
        sys.exit("ディレクトリがありません: {}".format(d))
    d = d.resolve()
    args = rest[1:]
    if cmd == "scan":
        write = "--write" in args
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 20
        show = int(args[args.index("--show") + 1]) if "--show" in args else 15
        backlog_n = int(args[args.index("--backlog") + 1]) if "--backlog" in args else 0
        return cmd_scan(d, write, limit, show, backlog_n)
    if cmd == "list":
        return cmd_list(d)
    if cmd == "open":
        return cmd_open(d, args)
    if cmd == "stamp":
        return cmd_stamp(d, args)
    if cmd == "drop":
        reason = args[args.index("--reason") + 1] if "--reason" in args else ""
        keys = [a for i, a in enumerate(args) if a != "--reason" and (i == 0 or args[i - 1] != "--reason")]
        return cmd_drop(d, keys, reason)
    sys.exit("不明なコマンド: {} (--help)".format(cmd))


if __name__ == "__main__":
    main(sys.argv[1:])
