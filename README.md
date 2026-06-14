# santasan（懸賞さん）

X（Twitter）の懸賞・プレゼントキャンペーンへ自動応募するツールです。Yahoo! リアルタイム検索でキャンペーンツイートを収集し、フォロー・リポスト・いいね・リプライを自動実行します。複数アカウント対応、レート制限とジッタ遅延で bot 検出を回避します。

## 機能

- **懸賞ツイート収集**: Yahoo! リアルタイム検索 API からキーワード検索
- **自動分類**: フォロー / リポスト / いいね / リプライ の要件をテキスト解析で判定
- **自動応募**: twikit でフォロー・リポスト・いいね・リプライを実行
- **自然な日本語生成**: RakutenAI（rakutenai）で有機ツイートと返信文を生成
- **複数アカウント管理**: Cookie ファイルベースのセッション（パスワード不要）
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
│   ├── actions.py             # twikit ラッパー（follow / repost / reply / tweet）
│   ├── generator.py           # RakutenAI Python ラッパー
│   ├── scheduler.py           # レート制限つきアクションキュー
│   └── account_manager.py     # マルチアカウント・セッションローダー
├── config.yaml                # 全体設定
└── requirements.txt
```

## セットアップ

### 1. Python 環境

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

追加で BeautifulSoup と lxml が必要です（twikit のパッチ処理に使用）:

```bash
.venv/bin/pip install beautifulsoup4 lxml
```

### 2. Node.js 環境（RakutenAI 生成用）

```bash
cd generator_node
npx jsr add @evex/rakutenai
npm install ai@latest
cd ..
```

### 3. Cookie ファイルの準備

ブラウザ拡張（例: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)）で X のログイン済み Cookie を Netscape 形式でエクスポートし、`cookies/` 以下に配置します。

```
cookies/account1.json   ← ファイル名は .json でも Netscape 形式でも OK
```

> **注意**: パスワードは一切保存しません。Cookie のみ使用します。

### 4. アカウント設定

`accounts/account_configs.yaml` を編集します:

```yaml
accounts:
  - name: "account1"
    cookie_file: "cookies/account1.json"
    is_new: false   # 作成から 1 週間未満なら true（時間あたり上限が半減）
```

### 5. キーワード・レート設定

`config.yaml` で検索キーワードやレート制限を調整できます。デフォルト値は X の利用規約に配慮した安全なレベルに設定されています。

## 実行

### 通常実行（バックグラウンド推奨）

```bash
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

> 1 サイクルは設計上数時間かかります。bot 検出回避のための意図的な遅延です。

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
- VPN を使用すると Error 226（自動化検出）のリスクが高まります
- 同じテキストを繰り返し投稿すると Error 187（重複ツイート）が発生します
- Cookie の有効期限が切れた場合はブラウザで再ログインしてエクスポートし直してください

## 技術スタック

| 用途 | ライブラリ |
|---|---|
| X API アクセス | [twikit](https://github.com/d60/twikit) v2.3.x（Cookie ベース） |
| 日本語テキスト生成 | [rakutenai](https://github.com/evex-dev/rakutenai)（JSR パッケージ） |
| 懸賞ツイート収集 | Yahoo! リアルタイム検索 API |
| HTTP クライアント | httpx |
| 設定ファイル | PyYAML |
