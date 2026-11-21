#!/usr/bin/env python3
"""Threads の長期アクセストークン（60日）を取得する。最初の1回だけ手元で実行する。

使い方（Mac のターミナルで）:
  python3 scripts/threads_token.py

Meta の開発者画面で確認できる「Threads アプリID」「Threads App Secret」と、
アプリに登録したリダイレクトURL（コールバックURL）を入力すると、ログイン用のURLを表示する。
ブラウザでそのURLを開いて許可すると、リダイレクトURLに移動するので、
そのときのアドレスバーのURLを丸ごと貼り付ける。最後に長期トークンを表示する。

gh コマンドが使えて、ログイン済みなら、そのまま GitHub の Secrets に登録することもできる。
"""
from __future__ import annotations

import getpass
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.threads.net"
REPO = "suzuki-nobuko-koto/my-page"


def request(method: str, url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params)
    req = (urllib.request.Request(url, data=data.encode(), method="POST") if method == "POST"
           else urllib.request.Request(f"{url}?{data}"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"エラー（HTTP {e.code}）: {e.read().decode('utf-8', 'replace')[:500]}")


def main() -> None:
    app_id = input("Threads アプリID: ").strip()
    secret = getpass.getpass("Threads App Secret（入力は表示されません）: ").strip()
    redirect = input("リダイレクトURL（アプリに登録したものと完全に同じ）: ").strip()

    auth = "https://threads.net/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": redirect, "response_type": "code",
        "scope": "threads_basic,threads_content_publish",
    })
    print("\n1) 次のURLを、鈴木さんの Threads にログインしたブラウザで開いて「許可」してください:\n")
    print(auth)
    back = input("\n2) 移動した先のアドレスバーのURLを丸ごと貼り付けてください:\n").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    code = (q.get("code") or [back])[0].split("#")[0]

    short = request("POST", f"{API}/oauth/access_token", {
        "client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
        "redirect_uri": redirect, "code": code,
    })
    long = request("GET", f"{API}/access_token", {
        "grant_type": "th_exchange_token", "client_secret": secret, "access_token": short["access_token"],
    })
    token = long["access_token"]
    me = request("GET", f"{API}/v1.0/me", {"fields": "id,username", "access_token": token})
    days = int(long.get("expires_in", 0)) // 86400
    print(f"\n✓ @{me.get('username')} の長期トークンを取得しました（有効期限 約{days}日）")

    if shutil.which("gh") and input(f"\nGitHub（{REPO}）の Secret THREADS_ACCESS_TOKEN に登録しますか？ [y/N]: ").lower() == "y":
        subprocess.run(["gh", "secret", "set", "THREADS_ACCESS_TOKEN", "--repo", REPO, "--body", token], check=True)
        print("✓ 登録しました")
    else:
        print("\n次のトークンを GitHub の Secret THREADS_ACCESS_TOKEN に登録してください（他人に見せないこと）:\n")
        print(token)


if __name__ == "__main__":
    main()
