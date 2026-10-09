#!/bin/sh
# 共通作業ルール(claude/CLAUDE.md)を このマシンへ配置する。
#
#   Windows (Git Bash):  cd ~/src/setting && ./install.sh
#   macOS       :        cd ~/src/setting && ./install.sh
#
# 既定では 正本を「このリポジトリの親ディレクトリ」= src/ 配下へコピーします。
# Claude Code は カレントから親へ向かって CLAUDE.md を拾うため、
# src/ 配下のどのリポジトリで起動しても効きます。
#
#   --global   ~/.claude/CLAUDE.md にも配置する(このマシンの全プロジェクトに効く)
#              あわせて claude/agents/*.md を ~/.claude/agents/ へ配置する
#              (サブエージェント定義はユーザー単位でしか効かないため --global 時のみ)
#   --check    配置せず、現状との差分だけ表示する
#   --help
#
# ⚠️ POSIX sh で書いています(macOS の bash 3.2 でも動かすため)。bashism を足さないこと。

set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC_CANON="$REPO_DIR/claude/CLAUDE.md"
PARENT_DIR=$(dirname -- "$REPO_DIR")          # = src/
TARGET_SRC="$PARENT_DIR/CLAUDE.md"
TARGET_GLOBAL="$HOME/.claude/CLAUDE.md"
AGENTS_SRC_DIR="$REPO_DIR/claude/agents"
AGENTS_TARGET_DIR="$HOME/.claude/agents"

DO_GLOBAL=0
DO_CHECK=0
for a in "$@"; do
  case "$a" in
    --global) DO_GLOBAL=1 ;;
    --check)  DO_CHECK=1 ;;
    --help|-h)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "不明な引数: $a (--help)" >&2; exit 2 ;;
  esac
done

if [ ! -f "$SRC_CANON" ]; then
  echo "ERROR: 正本が見つかりません: $SRC_CANON" >&2
  exit 1
fi

# --- 配置先ごとの処理 ---------------------------------------------------
# place <正本> <配置先> <ラベル>
place() {
  src=$1
  target=$2
  label=$3
  dir=$(dirname -- "$target")

  if [ ! -d "$dir" ]; then
    if [ "$DO_CHECK" -eq 1 ]; then
      echo "  [$label] 親ディレクトリが無い: $dir"
      return 0
    fi
    mkdir -p -- "$dir"
  fi

  if [ -f "$target" ]; then
    if cmp -s -- "$src" "$target"; then
      echo "  [$label] 一致 (更新不要)  $target"
      return 0
    fi
    # 正本と違う = 手で直された可能性。上書き前に必ず控えを取る。
    if [ "$DO_CHECK" -eq 1 ]; then
      echo "  [$label] ⚠️ 差分あり  $target"
      diff -u -- "$target" "$src" | head -40 || true
      return 0
    fi
    bak="$target.bak-$(date +%Y%m%d-%H%M%S)"
    cp -- "$target" "$bak"
    echo "  [$label] 既存を退避 → $bak"
  else
    if [ "$DO_CHECK" -eq 1 ]; then
      echo "  [$label] 未配置  $target"
      return 0
    fi
  fi

  cp -- "$src" "$target"
  echo "  [$label] 配置しました  $target"
}

echo "正本: $SRC_CANON"
echo "配置先:"
place "$SRC_CANON" "$TARGET_SRC" "src"
if [ "$DO_GLOBAL" -eq 1 ]; then
  place "$SRC_CANON" "$TARGET_GLOBAL" "global"
  for f in "$AGENTS_SRC_DIR"/*.md; do
    [ -f "$f" ] || continue
    place "$f" "$AGENTS_TARGET_DIR/$(basename -- "$f")" "agent"
  done
fi

if [ "$DO_CHECK" -eq 0 ]; then
  echo
  echo "確認:"
  echo "  ls -l \"$TARGET_SRC\""
  [ "$DO_GLOBAL" -eq 1 ] && echo "  ls -l \"$TARGET_GLOBAL\" \"$AGENTS_TARGET_DIR\""
  echo
  echo "⚠️ 配置先はコピーです。内容を直すときは正本 ($SRC_CANON) を直して"
  echo "   git commit && git push してから、各マシンで git pull && ./install.sh を実行してください。"
fi
