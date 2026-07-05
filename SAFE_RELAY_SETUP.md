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

## アカウント選択

relay の profile は `x-profile-name` ヘッダーで選択します。

```http
x-profile-name: account1
```

このヘッダーを省略すると relay がランダムに profile を選ぶ可能性が
あるため、santasan では必ず送信してください。

`accounts/account_configs.yaml` の `name` は relay の profile name と
一致させます。

```yaml
accounts:
  - name: "account1"
    is_new: false
  - name: "account2"
    is_new: true
```

legacy twikit path を残す場合のみ `cookie_file` を使います。

## 必要な環境変数

```bash
export USE_SAFE_RELAY=true
export RELAY_SERVER_URL=http://localhost:3000
```

`RELAY_ACCOUNT_ID` はマルチアカウント運用では基本的に使いません。各アクション時に
選ばれた `session.name` を `x-profile-name` として送る設計にします。

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

dry-run でアカウント選択とログを確認したあと、制御済みのテスト投稿で
`like`、`repost`、`tweet`、`reply`、最後に `follow` の順で検証します。

実行モードでは起動時に `GET /profiles` を確認し、`accounts/account_configs.yaml`
にある profile が relay に存在しない場合は停止します。`--dry-run` では relay
未起動でもログ確認できるよう、この preflight は省略されます。

## 注意

- santasan では IP アドレスやネットワーク経路は制御しません。
- Web サイトから端末の MAC アドレスは通常見えません。
- ブラウザ fingerprint 偽装や検知回避ロジックは実装しません。
- アカウントごとの profile directory、CDP endpoint、ログイン状態を共有しないでください。
- relay 側で X のログイン challenge が出た場合は、ブラウザ UI で手動対応が必要です。

## 参考

- [twitter_api_safe_relay](https://github.com/fa0311/twitter_api_safe_relay)
- [SAFE_RELAY_INVESTIGATION.md](SAFE_RELAY_INVESTIGATION.md)
