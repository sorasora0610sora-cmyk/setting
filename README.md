# setting — マシン共通の作業ルール

複数マシン(Windows / Mac)で **同じ条件** で Claude Code を動かすための設定リポジトリです。

## 中身

| パス | 役割 |
|---|---|
| `claude/CLAUDE.md` | **正本**。全マシン・全リポジトリに効かせる共通作業ルール |
| `install.sh` | 正本を このマシンの所定の場所へ配置する |

## 使い方

### 初回(このマシン / 別マシン 共通)

```sh
cd ~/src            # Windows は /c/Users/ohsuk/src, Mac は /Users/junyasugiyama/src
git clone git@github.com:sorasora0610sora-cmyk/setting.git
cd setting
./install.sh              # → ../CLAUDE.md (= src/CLAUDE.md) へ配置
./install.sh --global     # → さらに ~/.claude/CLAUDE.md へも配置(全プロジェクトに効く)
```

### 更新したとき

```sh
# 直すのは 正本だけ
vi claude/CLAUDE.md
git commit -m "..." -- claude/CLAUDE.md && git push

# 各マシンで
cd ~/src/setting && git pull && ./install.sh
```

### 確認だけしたいとき

```sh
./install.sh --check      # 配置せず、正本との差分を表示
```

## なぜこの形なのか

- **`src/` は git 管理外**です。ここに直接 `CLAUDE.md` を置いても他マシンには同期されません。
  そこで **正本をこのリポジトリに置き、`install.sh` で `src/CLAUDE.md` へコピー**します。
- Claude Code は **カレントディレクトリから親へ向かって** `CLAUDE.md` を拾うため、
  `src/CLAUDE.md` を置けば `src/` 配下のどのリポジトリで起動しても効きます。
- `~/.claude/CLAUDE.md`(`--global`)は **そのマシンの全プロジェクト**に効きます。
  `src/` の外でも効かせたいときだけ付けてください。
- 配置先は**コピー**です。シンボリックリンクにしていないのは、Windows でリンク作成に
  管理者権限や開発者モードが要る場合があるためです。そのぶん**更新のたびに `install.sh` の再実行が要ります**。
- 既存の配置先が正本と違う場合、上書き前に `.bak-<日時>` へ退避します。

## 効力の範囲(優先順)

```
~/.claude/CLAUDE.md          ← --global 指定時。このマシンの全プロジェクト
  └ src/CLAUDE.md            ← install.sh の既定。src 配下の全リポジトリ
      └ <repo>/CLAUDE.md     ← 各リポジトリ固有
          └ <repo>/<ws>/CLAUDE.md  ← 案件固有(例: asunaro-ops の WS-PJ011)
```

**案件固有のルールは正本に書かないでください。** 下の階層の `CLAUDE.md` に書きます。
