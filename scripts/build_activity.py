#!/usr/bin/env python3
"""activity/posts/*.json から活動報告ページを作る。

- status が "published" の投稿だけを掲載（pending / hidden は載せない）
- activity/index.html を生成
- トップページ index.html の <!-- ACTIVITY:START --> 〜 <!-- ACTIVITY:END --> に最新3件を差し込む

使い方:  python3 scripts/build_activity.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "activity" / "posts"
OUT = ROOT / "activity" / "index.html"
HOME = ROOT / "index.html"
WEEK = "月火水木金土日"
URL_RE = re.compile(r"https?://[^\s<>\"']+")
TAG_RE = re.compile(r"(?<![\w&])#([^\s#。、！？!?,.()（）「」]+)")


def load_posts() -> list[dict]:
    posts = []
    for f in sorted(POSTS_DIR.glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("status") == "published":
            posts.append(p)
    posts.sort(key=lambda p: int(p["id"]), reverse=True)
    return posts


def jdate(iso: str) -> str:
    d = dt.datetime.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日（{WEEK[d.weekday()]}）"


def rich(text: str) -> str:
    """本文をHTMLに：エスケープ → URL・ハッシュタグをリンク化 → 改行を <br>。"""
    out, pos = [], 0
    for m in URL_RE.finditer(text):
        out.append(_tags(html.escape(text[pos:m.start()])))
        url = m.group(0).rstrip("）)」.,、。")
        tail = m.group(0)[len(url):]
        shown = re.sub(r"^https?://(www\.)?", "", url)
        shown = shown if len(shown) <= 40 else shown[:38] + "…"
        out.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(shown)}</a>{html.escape(tail)}')
        pos = m.end()
    out.append(_tags(html.escape(text[pos:])))
    return "".join(out).replace("\n", "<br>")


def _tags(s: str) -> str:
    return TAG_RE.sub(lambda m: f'<a class="tag" href="https://x.com/hashtag/{m.group(1)}" target="_blank" rel="noopener">#{m.group(1)}</a>', s)


def title_of(p: dict) -> str:
    if p.get("title"):
        return p["title"]
    first = (p.get("text") or "").strip().splitlines()[0] if p.get("text") else "活動報告"
    return first if len(first) <= 32 else first[:31] + "…"


def media_html(p: dict, prefix: str) -> str:
    items = []
    for ph in p.get("photos", []):
        alt = html.escape(ph.get("alt") or title_of(p))
        items.append(f'<a href="{prefix}{ph["src"]}" target="_blank"><img src="{prefix}{ph["src"]}" alt="{alt}" '
                     f'width="{ph["width"]}" height="{ph["height"]}" loading="lazy"></a>')
    for v in p.get("videos", []):
        items.append(f'<a class="video" href="{html.escape(p["url"])}" target="_blank" rel="noopener" aria-label="Xで動画を見る">'
                     f'<img src="{prefix}{v["poster"]}" alt="動画のサムネイル" width="{v["width"]}" height="{v["height"]}" loading="lazy"></a>')
    if not items:
        return ""
    return f'<div class="media n{min(len(items), 4)}">' + "".join(items[:4]) + "</div>"


def band_css() -> str:
    m = re.search(r'\.sg-hero \{[^}]*?background: (url\("[^"]*"\))', HOME.read_text(encoding="utf-8"))
    return m.group(1) if m else "none"


PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>活動報告｜鈴木のぶこ 日本保守党 東京都江東区 政策委員</title>
  <meta name="description" content="日本保守党 東京都江東区 政策委員 鈴木伸子（すずき のぶこ）の活動報告。街頭活動や区政の調査など、日々の活動を記録しています。">
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
  <link rel="icon" href="../favicon.ico" sizes="32x32">
  <link rel="apple-touch-icon" href="../apple-touch-icon.png">
  <meta name="theme-color" content="#2b7fd4">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@700;900&family=Noto+Sans+JP:wght@400;500;700&family=Quicksand:wght@700&display=swap" rel="stylesheet">
  <style>
    :root {{ --blue:#2b7fd4; --blue-deep:#1f63b0; --sky:#5bb8f0; --ice:#f0f8fe; --pink:#f07fa3; --text:#2b3a55; --muted:#66758f; --cream:#fffaf5; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Noto Sans JP", system-ui, sans-serif; color: var(--text); background: var(--cream); line-height: 1.9; }}
    a {{ color: var(--blue-deep); }}
    .wrap {{ max-width: 760px; margin: 0 auto; padding: 0 16px; }}
    header {{ position: relative; color: #fff; padding: 22px 0 110px; background: linear-gradient(150deg, #8fd0f5 0%, #5bb8f0 40%, #3d93e0 100%); overflow: hidden; }}
    header .wave {{ position: absolute; left: 0; right: 0; bottom: 0; height: 75px; background: {band} repeat-x 0 0 / 60px 75px; }}
    .bar {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    .logo {{ color: #fff; text-decoration: none; font-family: "Zen Maru Gothic", sans-serif; font-weight: 900; font-size: 1.3rem; letter-spacing: .06em; line-height: 1.2; }}
    .logo small {{ display: block; font-size: .62rem; letter-spacing: .14em; opacity: .9; }}
    .back {{ color: #fff; text-decoration: none; font-weight: 700; font-size: .88rem; padding: 7px 16px; border-radius: 999px; background: rgba(255,255,255,.25); border: 1.5px solid rgba(255,255,255,.7); white-space: nowrap; }}
    h1 {{ margin: 48px 0 0; text-align: center; font-family: "Zen Maru Gothic", sans-serif; font-weight: 900; font-size: clamp(1.9rem, 6vw, 2.6rem); letter-spacing: .06em; text-shadow: 0 3px 18px rgba(31,99,176,.3); }}
    .en {{ display: block; text-align: center; font-family: "Quicksand", sans-serif; font-size: .85rem; letter-spacing: .2em; opacity: .95; }}
    main {{ padding: 44px 0 70px; }}
    .lead {{ text-align: center; color: var(--muted); margin: 0 0 32px; }}
    article {{ background: #fff; border-radius: 26px; padding: 26px 24px; margin-bottom: 22px; box-shadow: 0 10px 28px rgba(43,127,212,.1); border: 2px solid #e3f1fc; }}
    time {{ display: inline-block; font-size: .82rem; font-weight: 700; color: #fff; background: var(--sky); padding: 2px 14px; border-radius: 999px; }}
    article h2 {{ margin: 10px 0 8px; font-family: "Zen Maru Gothic", sans-serif; font-weight: 900; font-size: 1.22rem; line-height: 1.5; color: var(--blue-deep); }}
    .body {{ margin: 0; font-size: .98rem; overflow-wrap: anywhere; }}
    .body a.tag {{ text-decoration: none; }}
    .media {{ display: grid; gap: 6px; margin-top: 16px; border-radius: 18px; overflow: hidden; }}
    .media.n2, .media.n4 {{ grid-template-columns: 1fr 1fr; }}
    .media.n3 {{ grid-template-columns: 2fr 1fr; grid-template-rows: 1fr 1fr; }}
    .media.n3 a:first-child {{ grid-row: span 2; }}
    .media a {{ display: block; position: relative; background: var(--ice); }}
    .media img {{ display: block; width: 100%; height: 100%; object-fit: cover; max-height: 520px; }}
    .media.n2 img, .media.n3 img, .media.n4 img {{ aspect-ratio: 4 / 3; }}
    .media .video::after {{ content: "▶"; position: absolute; inset: 0; margin: auto; width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; background: rgba(31,99,176,.8); color: #fff; font-size: 1.3rem; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 4px 20px; margin-top: 14px; }}
    .src {{ display: inline-flex; align-items: center; gap: 6px; font-size: .85rem; font-weight: 700; text-decoration: none; }}
    .empty {{ text-align: center; color: var(--muted); background: #fff; border-radius: 26px; padding: 40px 20px; }}
    footer {{ text-align: center; font-size: .8rem; color: var(--muted); padding: 0 16px 30px; letter-spacing: .06em; }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div class="bar">
        <a class="logo" href="../"><small>東京都江東区 政策委員</small>鈴木のぶこ</a>
        <a class="back" href="../">トップへ戻る</a>
      </div>
      <h1>活動報告</h1>
      <span class="en">ACTIVITY REPORT</span>
    </div>
    <div class="wave" aria-hidden="true"></div>
  </header>
  <main class="wrap">
    <p class="lead">街頭活動や区政の調査など、日々の活動を記録しています。</p>
{items}
  </main>
  <footer>&copy; 2026 鈴木のぶこ</footer>
</body>
</html>
"""

ARTICLE = """    <article id="p{id}">
      <time datetime="{iso}">{date}</time>
      <h2>{title}</h2>
      <p class="body">{body}</p>
      {media}
      <div class="links"><a class="src" href="{url}" target="_blank" rel="noopener">𝕏 元の投稿を見る →</a>{quoted}</div>
    </article>"""

CARD = """          <a class="act-card" href="activity/#p{id}">
            {thumb}<span class="act-meta"><time datetime="{iso}">{date}</time><b>{title}</b></span>
          </a>"""


def build() -> None:
    posts = load_posts()
    items = "\n".join(ARTICLE.format(
        id=p["id"], iso=p["created_at"], date=jdate(p["created_at"]), title=html.escape(title_of(p)),
        body=rich(p.get("text", "")), media=media_html(p, "../"), url=html.escape(p["url"]),
        quoted=(f'<a class="src" href="{html.escape(p["quoted_url"])}" target="_blank" rel="noopener">引用元の投稿を見る →</a>' if p.get("quoted_url") else ""),
    ) for p in posts) or '    <p class="empty">活動報告は準備中です。</p>'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(PAGE.format(band=band_css(), items=items), encoding="utf-8")

    # トップページの最新3件
    cards = []
    for p in posts[:3]:
        img = (p.get("photos") or [{}])[0].get("src") or (p.get("videos") or [{}])[0].get("poster")
        thumb = f'<img src="{img}" alt="" width="160" height="120" loading="lazy">' if img else '<span class="act-noimg" aria-hidden="true"></span>'
        cards.append(CARD.format(id=p["id"], iso=p["created_at"], date=jdate(p["created_at"]), title=html.escape(title_of(p)), thumb=thumb))
    block = ""
    if cards:
        block = ('\n        <div class="act-latest reveal">\n          <h3>最新の活動報告</h3>\n'
                 + "\n".join(cards)
                 + '\n          <a class="act-more" href="activity/">活動報告をすべて見る →</a>\n        </div>\n        ')
    src = HOME.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- ACTIVITY:START -->).*?(<!-- ACTIVITY:END -->)", lambda m: m.group(1) + block + m.group(2), src, flags=re.S)
    if new == src and "<!-- ACTIVITY:START -->" not in src:
        raise SystemExit("index.html に ACTIVITY マーカーがありません")
    HOME.write_text(new, encoding="utf-8")
    print(f"掲載 {len(posts)} 件 → activity/index.html、トップに {len(cards)} 件")


if __name__ == "__main__":
    build()
