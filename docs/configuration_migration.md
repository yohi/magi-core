# 設定移行ガイド

本ガイドでは、System Hardening Refactor (v0.2.0) で導入された新しい設定システム (`MagiSettings`) への移行方法について説明します。
新しいシステムは Pydantic V2 を採用しており、型安全性、バリデーション、および一元管理が強化されています。

## 主な変更点

1.  **フラットな設定構造**: `magi.yaml` のネストされた構造（`streaming: enabled: ...` など）は、フラットなキー（`streaming_enabled: ...`）に移行されました。
    *   *Note*: 互換性維持のため、当面の間は従来のネスト構造も自動的に読み込まれますが、新しいフラット構造への移行を推奨します。
2.  **厳密なバリデーション**: 設定値の型や範囲（例: `timeout` は正の整数）が厳密にチェックされます。不正な値は起動時にエラーとなります。
3.  **環境変数の統一**: 全ての設定は `MAGI_` プレフィックス付きの環境変数で上書き可能です。
4.  **本番運用モード**: `MAGI_PRODUCTION_MODE` が導入され、公開鍵パスの解決などが厳格化されました。

## 環境変数マッピング

新しい設定項目と対応する環境変数は以下の通りです。

| 新設定キー (MagiSettings) | 環境変数 | 説明 | デフォルト値 |
| :--- | :--- | :--- | :--- |
| **API設定** | | | |
| `api_key` | `MAGI_API_KEY` | Anthropic API Key (必須) | - |
| `model` | `MAGI_MODEL` | 使用するモデル | `claude-sonnet-4-20250514` |
| `timeout` | `MAGI_TIMEOUT` | APIタイムアウト(秒) | 60 |
| `retry_count` | `MAGI_RETRY_COUNT` | リトライ回数 | 3 |
| `personas` | `MAGI_PERSONAS` | ペルソナ別設定 (JSON文字列) | `{}` |
| **並行処理 (New)** | | | |
| `llm_concurrency_limit` | `MAGI_LLM_CONCURRENCY_LIMIT` | LLM同時リクエスト数上限 | 5 |
| `plugin_concurrency_limit` | `MAGI_PLUGIN_CONCURRENCY_LIMIT` | プラグイン同時ロード数上限 | 3 |
| `plugin_load_timeout` | `MAGI_PLUGIN_LOAD_TIMEOUT` | プラグインロード制限時間(秒) | 30.0 |
| **ストリーミング** | | | |
| `streaming_enabled` | `MAGI_STREAMING_ENABLED` | ストリーミング出力の有効化 | `False` |
| `streaming_queue_size` | `MAGI_STREAMING_QUEUE_SIZE` | 出力バッファサイズ | 100 |
| `streaming_overflow_policy` | `MAGI_STREAMING_OVERFLOW_POLICY` | バッファ溢れ時の挙動 (`drop`/`backpressure`) | `drop` |
| **Guardrails** | | | |
| `guardrails_enabled` | `MAGI_GUARDRAILS_ENABLED` | Guardrailsの有効化 | `False` |
| `guardrails_timeout` | `MAGI_GUARDRAILS_TIMEOUT` | 評価制限時間(秒) | 3.0 |
| **運用・セキュリティ** | | | |
| `production_mode` | `MAGI_PRODUCTION_MODE` | 本番運用モード (Trueで厳格化) | `False` |
| `plugin_public_key_path` | `MAGI_PLUGIN_PUBLIC_KEY_PATH` | プラグイン検証用公開鍵パス | `None` (本番時必須) |
| `plugin_prompt_override_allowed`| `MAGI_PLUGIN_PROMPT_OVERRIDE_ALLOWED` | プラグインによるプロンプト上書き許可 | `False` |

### 構造化データの環境変数指定

`personas` などの辞書型設定は、環境変数では以下の2通りの方法で指定できます。

#### 1. JSON 文字列 (推奨)

環境変数に JSON 文字列として指定します。`temperature` (0.0-1.0) などの詳細設定も可能です。

```bash
# ペルソナごとのモデルやパラメータをJSONで指定する例（未指定項目はグローバル設定が使用されます）
export MAGI_PERSONAS='{"melchior": {"llm": {"model": "claude-3-opus-20240229", "temperature": 0.0}}, "balthasar": {"llm": {"timeout": 120}}}'
```

#### 2. ネストされた環境変数 (上級者向け/任意)

`__` (ダブルアンダースコア) を区切り文字として使用することで、個別の値をオーバーライドできます。
JSON形式と併用した場合、この**ネスト形式の設定が優先**されます。

```bash
# MELCHIORのモデルのみをピンポイントで変更する場合
export MAGI_PERSONAS__melchior__llm__model="claude-3-opus-20240229"

# temperature を設定する場合
export MAGI_PERSONAS__casper__llm__temperature=0.7
```

### 廃止・変更された環境変数 (自動変換されます)

以下の古いキーは自動的に新しいキーにマッピングされますが、警告が出る場合があります。

*   `enable_streaming_output` -> `streaming_enabled`
*   `streaming_emit_timeout_seconds` -> `streaming_emit_timeout`
*   `enable_guardrails` -> `guardrails_enabled`
*   `guardrails_timeout_seconds` -> `guardrails_timeout`
*   `guardrails_on_timeout_behavior` -> `guardrails_on_timeout`
*   `guardrails_on_error_policy` -> `guardrails_on_error`

## 設定ファイル (`magi.yaml`) の移行

### 推奨される新しい形式 (フラット)

```yaml
# magi.yaml
api_key: "sk-ant-..."
model: "claude-3-opus-20240229"

# ストリーミング設定
streaming_enabled: true
streaming_queue_size: 200
streaming_overflow_policy: "backpressure"

# 並行処理設定
llm_concurrency_limit: 10

# 本番設定
production_mode: false
```

### 従来の形式 (互換サポートあり)

以下のようなネスト構造も引き続き読み込めますが、内部で上記フラット構造に変換されます。

```yaml
# 旧形式 (非推奨)
streaming:
  enabled: true
  emitter:
    queue_size: 200
```

## トラブルシューティング

### バリデーションエラーへの対応

起動時に `MagiException` が発生し、詳細に `validation error` が含まれる場合、設定値が不正です。

**例1: APIキー不足**
```text
MagiException: APIキーが設定されていません。環境変数 MAGI_API_KEY または設定ファイルで設定してください。
```
-> `MAGI_API_KEY` 環境変数をセットするか、`magi.yaml` に `api_key` を記述してください。

**例2: 型不正**
```text
validation error; input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='five', input_type=str]
```
-> `timeout` や `concurrency_limit` などの数値項目に文字列を指定していないか確認してください。

**例3: 本番モードでの公開鍵未指定**
```text
production_mode=True では plugin_public_key_path の明示指定が必須です
```
-> `production_mode: true` (または `MAGI_PRODUCTION_MODE=true`) を設定している場合、必ず `plugin_public_key_path` も指定する必要があります。これはセキュリティ上の制約です。

### 診断コマンド

現在の設定値（環境変数などが適用された最終結果）を確認するには、以下のコマンドを使用できます（機微情報はマスクされます）。

```bash
python -m magi.cli --config-check
# または、実装予定の CLI コマンド
# magi config check
```
