# docs-index — 起動時の「この資料を開きますか？」提案

セッションを立ち上げたとき、これからやる作業に関連する資料を **要約付きで**
「○○ の資料をブラウザで開きますか？」と提案させる仕組みです。Windows / Mac / クラウドセッション共通。

## 構成

| もの | 置き場所 | 役割 |
|---|---|---|
| 資料台帳 `DOCS.md` | asunaro-ops は `ws-*/DOCS.md`、他リポジトリはルート | 資料 1 件 = 1 節(場所・種別・更新・指紋・関連・要約)。**git で同期**するので Mac・クラウドでも同じものが見える |
| `docs-index.py` | 各リポジトリの `.claude/docs-index.py`(正本はここ) | 台帳と実物の差分(scan)・一覧(list)・オープン(open)・指紋の記録(stamp)・起動時の案内(session-start) |
| SessionStart フック | 各リポジトリの `.claude/settings.json` | 起動時に「台帳がある・こう提案せよ」を Claude の文脈へ入れる。**リポジトリ側に置くのでクラウドでも走る**(`~/.claude` はクラウドに届かない) |
| ランチャー | asunaro-ops `scripts/launch-today-ws.sh` | WS 起動プロンプトに「台帳の手入れ(背景・Sonnet)」と「Grill 後の資料提案」を組み込み済み |

## 流れ

1. **起動** → フック(とランチャーの起動プロンプト)が手順を入れる。
2. **作業が決まったら** → `list` で台帳を見て、作業に効く資料を最大 4 件選び、
   AskUserQuestion で「どの資料をブラウザで開きますか？」(選択肢の説明 = 要約)。選ばれたら `open`。
   - Windows: 既定のブラウザ / アプリ(`os.startfile`)、Mac: `open`
   - クラウド: ブラウザは開けないので**リンクを示す**(GitHub の URL / Drive・Google ドキュメントの URL)。
     GitHub Pages は無いため、**HTML は GitHub 上でソース表示**になる。Drive の実体だけで URL 未登録の資料は開けない。
3. **台帳の手入れ(情報収集)** → `scan` が実物との差分を出し、`scan --write` が新しい資料の枠を足す。
   要約は Claude(Sonnet のサブエージェント)が資料を読んで書き、`stamp` で指紋を記録する。手順は `guide`。

## 何を集めるか

- リポジトリ内: `.html .pdf .docx .xlsx .pptx`(+ `.gdoc` 等)。週プラン HTML・`_old/`・`sources/`・`*_DB/`・`- コピー` は除外。
- Google Drive: 台帳の `Drive:` 行のフォルダ(マイドライブからの相対)。`ws-pjNNN` は `*/PJ-NNN_*` を自動で設定。
  Windows = `~/マイドライブ`(ミラー)、Mac = `~/Library/CloudStorage/GoogleDrive-*/マイドライブ`。クラウドには無い。
- URL: `STATUS.md` 等に出てくる Google ドキュメント / Drive / Notion / surge.sh / github.io。
- Drive / Notion の検索(コネクタ): 台帳の `検索語:` で週 1 回(`外部収集:` の日付で判定)。
- **版違いは 1 件にまとめて最新だけ**を載せる。新しさ = 名前先頭の YYMMDD > 名前末尾の日付 > 更新日 > 版番号 > mtime。
  版番号の大番号(V1 / V2)は別系列として扱う(並走する運用があるため)。
- **自動で足すのは「最終走査」以後に増えた・更新された資料だけ**。台帳を作るときは新しい順に 20 件。
  それより古いものは件数だけ報告し、`scan --write --backlog N` で足す(台帳を際限なく膨らませないため)。

## コマンド

```sh
python3 .claude/docs-index.py scan  <dir> [--write] [--limit N] [--backlog N]
python3 .claude/docs-index.py list  <dir>
python3 .claude/docs-index.py open  <dir> <番号>...
python3 .claude/docs-index.py stamp <dir> <番号 or 場所>...
python3 .claude/docs-index.py guide
```

Windows は `python`。

## 別のリポジトリに入れる

```sh
cd ~/src/setting
./install.sh --repo ../<リポジトリ>      # .claude/docs-index.py を配置。settings.json が無ければフック付きで作る
python3 ../<リポジトリ>/.claude/docs-index.py scan ../<リポジトリ> --write   # ルートに DOCS.md を作る
# → 要約を書いて stamp → .claude/ と DOCS.md を commit & push(クラウド・Mac に届けるため)
```

既に `.claude/settings.json` があるリポジトリは自動では書き換えません。`settings.hook.json` の
`SessionStart` を手で足してください(`install.sh --check --repo` で状態を確認できます)。

## 直すとき

正本はこのディレクトリの `docs-index.py`。直したら各リポジトリへ `./install.sh --repo <dir>` で配り直し、
リポジトリ側でも commit & push する(配置先はコピー)。
