#!/bin/sh
# 工事中モードの切り替え（_redirects の MAINTENANCE-START〜END の行を有効/無効にする）
#   sh scripts/site-mode.sh on      … 工事中ページを表示（トップと活動報告）
#   sh scripts/site-mode.sh off     … 本番ページを表示
#   sh scripts/site-mode.sh status  … 現在の状態を表示
# 切り替えたあと、git commit と git push で Cloudflare に反映されます。
set -e
cd "$(dirname "$0")/.."
F=_redirects
tmp="$F.tmp"

rewrite() {  # $1 = on | off
  awk -v mode="$1" '
    /^# MAINTENANCE-START/ { inblk=1; print; next }
    /^# MAINTENANCE-END/   { inblk=0; print; next }
    inblk && NF {
      line=$0; sub(/^#[ \t]*/, "", line)
      if (mode == "on") print line; else print "# " line
      next
    }
    { print }
  ' "$F" > "$tmp" && mv "$tmp" "$F"
}

is_on() { awk '/^# MAINTENANCE-START/{b=1;next} /^# MAINTENANCE-END/{b=0} b && NF && !/^#/{f=1} END{exit !f}' "$F"; }

case "$1" in
  on)  rewrite on;  echo "工事中モード: ON（工事中ページを表示）" ;;
  off) rewrite off; echo "工事中モード: OFF（本番ページを表示）" ;;
  status|"") if is_on; then echo "現在: 工事中モード ON"; else echo "現在: 工事中モード OFF（本番公開中）"; fi ;;
  *) echo "使い方: sh scripts/site-mode.sh [on|off|status]"; exit 1 ;;
esac
