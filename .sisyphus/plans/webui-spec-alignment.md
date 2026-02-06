# WebUI Spec Alignment Plan

## 概要
`magi-core` リポジトリ内の WebUI 実装を、全社標準仕様である `webui-spec.md` に完全準拠させるための改修計画。
インフラ構成の修正、API/WS仕様の不整合解消、および未実装のオプション機能の実装を行う。

## 方針
- **仕様準拠**: 実装を `webui-spec.md` に合わせる（仕様書変更は行わない）。
- **TDD (Test-Driven Development)**: 修正・実装の前に必ず再現テスト/失敗するテストを作成する。
- **インフラ**: 本番相当構成では Backend を外部公開せず、Frontend (Nginx) 経由のアクセスのみとする。
- **テスト基盤**: 既存の `unittest` + `FastAPI TestClient` を使用。

---

## Phase 1: インフラ構成とAPIインターフェースの整合 (P0/P1)

起動可能性の確保と、外部インターフェース（REST/WS）の仕様準拠を最優先で行う。

### 1.1 Docker Compose ポート構成の修正 (P0) [完了]
- **対象**: `compose.yaml`
- **内容**: 
  - `magi-backend` の `ports` 定義を削除（内部ネットワークのみ）。
  - `magi-frontend` の `ports` を `3000:80` に固定（ホスト側3000番）。
- **検証**: `docker compose up` 起動後、`curl localhost:3000/api/health` 成功、`curl localhost:8000` 失敗を確認。

### 1.2 REST API レスポンスの仕様準拠 (P1) [完了]
- **対象**: `src/magi/webui_backend/app.py`
- **タスク**:
  - `POST /api/sessions`: レスポンス `status` を `"created"` -> `"QUEUED"` (または `"RUNNING"`) に変更。
  - `POST /api/sessions/{id}/cancel`: レスポンス `status` を `"cancelled"` -> `"CANCELLED"` (または `"CANCELLING"`) に変更。
  - `prompt` の長さバリデーション実装（1〜8000文字）。範囲外なら 400 Bad Request。
- **テスト**: `tests/unit/test_webui_rest.py` を新規作成し、ステータス値とバリデーションを検証。

### 1.3 WebSocket Error イベントの仕様準拠 (P1) [完了]
- **対象**: `src/magi/webui_backend/session_manager.py`, `adapter.py`
- **タスク**:
  - `type: "error"` イベント送信時に、必ず `code` フィールドを含める。
  - 定義済みコード: `MAGI_CORE_ERROR`, `TIMEOUT`, `CANCELLED`, `INTERNAL`
- **テスト**: `tests/unit/test_webui_ws.py` を拡張し、エラーイベントのスキーマ検証を追加。

---

## Phase 2: 設定・オプションの実効化 (P2)

定義されているが機能していない設定項目を実装に反映させる。

### 2.1 実行タイムアウトの実装 [完了]
- **対象**: `src/magi/webui_backend/session_manager.py`
- **タスク**:
  - `SessionOptions.timeout_sec` (デフォルト120秒) を `adapter.run()` の実行タイムアウトとして適用。
  - `asyncio.wait_for` 等でラップし、タイムアウト時は `type: "error", code: "TIMEOUT"` を送信し、Phaseを `ERROR` に。
- **テスト**: `MockAdapter` を遅延させ、指定時間でタイムアウトすることを確認。

### 2.2 モデル指定の反映 [完了]
- **対象**: `src/magi/webui_backend/adapter.py`
- **タスク**:
  - `ConsensusEngineMagiAdapter` で、`SessionOptions.model` が指定されている場合、`ConsensusEngine` 生成時の `config.model` を上書きするロジックを追加。
- **テスト**: `ConsensusEngine` が指定されたモデルで初期化されているかモックで検証。

### 2.3 環境変数の適用 (MAX_CONCURRENCY, TTL) [完了]
- **対象**: `src/magi/webui_backend/app.py`
- **タスク**:
  - `os.environ` または `ConfigManager` から `MAX_CONCURRENCY`, `SESSION_TTL_SEC` を読み込み、`SessionManager` 初期化時に渡す。
  - `CORS_ORIGINS` が設定されている場合のみ `CORSMiddleware` を追加（開発環境用）。
- **テスト**: 環境変数を設定して `app` を起動し、設定値が反映されているか確認。

---

## Phase 3: 運用・品質向上 (P3)

### 3.1 定期 TTL クリーンアップ [完了]
- **対象**: `src/magi/webui_backend/session_manager.py`
- **タスク**:
  - 現状の「作成時のみクリーンアップ」に加え、バックグラウンドタスク（`asyncio.create_task`）で定期的に（例: 60秒ごと）期限切れセッションを削除する仕組みを追加。
  - `app.py` の `startup` イベント等で開始、`shutdown` で停止。

### 3.2 Frontend Cancel ボタン & ステータス表示改善 [完了]
- **対象**: `frontend/src/App.tsx`
- **タスク**:
  - 実行中 (`isRunning`) に「CANCEL」ボタンを表示し、API `/api/sessions/{id}/cancel` を呼ぶ。
  - WS切断時、ログだけでなくステータスバー等で視覚的に切断状態を示す（MVP範囲内での改善）。

---

## テスト計画

### 自動テスト (TDD)
各タスクの実装前に、期待する挙動（仕様）を記述したテストケースを作成する。

| テストファイル | 役割 | 新規/既存 |
|---|---|---|
| `tests/unit/test_webui_rest.py` | APIステータスコード、レスポンスボディ、バリデーション | **新規** |
| `tests/unit/test_webui_ws.py` | WSイベントスキーマ (error.code等)、接続制御 | 既存(拡張) |
| `tests/unit/test_session_manager.py` | タイムアウト、TTL、同時実行数、キャンセルロジック | 既存(拡張) |
| `tests/unit/test_webui_adapter.py` | モデル設定反映、エンジン呼び出し | 既存(拡張) |

### 手動確認手順
1. `docker compose up --build`
2. `http://localhost:3000` にアクセス
3. Prompt入力 -> Start -> 完了まで動作確認
4. 実行中に Cancel ボタン -> キャンセル確認
5. タイムアウト値(短め)で実行 -> タイムアウトエラー確認
