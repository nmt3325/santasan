# Twitter API Safe Relay 連携セットアップガイド

このプロジェクトでは、twikit の不安定さを避けるために
[twitter_api_safe_relay](https://github.com/fa0311/twitter_api_safe_relay)
への置き換えを進めます。

## 前提

`twitter_api_safe_relay` は高水準の Twitter client ではありません。
`/follow`、`/like`、`/retweet`、`/tweet` のような独自エンドポイントは
提供しません。

実際に提供される主なエンドポイントは以下です。

- `GET /health`
- `GET /profiles`
- `GET|POST /i/api/graphql/:queryId/:operationName`
- `GET|POST /1.1/*`
- `GET|POST /2/*`

santasan 側では、twikit が作っていた GraphQL/v1.1 リクエストを
relay proxy 経由で送る adapter を使います。

## 推奨 Docker 構成

Debian headless server では、root の `Dockerfile` と `docker-compose.yml` を
使う all-in-one 構成を推奨します。

- 1 image に Chromium、`twitter_api_safe_relay`、santasan を同梱
- container 内の `127.0.0.1:9222` に Chromium CDP を起動
- relay は `active` profile で `http://127.0.0.1:9222` に接続
- entrypoint が account ごとに Chrome profile を差し替えて直列実行
- profile は Docker volume の `/data/chrome/<account>` に永続化

```bash
cp .env.example .env
docker compose build
docker compose --profile login run --rm --service-ports login login account1
docker compose run --rm santasan verify account1
docker compose run --rm santasan run
```

`docker compose build` が buildx plugin を要求する場合は、Debian 側で
`sudo apt-get install docker-buildx-plugin` を実行してください。

Mac からログインするときは、server 側で login container を起動した状態で
SSH tunnel を張り、Mac Chrome の `chrome://inspect` から操作します。

```bash
ssh -N -L 9222:127.0.0.1:9222 user@alaska
```

Tailscale IP に直接接続したい場合は `.env` で `LOGIN_CDP_HOST=0.0.0.0` を
設定します。login container 内の Chromium は login mode だけ
`CDP_BIND=0.0.0.0` で起動します。run mode は `127.0.0.1` のままです。
直接公開する場合は firewall で `9222` を Tailscale interface のみに制限してください。

```bash
sudo ufw allow in on tailscale0 to any port 9222 proto tcp
sudo ufw deny 9222/tcp
```

## アカウント選択

relay の profile は `x-profile-name` ヘッダーで選択します。

```http
x-profile-name: account1
```

このヘッダーを省略すると relay がランダムに profile を選ぶ可能性が
あるため、santasan では必ず送信してください。

通常の複数 profile 構成では、`accounts/account_configs.yaml` の `name` は
relay の profile name と一致させます。

```yaml
accounts:
  - name: "account1"
    is_new: false
  - name: "account2"
    is_new: true
```

legacy twikit path を残す場合のみ `cookie_file` を使います。

### 1 CDP ポート / active profile 構成

Debian headless server では、エラーを減らすために以下の直列運用を推奨します。

```text
account1 Chrome profile -> 127.0.0.1:9222 -> relay profile "active" -> santasan --account account1
account2 Chrome profile -> 127.0.0.1:9222 -> relay profile "active" -> santasan --account account2
account3 Chrome profile -> 127.0.0.1:9222 -> relay profile "active" -> santasan --account account3
```

この構成では relay profile は常に `active` の 1 個だけです。アカウント分離は
relay profile ではなく、Chrome の `--user-data-dir=/data/chrome/<account>` を
停止・起動で差し替えることで実現します。

```bash
export USE_SAFE_RELAY=true
export RELAY_SERVER_URL=http://127.0.0.1:3001
export RELAY_PROFILE_NAME=active
```

`accounts/account_configs.yaml` は santasan 側のアカウント名と rate limit 用に
そのまま複数アカウントを残します。実行時は必ず `--account` を指定します。
`relay_profile` は書かないか、全アカウント `active` にしてください。

```bash
.venv/bin/python src/main.py --account account1 --once
```

## 必要な環境変数

```bash
export USE_SAFE_RELAY=true
export RELAY_SERVER_URL=http://localhost:3000
```

アクティブ profile 構成では `RELAY_PROFILE_NAME=active` を設定してください。
通常の複数 relay profile 構成では、各アクション時に選ばれた `session.name`
または `relay_profile` を `x-profile-name` として送ります。

## relay profile の作り方

各アカウントは完全に別のブラウザ session/profile としてログインします。
このプロジェクトで制御できる範囲では、Cookie、localStorage、browser profile
directory を共有しないでください。

### launch mode

```json
{
  "port": 3000,
  "logLevel": "info",
  "profiles": [
    {
      "name": "account1",
      "browser": {
        "type": "launch",
        "browserType": "chromium",
        "userDataDir": "./user_data/account1",
        "headless": true
      }
    },
    {
      "name": "account2",
      "browser": {
        "type": "launch",
        "browserType": "chromium",
        "userDataDir": "./user_data/account2",
        "headless": true
      }
    }
  ]
}
```

初回ログイン時は一時的に `headless: false` にして、各 profile に別々に
ログインしてください。ログイン後は同じ `userDataDir` を永続化して
`headless: true` で運用できます。

### cdp mode

headless Linux server では、CDP/Kasm Chrome 構成が扱いやすいです。
アカウント分離を強く保つなら、アカウントごとに別 Chromium process と
別 CDP endpoint を用意します。

```json
{
  "port": 3000,
  "logLevel": "info",
  "profiles": [
    {
      "name": "account1",
      "browser": {
        "type": "cdp",
        "browserType": "chromium",
        "cdpEndpoint": "http://127.0.0.1:9222"
      }
    },
    {
      "name": "account2",
      "browser": {
        "type": "cdp",
        "browserType": "chromium",
        "cdpEndpoint": "http://127.0.0.1:9223"
      }
    }
  ]
}
```

1 CDP ポート構成では relay の settings は 1 profile だけにします。

```json
{
  "port": 3000,
  "logLevel": "info",
  "profiles": [
    {
      "name": "active",
      "browser": {
        "type": "cdp",
        "browserType": "chromium",
        "cdpEndpoint": "http://127.0.0.1:9222"
      }
    }
  ]
}
```

all-in-one Docker 構成では Chromium と relay が同一 container 内で動くため、
`127.0.0.1:9222` のままで接続できます。

`twitter_api_safe_relay` の Docker を host から公開する場合は、host 側の
`3001:3000` のように割り当て、santasan では
`RELAY_SERVER_URL=http://127.0.0.1:3001` を使います。

## santasan 側の実装方針

`src/safe_relay.py` は relay-native adapter として実装されています。

必要な内部メソッド:

- `_graphql_post(query_id, operation_name, variables, features=None)`
- `_v11_post(path, data)`

必要な公開メソッド:

- `follow_user(user_id)`
- `retweet(tweet_id)`
- `favorite_tweet(tweet_id)`
- `create_tweet(text, reply_to=None, ...)`

アクションごとの対応:

| santasan action | relay request |
| --- | --- |
| like | `POST /i/api/graphql/lI07N6Otwv1PhnEgXILM7A/FavoriteTweet` |
| repost | `POST /i/api/graphql/ojPdsZsimiJrUGLR1sjUtA/CreateRetweet` |
| tweet/reply | `POST /i/api/graphql/SiM_cAu83R0wnrpmKQQSEw/CreateTweet` |
| follow | `POST /1.1/friendships/create.json` |

`follow` は relay の v1.1 POST が JSON body を読むため、実アカウントで
単独検証してください。

## 接続確認

```bash
curl http://localhost:3000/health
curl http://localhost:3000/profiles
```

期待例:

```json
{"status":"ok","profiles":["account1","account2"]}
```

## 実行例

```bash
export USE_SAFE_RELAY=true
export RELAY_SERVER_URL=http://localhost:3000
.venv/bin/python src/main.py --dry-run
```

1 CDP ポート構成では、Docker entrypoint または外側の orchestrator が
アカウントを切り替えます。

```bash
ACCOUNTS="account1 account2 account3" \
CHROME_DATA_ROOT=/data/chrome \
RELAY_SERVER_URL=http://127.0.0.1:3001 \
RELAY_PROFILE_NAME=active \
scripts/safe-relay-active-cycle.sh
```

dry-run でアカウント選択とログを確認したあと、制御済みのテスト投稿で
`like`、`repost`、`tweet`、`reply`、最後に `follow` の順で検証します。

実行モードでは起動時に `GET /profiles` と `GET /2/users/me` を確認します。
`/2/users/me` が 403/500 の場合は、その Chrome profile が X Web API として
ログイン生存していないため停止します。`--dry-run` では relay 未起動でもログ確認
できるよう、この preflight は省略されます。

dry-run のアクションログは既定で `logs/actions.dryrun.log` に分離されます。
また、本番の重複判定では `DRY_RUN` 行を無視します。

## 注意

- santasan では IP アドレスやネットワーク経路は制御しません。
- Web サイトから端末の MAC アドレスは通常見えません。
- ブラウザ fingerprint 偽装や検知回避ロジックは実装しません。
- アカウントごとの profile directory、CDP endpoint、ログイン状態を共有しないでください。
- 1 CDP ポート構成では同時に起動する Chrome は必ず 1 プロセスだけにしてください。
- Mac からログインする場合は 9222 を外部公開せず SSH tunnel を使ってください。
- relay 側で X のログイン challenge が出た場合は、ブラウザ UI で手動対応が必要です。

## 参考

- [twitter_api_safe_relay](https://github.com/fa0311/twitter_api_safe_relay)
- [SAFE_RELAY_INVESTIGATION.md](SAFE_RELAY_INVESTIGATION.md)
