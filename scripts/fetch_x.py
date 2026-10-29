#!/usr/bin/env python3
"""鈴木のぶこ（@petit_tama3）の X 投稿を取得して、活動報告の下書きデータを作る。

GitHub Actions から週1回実行する想定（.github/workflows/collect-x.yml）。

- 前回取得した最新の投稿より新しいものだけを取りに行く（費用を抑えるため）
- リポストと返信は取得しない
- 写真はダウンロードして長辺1600pxに縮小し、EXIF（位置情報など）を消して保存
- 投稿1件につき activity/posts/<日付>_<ID>.json を作る（status は "pending"）
- 実行結果を activity/last-run.json に残す

必要な環境変数:
  X_BEARER_TOKEN  … X API の Bearer Token（GitHub の Secrets に登録）
任意:
  X_USERNAME      … 既定 petit_tama3
  X_START_ID      … この投稿以降を取得する（初回のみ使用。既定は 2026-10-27 の投稿）
  X_DRY_RUN=1     … API を呼ばず、件数の見積もりだけ表示
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "activity" / "posts"
STATE_FILE = ROOT / "activity" / "state.json"
LAST_RUN = ROOT / "activity" / "last-run.json"
IMG_DIR = ROOT / "img" / "activity"

API = "https://api.x.com/2"
USERNAME = os.environ.get("X_USERNAME", "petit_tama3")
START_ID = int(os.environ.get("X_START_ID", "2114918743256203317"))
MAX_PAGES = 10            # 1回の実行で最大 1,000 件まで（暴走防止）
PHOTO_MAX = 1600          # 写真の長辺(px)
JST = dt.timezone(dt.timedelta(hours=9))


def log(msg: str) -> None:
    print(msg, flush=True)


def api_get(path: str, params: dict | None = None) -> dict:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("X_BEARER_TOKEN が設定されていません（GitHub の Secrets を確認）")
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "my-page-activity"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code == 429 and attempt < 2:
                reset = int(e.headers.get("x-rate-limit-reset", "0") or 0)
                wait = max(5, min(120, reset - int(time.time()))) if reset else 30
                log(f"レート制限（429）。{wait}秒待って再試行します")
                time.sleep(wait)
                continue
            hint = {
                401: "トークンが無効です。Bearer Token を確認してください",
                402: "クレジット残高が不足しているか、月の上限額に達しています",
                403: "このエンドポイントを使う権限がありません",
            }.get(e.code, "")
            raise RuntimeError(f"X API エラー {e.code}: {hint} {body}") from None
    raise RuntimeError("X API の再試行に失敗しました")


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "my-page-activity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def save_photo(data: bytes, dest: Path) -> tuple[int, int]:
    """縮小して EXIF を付けずに JPEG で保存する。"""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)          # 向きを反映してから EXIF を捨てる
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.convert("RGBA").split()[-1])
        im = bg
    im.thumbnail((PHOTO_MAX, PHOTO_MAX), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=82, optimize=True, progressive=True)   # exif を渡さない＝削除
    return im.size


def clean_text(tweet: dict) -> str:
    """t.co の短縮URLを元のURLに戻し、写真用のURLは消す。"""
    text = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text", "")
    ents = (tweet.get("note_tweet") or {}).get("entities") or tweet.get("entities") or {}
    for u in ents.get("urls", []):
        short = u.get("url", "")
        if not short:
            continue
        if u.get("media_key") or "/photo/" in u.get("expanded_url", "") or "/video/" in u.get("expanded_url", ""):
            text = text.replace(short, "")
        else:
            text = text.replace(short, u.get("expanded_url", short))
    return text.strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    started = dt.datetime.now(JST).isoformat(timespec="seconds")
    result = {"started_at": started, "status": "ok", "fetched": 0, "new_posts": 0, "photos": 0, "error": None}
    try:
        state = load_state()
        since_id = state.get("newest_id") or str(START_ID - 1)   # since_id は「より新しい」なので開始投稿を含めるため -1

        if os.environ.get("X_DRY_RUN") == "1":
            log(f"[dry-run] @{USERNAME} の {since_id} より新しい投稿を取得する予定です")
            return 0

        user_id = state.get("user_id")
        if not user_id:
            u = api_get(f"/users/by/username/{USERNAME}")
            user_id = u["data"]["id"]
            log(f"@{USERNAME} のユーザーID: {user_id}")

        params = {
            "since_id": since_id,
            "max_results": 100,
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,entities,attachments,referenced_tweets,note_tweet",
            "expansions": "attachments.media_keys",
            "media.fields": "type,url,preview_image_url,width,height,alt_text",
        }
        tweets, media = [], {}
        for _ in range(MAX_PAGES):
            page = api_get(f"/users/{user_id}/tweets", params)
            tweets += page.get("data", [])
            for m in page.get("includes", {}).get("media", []):
                media[m["media_key"]] = m
            nxt = page.get("meta", {}).get("next_token")
            if not nxt:
                break
            params["pagination_token"] = nxt
        result["fetched"] = len(tweets)
        log(f"取得した投稿: {len(tweets)} 件")

        newest = int(since_id)
        for t in sorted(tweets, key=lambda x: int(x["id"])):
            tid = t["id"]
            newest = max(newest, int(tid))
            created = dt.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(JST)
            post_file = POSTS_DIR / f"{created:%Y-%m-%d}_{tid}.json"
            if post_file.exists():
                continue
            photos, videos = [], []
            for i, key in enumerate(t.get("attachments", {}).get("media_keys", []), 1):
                m = media.get(key)
                if not m:
                    continue
                dest = IMG_DIR / f"{created:%Y}" / f"{created:%m}" / f"{tid}-{i}.jpg"
                rel = dest.relative_to(ROOT).as_posix()
                try:
                    if m["type"] == "photo" and m.get("url"):
                        w, h = save_photo(download(m["url"] + "?name=large"), dest)
                        photos.append({"src": rel, "width": w, "height": h, "alt": m.get("alt_text", "")})
                        result["photos"] += 1
                    elif m.get("preview_image_url"):      # 動画・GIF はサムネイルだけ保存して元の投稿へリンク
                        w, h = save_photo(download(m["preview_image_url"]), dest)
                        videos.append({"poster": rel, "width": w, "height": h, "type": m["type"]})
                except Exception as e:  # 写真1枚の失敗で全体を止めない
                    log(f"  写真の取得に失敗 {tid}-{i}: {e}")
            kinds = {r["type"] for r in t.get("referenced_tweets", [])}
            save_json(post_file, {
                "id": tid,
                "url": f"https://x.com/{USERNAME}/status/{tid}",
                "created_at": created.isoformat(timespec="seconds"),
                "kind": "quote" if "quoted" in kinds else "post",
                "text": clean_text(t),
                "photos": photos,
                "videos": videos,
                "status": "pending",
                "title": "",
                "note": "",
            })
            result["new_posts"] += 1
            log(f"  + {post_file.name}（写真 {len(photos)} / 動画 {len(videos)}）")

        save_json(STATE_FILE, {"username": USERNAME, "user_id": user_id, "newest_id": str(newest),
                               "updated_at": dt.datetime.now(JST).isoformat(timespec="seconds")})
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log(f"エラー: {e}")
    finally:
        if os.environ.get("X_DRY_RUN") != "1":
            result["finished_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
            save_json(LAST_RUN, result)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
