#!/bin/sh
# 工事中モードの切り替え
#   sh scripts/site-mode.sh on      … 工事中ページを表示
#   sh scripts/site-mode.sh off     … 本番ページを表示
#   sh scripts/site-mode.sh status  … 現在の状態を表示
# 切り替えたあと、git commit と git push で Cloudflare に反映されます。
set -e
cd "$(dirname "$0")/.."
F=_redirects
RULE='/  /maintenance/  200'

case "$1" in
  on)
    sed -i.bak "s|^#[[:space:]]*$RULE|$RULE|" "$F" && rm -f "$F.bak"
    grep -qx "$RULE" "$F" || echo "$RULE" >> "$F"
    echo "工事中モード: ON（工事中ページを表示）" ;;
  off)
    sed -i.bak "s|^$RULE|# $RULE|" "$F" && rm -f "$F.bak"
    echo "工事中モード: OFF（本番ページを表示）" ;;
  status|"")
    if grep -qx "$RULE" "$F"; then echo "現在: 工事中モード ON"; else echo "現在: 工事中モード OFF（本番公開中）"; fi ;;
  *) echo "使い方: sh scripts/site-mode.sh [on|off|status]"; exit 1 ;;
esac
