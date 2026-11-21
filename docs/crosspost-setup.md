# X の投稿を Threads・Instagram に自動で転載する（準備の手順）

鈴木のぶこ（@petit_tama3）が X に投稿すると、3時間以内に同じ内容が Threads と Instagram にも投稿されます。
仕組みは GitHub Actions（`.github/workflows/collect-x.yml`）と `scripts/crosspost.py` で、
Meta（Instagram・Threads の運営会社）の公式 API を使います。費用はかかりません。

この手順で用意するのは、GitHub に登録する3つの Secret です。

| Secret 名 | 中身 | 手順 |
|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | Instagram のアクセストークン | 1〜2 |
| `THREADS_ACCESS_TOKEN` | Threads のアクセストークン | 3 |
| `GH_SECRETS_TOKEN` | トークンを自動で延長するための GitHub のトークン | 4 |

片方の SNS だけ先に始めることもできます（トークンが無い SNS は飛ばします）。

---

## 1. Instagram をプロアカウントにする（鈴木さんのスマホで）

1. Instagram アプリで、プロフィール → 右上の「≡」→「アカウントの種類とツール」→「プロアカウントに切り替える」
2. 種類は「クリエイター」か「ビジネス」のどちらでも構いません（政治家・公人なら「クリエイター」が自然です）
3. アカウントは **公開** にしておきます

Facebook ページとの連携は不要です（「Instagram ログインによる API」を使うため）。

## 2. Instagram 用のアプリを作り、トークンを発行する

1. <https://developers.facebook.com/> に Facebook アカウントでログインし、開発者として登録します（Heureka さんのアカウントで可）
2. 「アプリを作成」→ ユースケースで **「Instagram でメッセージとコンテンツを管理」** を選ぶ → アプリ名（例：`nobuko-crosspost`）を付けて作成
3. 左のメニュー「ユースケース」→ Instagram の「カスタマイズ」→「アクセス許可」で、
   **`instagram_business_basic`** と **`instagram_business_content_publish`** が追加されていることを確認（無ければ追加）
4. 「Instagram ログインによる API 設定」→「アクセストークンを生成」→「アカウントを追加」
   → 鈴木さんの Instagram でログインして許可します
   - 招待の承認を求められたら、Instagram の「設定」→「アプリとウェブサイト」→「テスターへの招待」で承認します
5. 追加したアカウントの横の「トークンを生成」を押し、表示されたトークンをコピーします（有効期限 60 日）
6. GitHub のリポジトリ → Settings → Secrets and variables → Actions →「New repository secret」で
   名前 `INSTAGRAM_ACCESS_TOKEN` として登録します

アプリは「開発モード」のままで大丈夫です。自分たちのアカウントに投稿するだけなら、アプリの審査やビジネス認証は要りません。

## 3. Threads 用のアプリを作り、トークンを発行する

1. 開発者画面で、もう1つアプリを作成 → ユースケースで **「Threads API にアクセス」** を選ぶ
2. 「ユースケース」→ Threads の「カスタマイズ」→「アクセス許可」で **`threads_basic`** と **`threads_content_publish`** を追加
3. 同じ画面の「設定」で、**コールバック URL（リダイレクト URL）** にサイトの URL（例：`https://〜.pages.dev/`）を入れて保存。
   アンインストール・削除のコールバック URL にも同じ URL を入れておきます
4. 「アプリの役割」→「役割」→「メンバーを追加」→「Threads テスター」に `petit_tama3` を追加
   → 鈴木さんの Threads で「設定」→「アカウント」→「ウェブサイトのアクセス許可」→「招待」から承認します
5. Mac のターミナルで、リポジトリのフォルダに移動して次を実行します

   ```sh
   python3 scripts/threads_token.py
   ```

   Threads アプリ ID・App Secret（「アプリの設定」→「ベーシック」にある **Threads 用**のもの）とコールバック URL を入力し、
   表示された URL を鈴木さんの Threads にログインしたブラウザで開いて許可します。
   移動した先のアドレスバーの URL を貼り付けると、長期トークンが表示されます
   （`gh` コマンドが使えれば、そのまま Secret `THREADS_ACCESS_TOKEN` に登録できます）

Threads のプロフィールも **公開** にしておいてください。非公開だとトークンの延長ができなくなります。

## 4. トークンを自動で延長する設定

どちらのトークンも 60 日で切れるので、毎週水曜に `.github/workflows/refresh-meta-tokens.yml` が延長して、Secret を書き換えます。
そのための GitHub のトークンを1つ作ります。

1. GitHub → 右上のアイコン → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** →「Generate new token」
2. Repository access は「Only select repositories」で `suzuki-nobuko-koto/my-page` だけを選ぶ
3. Permissions の Repository permissions で **Secrets** を「Read and write」にする（他は不要）
4. 有効期限は最長（1年）にして作成し、表示されたトークンを Secret `GH_SECRETS_TOKEN` として登録します
   - このトークンの期限が来たら、作り直して登録し直してください（GitHub からメールで予告が届きます）

## 5. 動かしてみる

1. GitHub の Actions →「collect-x」→「Run workflow」で1回実行します
2. **初回は転載しません。**「この投稿より新しいものから転載する」という起点を記録するだけです
   （これまでの投稿がまとめて流れないようにするため）
3. その後、鈴木さんが X に投稿すると、3時間以内に Threads・Instagram に転載されます
4. 「refresh-meta-tokens」も一度「Run workflow」で実行しておくと、延長の設定が正しいか確かめられます
   （トークンを発行した当日は「発行から24時間以上たっていない」ため失敗します。翌日以降に試してください）

---

## 転載のルール

| | Threads | Instagram |
|---|---|---|
| 本文 | X の本文そのまま。500字を超える分は省略して X へのリンクを付ける | X の本文そのまま（キャプション） |
| 写真付きの投稿 | 写真（最大4枚）と本文 | 写真と本文。縦横比が Instagram の範囲外なら余白を足す（切り取らない） |
| 写真が無い投稿 | 本文だけで投稿 | 本文を画像カード（サイトと同じ配色・フォント）にして投稿。長文は複数枚 |
| 引用ポスト | 引用元の X の URL を本文の最後に付ける | 「X の投稿を引用しています」と書き添える |
| 動画付きの投稿 | サムネイル画像と「動画は X で」の案内 | 同じ |

- リポスト・返信は転載しません
- 本文中の `@ユーザー名` は全角の「＠」に置き換えます。X と Threads・Instagram では同じ名前が別人のことがあり、
  間違ってタグ付けしないためです
- 投稿から 7 日以上たったものは転載しません。1回の実行で最大 5 件です
- 失敗したときは 3 回まで自動で再試行し、Actions の実行結果が赤くなります（GitHub からメールが届きます）

## 記録の場所

転載に使った画像と、どの投稿をどこに転載したかの記録は **`sns-media` ブランチ** にあります（main には入りません）。

- `state.json` … 投稿ごとの転載先の ID・日時・エラー内容。`since_id` が転載の起点
- `media/<投稿ID>/` … 転載待ちの画像（転載が済むと次の実行で消えます）

## 止めたいとき

- 一時的に止める：Secret `THREADS_ACCESS_TOKEN` / `INSTAGRAM_ACCESS_TOKEN` を削除する（X からの取得と活動報告の下書きはそのまま動きます）
- 特定の投稿を転載させない：その投稿の ID を `sns-media` ブランチの `state.json` の `posts` に、
  `{"threads": {"media_id": "skip"}, "instagram": {"media_id": "skip"}}` として書き足す
- 転載してしまった投稿は、Threads・Instagram のアプリから手で削除してください
