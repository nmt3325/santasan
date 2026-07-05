# santasan（懸賞さん）

X（Twitter）の懸賞・プレゼントキャンペーンへ自動応募するツールです。Yahoo! リアルタイム検索でキャンペーンツイートを収集し、フォロー・リポスト・いいね・リプライを自動実行します。複数アカウント、レート制限、ジッタ遅延に対応します。

## 機能

- **懸賞ツイート収集**: Yahoo! リアルタイム検索 API からキーワード検索
- **自動分類**: フォロー / リポスト / いいね / リプライ の要件をテキスト解析で判定
- **自動応募**: Safe Relay adapter または legacy twikit path でフォロー・リポスト・いいね・リプライを実行
- **自然な日本語生成**: RakutenAI（rakutenai）で有機ツイートと返信文を生成
- **複数アカウント管理**: Safe Relay ではアカウントごとに別ブラウザ profile、legacy twikit では Cookie ファイルベース
- **レート制限ガード**: 時間・日次の上限を超えないよう自動制御
- **ジッタ遅延**: アクション間に 5〜30 分のランダム待機で人間らしく振る舞う
- **Dry-run モード**: 実際には何もせずシミュレーション実行
- **全アクションをログ記録**: `logs/actions.log` にタイムスタンプ付きで記録

## ディレクトリ構成

```
santasan/
├── accounts/
│   └── account_configs.yaml   # アカウント一覧（name / cookie_file / is_new）
├── cookies/
│   └── {account_name}.json    # Cookie ファイル（Netscape 形式 or JSON）
├── logs/
│   └── actions.log            # 全アクション記録
├── generator_node/
│   ├── package.json           # Node.js 依存（@evex/rakutenai, ai）
│   └── generate.mjs           # RakutenAI 呼び出しスクリプト
├── src/
│   ├── main.py                # エントリーポイント
│   ├── search.py              # Yahoo! リアルタイム検索スクレイパー
│   ├── classify.py            # 懸賞判定クラシファイア
│   ├── actions.py             # アクション facade（follow / repost / reply / tweet）
│   ├── safe_relay.py          # Safe Relay adapter
│   ├── generator.py           # RakutenAI Python ラッパー
│   ├── scheduler.py           # レート制限つきアクションキュー
│   └── account_manager.py     # マルチアカウント・セッションローダー
├── config.yaml                # 全体設定
└── requirements.txt
```

## セットアップ

### Docker Compose（推奨: Debian headless）

`twitter_api_safe_relay`、Chromium、santasan を 1 コンテナにまとめた
all-in-one 構成を用意しています。1つの CDP port `9222` を使い、
アカウントごとに Chrome profile を停止・起動で差し替えます。

```bash
cp .env.example .env
vim .env  # ACCOUNTS=account1,account2,account3 を調整
docker compose build
```

`docker compose build` で buildx plugin を求められる場合は、Debian 側で
`docker-buildx-plugin` を入れてください。

```bash
sudo apt-get update
sudo apt-get install docker-buildx-plugin
```

初回ログインはアカウントごとに実行します。

```bash
docker compose --profile login run --rm login login account1
```

`login` service は Linux host network で起動し、Alaska host の `9222` で
CDP を待ち受けます。SSH tunnel を使う場合は、別ターミナルから Mac で
tunnel を張ります。

```bash
ssh -N -L 9222:127.0.0.1:9222 user@alaska
```

Mac Chrome の `chrome://inspect` で `localhost:9222` を追加し、
表示された target を Inspect して `https://x.com/home` にログインします。
ログインできたら `Ctrl-C` で login container を止めます。

Tailscale IP に Mac から直接つなぐ場合は、必ず firewall で `9222` を
Tailscale interface のみに制限してください。

```bash
sudo ufw allow in on tailscale0 to any port 9222 proto tcp
sudo ufw deny 9222/tcp
```

ログイン生存確認:

```bash
docker compose run --rm santasan verify account1
```

全アカウントを直列実行:

```bash
docker compose run --rm santasan run
```

profile は Docker volume `santasan-stack_chrome_profiles` の
`/data/chrome/<account>` に保存されます。アカウント追加時は `.env` の
`ACCOUNTS` に追加し、そのアカウントで login を 1 回実行してください。
`accounts/account_configs.yaml` の `relay_profile` は書かないか、全アカウント
`active` にしてください。

### 1. Python 環境

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

legacy twikit path 用の BeautifulSoup と lxml も `requirements.txt` に含まれています。

### 2. Node.js 環境（RakutenAI 生成用）

```bash
cd generator_node
npx jsr add @evex/rakutenai
npm install ai@latest
cd ..
```

### 3. X セッションの準備

推奨は [twitter_api_safe_relay](https://github.com/fa0311/twitter_api_safe_relay) を使う構成です。Safe Relay mode では、santasan 側に Cookie を置かず、relay 側でアカウントごとに完全に別のブラウザ profile を用意します。

例:

```json
{
  "port": 3000,
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

初回ログイン時は `headless: false` または CDP/Kasm Chrome 構成で各 profile に個別ログインし、その `userDataDir` を永続化してください。

legacy twikit path を使う場合のみ、ブラウザ拡張（例: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)）で X のログイン済み Cookie を Netscape 形式でエクスポートし、`cookies/` 以下に配置します。

```text
cookies/account1.json   ← ファイル名は .json でも Netscape 形式でも OK
```

> **注意**: パスワードは一切保存しません。Safe Relay mode ではログイン状態は relay 側のブラウザ profile に保存されます。

### 4. アカウント設定

`accounts/account_configs.yaml` を編集します:

```yaml
accounts:
  - name: "account1"
    cookie_file: "cookies/account1.json"  # legacy twikit path のみ必須
    relay_profile: "account1"             # 省略時は name と同じ
    is_new: false   # 作成から 1 週間未満なら true（時間あたり上限が半減）
```

Safe Relay mode では `name` または `relay_profile` が relay の profile name と一致している必要があります。relay へのリクエストでは `x-profile-name` ヘッダーにこの名前を入れて、対象アカウントを固定します。

### 5. キーワード・レート設定

`config.yaml` で検索キーワードやレート制限を調整できます。デフォルト値は X の利用規約に配慮した安全なレベルに設定されています。

## 実行

### 通常実行（バックグラウンド推奨）

```bash
export USE_SAFE_RELAY=true
export RELAY_SERVER_URL=http://localhost:3000
nohup .venv/bin/python src/main.py > logs/stdout.log 2>&1 &
echo "PID: $!"
```

### ドライラン（アクションなしで動作確認）

```bash
.venv/bin/python src/main.py --dry-run
```

### ディスカバリーモード（ツイートサンプル表示のみ）

```bash
.venv/bin/python src/main.py --discover
```

### ログ確認

```bash
tail -f logs/actions.log
```

## 動作サイクル

1. Yahoo! リアルタイム検索から懸賞ツイートを最大 `results_per_query × キーワード数` 件収集
2. 24 時間以内・未対応のツイートを抽出
3. 有機ツイートを 1 日 2〜5 件投稿（RakutenAI 生成、ツイート間に 5〜30 分の待機）
4. 懸賞ツイートを順番に処理（フォロー → リポスト → いいね → リプライ）
5. 各アクション後に 5〜30 分のランダム待機
6. 30 分スリープ後に次のサイクルへ

> 1 サイクルは設計上数時間かかります。レート制限とアカウント負荷に配慮した意図的な遅延です。

## レート制限（デフォルト）

| 項目 | 上限 |
|---|---|
| アクション / 時（通常アカウント） | 40 |
| アクション / 時（新規アカウント） | 20 |
| フォロー / 時 | 8 |
| フォロー / 日 | 400 |
| いいね / 日（全アカウント合計） | 100 |
| リポスト / 日（全アカウント合計） | 50 |
| リプライ / 日（全アカウント合計） | 30 |
| アクション間隔 | 5〜30 分 |
| HTTP 429 / Error 226 時のバックオフ | 60 → 120 → 240 → 480 秒 |

## 注意事項

- X の利用規約および各種ガイドラインを遵守した範囲でご使用ください
- 同じテキストを繰り返し投稿すると Error 187（重複ツイート）が発生します
- Safe Relay mode では、アカウントごとに別 `userDataDir` または別 CDP browser process を使ってください
- relay profile を共有すると、アカウントの Cookie/localStorage が混ざります
- legacy twikit path で Cookie の有効期限が切れた場合はブラウザで再ログインしてエクスポートし直してください

## 技術スタック

| 用途 | ライブラリ |
|---|---|
| X API アクセス | [twitter_api_safe_relay](https://github.com/fa0311/twitter_api_safe_relay) 推奨、twikit は legacy fallback |
| 日本語テキスト生成 | [rakutenai](https://github.com/evex-dev/rakutenai)（JSR パッケージ） |
| 懸賞ツイート収集 | Yahoo! リアルタイム検索 API |
| HTTP クライアント | httpx |
| 設定ファイル | PyYAML |
