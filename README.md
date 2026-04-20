# Note Auto Post

`note` の記事を RSS からランダム取得し、Gemini で Threads 向けに要約して自動投稿するプロジェクトです。GitHub Actions を使って定期実行できます。

## 概要

このプロジェクトは次の流れで動きます。

1. `note` の RSS から記事を取得
2. 記事をランダムに 1 件選択
3. Gemini で Threads 向けの本文を生成
4. Threads に親投稿を作成
5. 条件に応じて記事リンク付きリプライを投稿

現在は運用上の安定性を上げるため、以下を実装しています。

- GitHub Actions は毎時 `17分` に実行
- Gemini は一時エラー時に指数バックオフ付きで再試行
- `GEMINI_MODELS` で複数モデルを順に試行
- Threads の投稿コンテナは状態確認後に publish
- 失敗時は GitHub Actions 上でエラー終了

## ファイル構成

- `main.py`: RSS 取得、要約生成、Threads 投稿の本体
- `.github/workflows/post_note.yml`: GitHub Actions の定期実行設定
- `requirements.txt`: ローカル実行用の依存関係

## 必要な環境変数

### ローカル用 `.env`

ローカル実行時はプロジェクト直下に `.env` を置きます。

```env
GEMINI_API_KEY=your_gemini_api_key
THREADS_ACCESS_TOKEN_NOTE=your_threads_access_token
THREADS_USER_ID_NOTE=your_threads_user_id
GEMINI_MODELS=gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash
```

`GEMINI_MODELS` は省略可能です。未設定時は次の順で試します。

```text
gemini-2.5-flash
gemini-2.5-flash-lite
gemini-2.0-flash
```

### GitHub Actions 用

GitHub のリポジトリ設定で以下を用意します。

`Secrets`

- `GEMINI_API_KEY`
- `THREADS_ACCESS_TOKEN_NOTE`
- `THREADS_USER_ID_NOTE`

`Variables`

- `GEMINI_MODELS`  
  例: `gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash`

`GEMINI_MODELS` を設定しない場合でも、コード側のデフォルトモデルで動作します。

## ローカル実行手順

1. Python 3.11 を用意する
2. 依存関係をインストールする
3. `.env` を作成する
4. スクリプトを実行する

```bash
pip install -r requirements.txt
python main.py
```

## GitHub Actions での自動実行

ワークフロー定義は `.github/workflows/post_note.yml` です。

- 実行方式: `schedule` + `workflow_dispatch`
- 定期実行: 日本時間 `08:17` から `00:17` まで 1 時間ごと
- 手動実行: GitHub の `Actions` 画面から `Run workflow`

毎時 `0分` は GitHub Actions の混雑で遅延しやすいため、`17分` 実行にしています。

## Gemini のフォールバック戦略

`main.py` では `GEMINI_MODELS` の先頭から順にモデルを試します。

- 各モデルごとに最大 4 回まで再試行
- `503` や `429` などの一時エラーは指数バックオフで再試行
- 再試行上限に達したら次のモデルへフォールバック
- 全モデル失敗時のみ処理全体を失敗にする

これにより、特定モデルの一時的な高負荷でも投稿が止まりにくくなっています。

## Threads 投稿の流れ

Threads 投稿は次の手順で行います。

1. 親投稿用コンテナを作成
2. コンテナの状態を確認
3. `FINISHED` を確認後に親投稿を publish
4. リンク付きモードの場合はリプライ用コンテナを作成
5. リプライ側も状態確認後に publish

作成直後に即 publish すると `Media Not Found` が起きることがあるため、状態確認を挟んでいます。

## ログの見方

GitHub Actions の `Run post script` で、主に以下を確認します。

- `Fetching RSS feed`
- `Configured Gemini models`
- `Trying Gemini model`
- `Retrying Gemini after`
- `Checking Parent container status`
- `Checking Reply container status`
- `Threads publish status`
- `Success: ...`

`Success:` が出ていれば、現在のコードでは投稿完了まで通過しています。

## よくある失敗例

### Gemini の `503 UNAVAILABLE`

Gemini 側の高負荷です。現在は自動再試行し、それでも失敗した場合は次モデルへフォールバックします。

### Threads の `Media Not Found`

コンテナ作成直後に publish すると起きることがあります。現在は状態確認後に publish するため、以前より起きにくくなっています。

### GitHub Actions が想定時刻に動かない

GitHub Actions の `schedule` は厳密な定刻実行ではありません。高負荷時は遅延することがあります。

## 備考

- `.env` はローカル専用です。機密情報はコミットしないでください。
- 投稿内容は毎回ランダムな記事と、ランダムなリンク有無モードで決まります。
- 本番運用では GitHub Actions のログ確認を前提にすると保守しやすいです。
