#!/usr/bin/env python3
"""鈴木のぶこ（@petit_tama3）の X 投稿を Threads と Instagram に自動で転載する。

GitHub Actions（.github/workflows/collect-x.yml）から、fetch_x.py のあとに2段階で呼ぶ。

  1. prepare … 転載する投稿を選び、各SNS用の画像を作って MEDIA_DIR に置く
                （MEDIA_DIR は sns-media ブランチ。ワークフローがコミットして公開URLにする）
  2. publish … 公開URLの画像を使って Threads / Instagram に投稿し、結果を state.json に記録する

転載のルール
- 対象は activity/posts/*.json（リポスト・返信は fetch_x.py の時点で除外済み）。サイトの掲載可否（status）とは無関係
- 仕組みを有効にした時点より前の投稿は転載しない（初回実行時に「ここから」を記録する）
- 投稿から7日以上たったもの、3回失敗したものは転載しない。1回の実行で最大5件
- 本文の @ユーザー名 は全角の「＠」に置き換える（別のSNSで別人をタグ付けしないため）
- Threads … 本文はそのまま（500字を超える分は省略して X へのリンクを付ける）。写真は最大4枚
- Instagram … 写真があれば写真を、なければ本文を画像カードにして投稿。キャプションは本文
- 動画は X から取得していないので、サムネイル画像と「動画は X で」の案内で転載する

環境変数
  THREADS_ACCESS_TOKEN / INSTAGRAM_ACCESS_TOKEN … 片方だけでも可。無い SNS は飛ばす
  CROSSPOST_DRY_RUN=1  … API を呼ばずに、作る投稿の内容を表示するだけ
  CARD_FONT_DIR        … 画像カード用フォント（ZenMaruGothic-Medium/Bold.ttf）のフォルダ
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "activity" / "posts"
JST = dt.timezone(dt.timedelta(hours=9))

THREADS_API = os.environ.get("THREADS_API", "https://graph.threads.net/v1.0")
IG_API = os.environ.get("INSTAGRAM_API", "https://graph.instagram.com/v23.0")
X_USERNAME = os.environ.get("X_USERNAME", "petit_tama3")

MAX_PER_RUN = int(os.environ.get("CROSSPOST_MAX_PER_RUN", "5"))
MAX_AGE_DAYS = int(os.environ.get("CROSSPOST_MAX_AGE_DAYS", "7"))
MAX_ATTEMPTS = 3
THREADS_LIMIT = 500
IG_CAPTION_LIMIT = 2200
IG_HASHTAG_LIMIT = 30
IG_WIDTH = 1080

# サイトの配色（index.html の CSS 変数と同じ）
C_BLUE, C_BLUE_DEEP, C_SKY, C_ICE = "#2b7fd4", "#1f63b0", "#5bb8f0", "#f0f8fe"
C_PINK, C_PINK_SOFT, C_CREAM = "#f07fa3", "#fde9f0", "#fffaf5"
C_TEXT, C_MUTED, C_WHITE = "#2b3a55", "#66758f", "#ffffff"

PLATFORMS = ("threads", "instagram")


def log(msg: str) -> None:
    print(msg, flush=True)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def now_iso() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def enabled_platforms() -> list[str]:
    return [p for p in PLATFORMS if os.environ.get(f"{p.upper()}_ACCESS_TOKEN", "").strip()]


# ---------------------------------------------------------------- 本文

def normalize(text: str) -> str:
    text = text.replace(" ", "\n").replace(" ", "\n\n").replace("\r\n", "\n")
    # X の @メンションを全角に（メールアドレスの @ はそのまま）
    text = re.sub(r"(?<![\w.])@(?=\w)", "＠", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or cp in (0x200D, 0xFE0F, 0x20E3)
            or 0x2190 <= cp <= 0x21FF or 0x2300 <= cp <= 0x23FF)


def threads_len(text: str) -> int:
    """Threads の文字数。絵文字は UTF-8 のバイト数で数える（公式ドキュメントの説明どおり）。"""
    return sum(len(c.encode("utf-8")) if is_emoji(c) else 1 for c in text)


def cut_to(text: str, limit: int, measure) -> str:
    out = ""
    for ch in text:
        if measure(out + ch) > limit:
            break
        out += ch
    return out.rstrip()


def threads_text(post: dict) -> str:
    text = normalize(post["text"])
    extras = []
    if post.get("videos"):
        extras.append(f"🎥 動画は X でご覧いただけます\n{post['url']}")
    elif post.get("quoted_url"):
        extras.append(post["quoted_url"])
    full = "\n\n".join([text] + extras) if text else "\n\n".join(extras)
    if threads_len(full) <= THREADS_LIMIT:
        return full
    tail = f"…\n\n続きは X で👇\n{post['url']}"
    return cut_to(text, THREADS_LIMIT - threads_len(tail), threads_len) + tail


def instagram_caption(post: dict) -> str:
    text = normalize(post["text"])
    # ハッシュタグは30個まで（超えた分は # を外す）
    count = 0

    def tag(m):
        nonlocal count
        count += 1
        return m.group(0) if count <= IG_HASHTAG_LIMIT else m.group(0)[1:]
    text = re.sub(r"[#＃][^\s#＃]+", tag, text)
    notes = []
    if post.get("videos"):
        notes.append(f"🎥 動画は X（＠{X_USERNAME}）でご覧いただけます")
    elif post.get("kind") == "quote":
        notes.append(f"※ X（＠{X_USERNAME}）の投稿を引用しています")
    caption = "\n\n".join([t for t in [text] + notes if t])
    if len(caption) > IG_CAPTION_LIMIT:
        tail = f"…\n\n続きは X（＠{X_USERNAME}）で"
        caption = text[: IG_CAPTION_LIMIT - len(tail)].rstrip() + tail
    return caption


# ---------------------------------------------------------------- 画像

def font_paths() -> tuple[Path, Path]:
    d = Path(os.environ.get("CARD_FONT_DIR", ROOT / ".cache" / "fonts"))
    return d / "ZenMaruGothic-Medium.ttf", d / "ZenMaruGothic-Bold.ttf"


_cmap_cache: dict[str, set[int]] = {}


def font_cmap(path: Path) -> set[int]:
    if str(path) not in _cmap_cache:
        from fontTools.ttLib import TTFont
        _cmap_cache[str(path)] = set(TTFont(str(path)).getBestCmap())
    return _cmap_cache[str(path)]


def card_text(text: str, cmap: set[int]) -> str:
    """画像カードに載せる本文。ハッシュタグ・URL・フォントに無い文字（絵文字など）を外す。"""
    text = normalize(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#＃][^\s#＃]+", "", text)
    text = "".join(c for c in text if c == "\n" or ord(c) in cmap)
    lines = [re.sub(r"[ \t　]+$", "", ln) for ln in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


NO_LINE_START = set("、。，．：；？！」』）】〕〉》”’…‥!?.,)]}")   # 行頭に置かない（前の行にぶら下げる）
NO_LINE_END = set("「『（【〔〈《“‘([{")                             # 行末に置かない（次の行へ送る）


def wrap(draw, text: str, font, width: int) -> list[str]:
    """1文字ずつ詰めて折り返す。句読点・閉じ括弧はぶら下げ、開き括弧は次の行へ送る。"""
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= width or not cur:
                cur += ch
            elif ch in NO_LINE_START:
                cur += ch
            else:
                carry = ""
                while cur and cur[-1] in NO_LINE_END:
                    carry, cur = cur[-1] + carry, cur[:-1]
                lines.append(cur)
                cur = carry + ("" if ch.isspace() else ch)
        lines.append(cur)
    return lines


def make_text_cards(post: dict, out_dir: Path) -> list[Path]:
    """本文を 1080×1350 の画像カードにする。長い場合は複数枚（最大10枚）に分ける。"""
    from PIL import Image, ImageDraw, ImageFont

    medium, bold = font_paths()
    body = card_text(post["text"], font_cmap(medium))
    if not body:
        body = "X に投稿しました"
    W, H = IG_WIDTH, 1350
    pad_x, top, bottom = 108, 236, 196
    f_head = ImageFont.truetype(str(bold), 40)
    f_small = ImageFont.truetype(str(medium), 30)
    probe = ImageDraw.Draw(Image.new("RGB", (W, H)))
    # 1枚に収まる一番大きい文字サイズを選ぶ。収まらなければ 40px で複数枚に分ける
    for size in (64, 56, 50, 44, 40):
        f_body = ImageFont.truetype(str(medium), size)
        line_h = int(size * 1.7)
        lines = wrap(probe, body, f_body, W - pad_x * 2 - size // 2)
        per_page = (H - top - bottom) // line_h
        if len(lines) <= per_page:
            break
    pages = []
    while lines:
        chunk = lines[:per_page]
        # ページ末尾が空行ならそこで区切る（段落の途中で切らない工夫）
        lines = lines[per_page:]
        while lines and lines[0] == "":
            lines.pop(0)
        pages.append(chunk)
    if len(pages) > 10:
        pages = pages[:10]
        pages[-1][-1] = pages[-1][-1][:-1] + "…"

    created = dt.datetime.fromisoformat(post["created_at"])
    paths = []
    for n, chunk in enumerate(pages, 1):
        im = Image.new("RGB", (W, H), C_CREAM)
        d = ImageDraw.Draw(im)
        # 上の帯（サイトの青）と、ピンクのアクセント
        d.rectangle([0, 0, W, 150], fill=C_BLUE)
        d.rectangle([0, 150, W, 160], fill=C_SKY)
        d.text((pad_x, 75), "鈴木のぶこ", font=f_head, fill=C_WHITE, anchor="lm")
        d.text((W - pad_x, 75), "江東区", font=f_small, fill=C_WHITE, anchor="rm")
        # 本文のカード
        d.rounded_rectangle([56, 196, W - 56, H - 150], radius=36, fill=C_WHITE, outline=C_PINK_SOFT, width=4)
        d.rectangle([56 + 36, 196, 56 + 36 + 120, 204], fill=C_PINK)
        y = top + 12
        if len(pages) == 1:   # 1枚に収まる短い投稿は上下中央に置く
            y = top + 12 + ((H - top - bottom) - len(chunk) * line_h) // 2
        for ln in chunk:
            d.text((pad_x, y), ln, font=f_body, fill=C_TEXT)
            y += line_h
        # 下の行：アカウント名・日付・ページ番号
        foot = f"X ＠{X_USERNAME}　{created:%Y.%m.%d}"
        d.text((pad_x, H - 75), foot, font=f_small, fill=C_MUTED, anchor="lm")
        if len(pages) > 1:
            d.text((W - pad_x, H - 75), f"{n} / {len(pages)}", font=f_small, fill=C_BLUE_DEEP, anchor="rm")
        p = out_dir / f"ig-{n}.jpg"
        im.save(p, "JPEG", quality=90, optimize=True)
        paths.append(p)
    return paths


def fit_ratio(r: float) -> float:
    """Instagram のフィードに載せられる縦横比（4:5 〜 1.91:1）に収める。"""
    return min(max(r, 0.8), 1.91)


def make_ig_photos(srcs: list[Path], out_dir: Path) -> list[Path]:
    """写真を Instagram 用にする。比率が範囲外なら余白を足す（切り取らない）。
    複数枚のときは1枚目の比率に揃える（揃えないと Instagram 側で切り取られるため）。"""
    from PIL import Image

    ims = [Image.open(s).convert("RGB") for s in srcs]
    target = fit_ratio(ims[0].width / ims[0].height)
    paths = []
    for n, im in enumerate(ims, 1):
        W = IG_WIDTH
        H = round(W / target)
        scale = min(W / im.width, H / im.height)
        resized = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), C_CREAM)
        canvas.paste(resized, ((W - resized.width) // 2, (H - resized.height) // 2))
        p = out_dir / f"ig-{n}.jpg"
        canvas.save(p, "JPEG", quality=88, optimize=True)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- 準備

def post_id_of(path: Path) -> str:
    return path.stem.split("_", 1)[1]


def plan(state: dict, platforms: list[str]) -> list[dict]:
    files = sorted(POSTS_DIR.glob("*.json"), key=lambda p: int(post_id_of(p)))
    if "since_id" not in state:
        newest = max((int(post_id_of(p)) for p in files), default=0)
        state["since_id"] = os.environ.get("CROSSPOST_SINCE_ID") or str(newest)
        state["started_at"] = now_iso()
        log(f"初回実行: 投稿ID {state['since_id']} より新しい投稿から転載します（それ以前は転載しません）")
    since = int(state["since_id"])
    limit = dt.datetime.now(JST) - dt.timedelta(days=MAX_AGE_DAYS)
    todo = []
    for f in files:
        post = load_json(f, {})
        pid = post.get("id") or post_id_of(f)
        if int(pid) <= since:
            continue
        rec = state.setdefault("posts", {}).get(pid, {})
        need = [p for p in platforms
                if not rec.get(p, {}).get("media_id") and rec.get(p, {}).get("attempts", 0) < MAX_ATTEMPTS]
        if not need:
            continue
        if dt.datetime.fromisoformat(post["created_at"]) < limit:
            log(f"  - {pid}: {MAX_AGE_DAYS}日以上前の投稿なので転載しません")
            continue
        todo.append({"post": post, "platforms": need})
    return todo[:MAX_PER_RUN]


def prepare(media_dir: Path) -> int:
    platforms = enabled_platforms()
    if not platforms and os.environ.get("CROSSPOST_DRY_RUN") != "1":
        log("THREADS_ACCESS_TOKEN / INSTAGRAM_ACCESS_TOKEN が未設定なので、転載はしません")
        save_json(media_dir / "queue.json", [])
        return 0
    if not platforms:
        platforms = list(PLATFORMS)
    state = load_json(media_dir / "state.json", {})
    todo = plan(state, platforms)
    save_json(media_dir / "state.json", state)
    # 投稿済みの画像は Meta 側に取り込まれているので消す（ブランチを軽く保つ。履歴には残る）
    keep = {item["post"]["id"] for item in todo}
    for d in (media_dir / "media").glob("*"):
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)
    queue = []
    for item in todo:
        post, pid = item["post"], item["post"]["id"]
        d = media_dir / "media" / pid
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        srcs = [ROOT / ph["src"] for ph in post.get("photos", [])] or \
               [ROOT / v["poster"] for v in post.get("videos", [])][:1]
        srcs = [s for s in srcs if s.exists()][:4]
        th_images = []
        for n, s in enumerate(srcs, 1):
            dest = d / f"th-{n}.jpg"
            shutil.copyfile(s, dest)
            th_images.append(dest)
        ig_images = make_ig_photos(srcs, d) if srcs else make_text_cards(post, d)
        rel = lambda ps: [p.relative_to(media_dir).as_posix() for p in ps]  # noqa: E731
        queue.append({
            "id": pid,
            "url": post["url"],
            "platforms": item["platforms"],
            "threads": {"text": threads_text(post), "images": rel(th_images)},
            "instagram": {"caption": instagram_caption(post), "images": rel(ig_images),
                          "text_card": not srcs},
        })
        log(f"  + {pid}: Threads 画像{len(th_images)}枚 / Instagram 画像{len(ig_images)}枚"
            f"{'（本文カード）' if not srcs else ''} → {', '.join(item['platforms'])}")
    save_json(media_dir / "queue.json", queue)
    log(f"転載予定: {len(queue)} 件")
    return 0


# ---------------------------------------------------------------- 投稿

class ApiError(RuntimeError):
    pass


def call(method: str, url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url, data = url + "?" + data.decode(), None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "my-page-crosspost"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        # エラー本文にトークンが含まれないよう念のため伏せる
        for key in ("THREADS_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN"):
            tok = os.environ.get(key)
            if tok:
                body = body.replace(tok, "***")
        raise ApiError(f"HTTP {e.code}: {body}") from None


def wait_ready(api: str, container: str, token: str, field: str, ok: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    delay = 5
    while True:
        st = call("GET", f"{api}/{container}", {"fields": field, "access_token": token}).get(field, "")
        if st in (ok, "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise ApiError(f"メディアの処理に失敗しました（{st}）")
        if time.time() > deadline:
            raise ApiError("メディアの処理が時間内に終わりませんでした")
        time.sleep(delay)
        delay = min(delay * 2, 30)


def publish_threads(item: dict, base_url: str) -> str:
    tok = os.environ["THREADS_ACCESS_TOKEN"].strip()
    api = THREADS_API
    uid = call("GET", f"{api}/me", {"fields": "id", "access_token": tok})["id"]
    text, imgs = item["threads"]["text"], [f"{base_url}/{p}" for p in item["threads"]["images"]]
    if not imgs:
        cid = call("POST", f"{api}/{uid}/threads", {"media_type": "TEXT", "text": text, "access_token": tok})["id"]
    elif len(imgs) == 1:
        cid = call("POST", f"{api}/{uid}/threads",
                   {"media_type": "IMAGE", "image_url": imgs[0], "text": text, "access_token": tok})["id"]
    else:
        kids = []
        for u in imgs:
            k = call("POST", f"{api}/{uid}/threads",
                     {"media_type": "IMAGE", "image_url": u, "is_carousel_item": "true", "access_token": tok})["id"]
            wait_ready(api, k, tok, "status", "FINISHED")
            kids.append(k)
        cid = call("POST", f"{api}/{uid}/threads",
                   {"media_type": "CAROUSEL", "children": ",".join(kids), "text": text, "access_token": tok})["id"]
    wait_ready(api, cid, tok, "status", "FINISHED")
    return call("POST", f"{api}/{uid}/threads_publish", {"creation_id": cid, "access_token": tok})["id"]


def publish_instagram(item: dict, base_url: str) -> str:
    tok = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    api = IG_API
    uid = call("GET", f"{api}/me", {"fields": "user_id,username", "access_token": tok})["user_id"]
    caption, imgs = item["instagram"]["caption"], [f"{base_url}/{p}" for p in item["instagram"]["images"]]
    if len(imgs) == 1:
        cid = call("POST", f"{api}/{uid}/media", {"image_url": imgs[0], "caption": caption, "access_token": tok})["id"]
    else:
        kids = []
        for u in imgs:
            k = call("POST", f"{api}/{uid}/media", {"image_url": u, "is_carousel_item": "true", "access_token": tok})["id"]
            wait_ready(api, k, tok, "status_code", "FINISHED")
            kids.append(k)
        cid = call("POST", f"{api}/{uid}/media",
                   {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption, "access_token": tok})["id"]
    wait_ready(api, cid, tok, "status_code", "FINISHED")
    return call("POST", f"{api}/{uid}/media_publish", {"creation_id": cid, "access_token": tok})["id"]


def publish(media_dir: Path, base_url: str) -> int:
    dry = os.environ.get("CROSSPOST_DRY_RUN") == "1"
    queue = load_json(media_dir / "queue.json", [])
    state = load_json(media_dir / "state.json", {})
    funcs = {"threads": publish_threads, "instagram": publish_instagram}
    failed = 0
    for item in queue:
        rec = state.setdefault("posts", {}).setdefault(item["id"], {"x_url": item["url"]})
        for p in item["platforms"]:
            if dry:
                body = item[p].get("text") or item[p].get("caption")
                log(f"\n[dry-run] {p} ← {item['id']}  画像: {item[p]['images']}\n{body}\n")
                continue
            r = rec.setdefault(p, {})
            try:
                media_id = funcs[p](item, base_url)
                r.update({"media_id": media_id, "posted_at": now_iso()})
                r.pop("error", None)
                log(f"  ✓ {p}: {item['id']} → {media_id}")
            except Exception as e:
                failed += 1
                r["attempts"] = r.get("attempts", 0) + 1
                r["error"] = str(e)[:500]
                r["failed_at"] = now_iso()
                log(f"  ✗ {p}: {item['id']} 失敗（{r['attempts']}回目）: {e}")
            # 二重投稿を防ぐため、1件ごとに保存する
            save_json(media_dir / "state.json", state)
    state["last_run"] = {"at": now_iso(), "queued": len(queue), "failed": failed}
    if not dry:
        save_json(media_dir / "state.json", state)
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["prepare", "publish"])
    ap.add_argument("--media-dir", required=True, type=Path)
    ap.add_argument("--base-url", help="publish 時: MEDIA_DIR のファイルが公開されている URL")
    a = ap.parse_args()
    a.media_dir.mkdir(parents=True, exist_ok=True)
    if a.step == "prepare":
        return prepare(a.media_dir)
    if not a.base_url:
        ap.error("publish には --base-url が必要です")
    return publish(a.media_dir, a.base_url.rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
