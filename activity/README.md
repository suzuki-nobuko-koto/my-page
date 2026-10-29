# 活動報告（X の投稿から作るページ）

## 仕組み

1. **収集**：GitHub Actions（`.github/workflows/collect-x.yml`）が毎週月曜 6:00 に
   `scripts/fetch_x.py` を実行し、@petit_tama3 の新しい投稿を取得します。
   結果は `activity-draft` ブランチにコミットされ、main 向けのプルリクエストができます。
2. **選定**：各投稿の `status` を決め、必要ならタイトルを付けます（Claude が下書きします）。
3. **生成**：`python3 scripts/build_activity.py` で `activity/index.html` と、トップページの「最新の活動報告」を作り直します。
4. **公開**：プルリクエストを確認して main にマージすると、Cloudflare が自動で公開します。

工事中モードの間は、`/activity/` も工事中ページになります（`_redirects`）。

## ファイル

| パス | 内容 |
|---|---|
| `activity/posts/<日付>_<投稿ID>.json` | 投稿1件分のデータ |
| `img/activity/<年>/<月>/<投稿ID>-<番号>.jpg` | 写真（長辺1600px・位置情報などのEXIFは削除済み） |
| `activity/state.json` | 前回どこまで取得したか（次回はこれより新しい投稿だけを取得） |
| `activity/last-run.json` | 直近の実行結果（件数・エラー） |

## 投稿データの項目

```json
{
  "id": "2114918743256203317",
  "url": "https://x.com/petit_tama3/status/…",
  "created_at": "2026-10-27T12:14:56+09:00",
  "kind": "post",            // post（通常） / quote（引用）
  "text": "本文（X の原文のまま）",
  "photos": [{ "src": "img/activity/…jpg", "width": 1600, "height": 1067, "alt": "" }],
  "videos": [{ "poster": "img/activity/…jpg", "width": 1280, "height": 720, "type": "video" }],
  "status": "pending",       // pending（未確認） / published（掲載） / hidden（掲載しない）
  "title": "",               // 空なら本文の1行目を使う
  "note": ""                 // 選定のメモ（ページには出ない）
}
```

## 掲載の基準

- 載せる：写真付きの活動報告（街頭活動・議会傍聴・情報公開請求・調査など）
- 載せない：個人的な投稿、他の人への批判、真偽が確認できない内容
- 一般の方の顔がはっきり写っている写真は載せない（党員の方は事前に了解をもらう）
- 他の人が撮った写真は、撮影者の了解をもらってから載せる
- 選挙の告示前は「投票してください」にあたる表現を載せない（事前運動の禁止）
- 本文は原文のまま載せ、元の投稿へのリンクを付ける
- X で投稿を削除したときは、`status` を `hidden` にする
