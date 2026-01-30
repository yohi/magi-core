### 設計書・仕様書・作業手順書

#### (1) 概要

* 背景/目的:

  * `magi-core` を実行し、合議（MELCHIOR/BALTHASAR/CASPER）の進捗・ログ・投票・最終判定を **MAGI風UI**でリアルタイム表示する。
* 成功条件（Done定義）:

  * ブラウザからプロンプト投入→実行開始→3ユニット状態が更新→最終判定が表示される。
  * WS切断/再接続、キャンセル、失敗（magi-coreエラー）がUI上で判別できる。
  * Docker Compose で `up` するだけで起動できる（開発/本番分離）。
* スコープ（含む/含まない）:

  * 含む: UI表示、WSストリーム、ジョブ管理、Nginx同一オリジン集約、Secrets注入、最小監視（health）。
  * 含まない（MVP）: ユーザ認証、永続履歴、マルチテナント、詳細監査基盤、CRT歪み等の重い演出。
* 前提/制約（未確定を明示）:

  * `magi-core` の呼び出し方式（Python API / CLI）は **未確定**。本仕様は「Adapterで吸収」する。
  * LLM/外部APIキー等のSecretsが必要な場合はバックエンドのみ保持（フロント露出禁止）。
* 用語集:

  * Session: 1回の実行単位（prompt投入から完了まで）
  * Phase: THINKING / DEBATE / VOTING / RESOLVED
  * Unit: MELCHIOR-1 / BALTHASAR-2 / CASPER-3

---

#### (2) 要件定義

* 利用者/ステークホルダー:

  * 開発者（デモ/検証用）
  * 運用者（障害切り分け）
* ユースケース一覧:

  1. Promptを入力して実行開始
  2. 進捗と各Unitの状態を見る（ログ/スコア/投票）
  3. 実行をキャンセル
  4. 失敗時に原因を確認（magi-core/ネットワーク）
* 機能要件:

  * セッション生成（REST）
  * セッションイベント購読（WebSocket）
  * キャンセル（REST or WS）
  * UI: 3パネル（台形/六角形表示）、中心ノード、進捗バー、全体ステータス、ログビュー
* 非機能要件:

  * 性能:

    * UI更新 10Hz 程度（過剰更新禁止、バックプレッシャ考慮）
    * 同時セッション: 10（MVP目標、設定で変更可）
  * 可用性:

    * WS切断時はジョブ停止または継続を選択可能（MVPは停止推奨）
  * セキュリティ:

    * 同一オリジン構成を基本（Nginx集約）、CORSは開発時のみ限定許可
    * Secretsはバックエンド環境変数/Secretsで管理、ログに出さない
  * 運用/保守:

    * healthcheck、ログ（JSON推奨）、セッションTTL（メモリリーク防止）
  * 互換性/移行:

    * schema_version によりWSイベント互換性を管理
* 例外/エラーハンドリング方針:

  * magi-core失敗: `type=error` をWS送信し `phase=ERROR` へ遷移
  * タイムアウト: `phase=ERROR`、原因 `TIMEOUT`
  * キャンセル: `phase=CANCELLED`、以後イベント送信停止

---

#### (3) 外部仕様

##### 3.1 API（REST）

* Base Path: `/api`

1. **POST /api/sessions**

* 用途: セッション作成・実行開始
* Request (JSON):

  * `prompt` (string, required)
  * `options` (object, optional)

    * `model` (string, optional) ※magi-coreに渡せる場合
    * `max_rounds` (number, optional)
    * `timeout_sec` (number, optional, default 120)
* Response (201):

  * `session_id` (string, UUID)
  * `ws_url` (string, e.g. `/ws/sessions/{session_id}`)
  * `status` = `QUEUED|RUNNING`
* Validation:

  * prompt 1..8000 chars（仮定、未確定）

2. **POST /api/sessions/{session_id}/cancel**

* 用途: キャンセル要求
* Response:

  * `status` = `CANCELLING|CANCELLED`

3. **GET /api/health**

* 用途: ヘルスチェック
* Response:

  * `status` = `ok`

##### 3.2 WebSocket

* Endpoint: `/ws/sessions/{session_id}`
* 送信方向: server → client（MVP）
* Ping/Pong: 30秒（推奨）

**共通フィールド**

* `schema_version`: `"1.0"`
* `session_id`
* `ts`: ISO8601
* `type`: `"phase" | "unit" | "log" | "progress" | "final" | "error"`
* `phase`: `"QUEUED" | "THINKING" | "DEBATE" | "VOTING" | "RESOLVED" | "CANCELLED" | "ERROR"`

**イベント定義**

1. phase

* `type="phase"`, `phase` 更新

2. unit

* `type="unit"`
* `unit`: `"MELCHIOR-1" | "BALTHASAR-2" | "CASPER-3"`
* `state`: `"IDLE|THINKING|DEBATING|VOTING|VOTED"`
* `score`: number (0..1, optional)
* `message`: string (短文、UI中央表示に使用)

3. log

* `type="log"`
* `unit` (optional)
* `lines`: string[]（追加分のみ）
* `level`: `"DEBUG|INFO|WARN|ERROR"`

4. progress

* `type="progress"`
* `pct`: number (0..100)

5. final

* `type="final"`
* `decision`: `"APPROVE|DENY|CONDITIONAL"`（名称はmagi-coreに合わせて調整、現時点は仮定）
* `votes`:

  * unitごとの `vote`: `"YES|NO|ABSTAIN"`（仮定）
  * `reason`: string（短文）
* `summary`: string（任意）

6. error

* `type="error"`
* `code`: `"MAGI_CORE_ERROR|TIMEOUT|CANCELLED|INTERNAL"`
* `message`: string

---

#### (4) 内部設計

##### 4.1 アーキテクチャ概要

* `frontend (React build) + nginx`:

  * 静的配信
  * `/api/*` を `backend:8000` にプロキシ
  * `/ws/*` を `backend:8000` にWebSocketプロキシ
* `backend (FastAPI)`:

  * REST/WS終端
  * SessionManager（メモリ管理、同時数制限、TTL）
  * MagiAdapter（magi-core 呼び出し抽象化）
* `magi-core`:

  * Adapter経由で実行（方式未確定）

##### 4.2 コンポーネント責務

* SessionManager

  * `create_session(prompt, options)` → session_id
  * `run_session(session_id)` → asyncio task
  * `cancel_session(session_id)`
  * session状態保持: phase, progress, unit_states, ring_logs
* MagiAdapter（差し替え点）

  * `async run(prompt, options) -> async iterator[Event]`
  * 実装候補:

    * AdapterA: Python API直呼び（推奨）
    * AdapterB: CLIラップ（MVPで許容）
* EventBroadcaster

  * WS接続に対しイベント配信（バックプレッシャ時はドロップ/間引き）
  * schema_version付与

##### 4.3 状態遷移（セッション）

* QUEUED → THINKING → DEBATE → VOTING → RESOLVED
* 途中で CANCELLED / ERROR へ遷移可
* WS切断時（MVP推奨）:

  * `disconnect -> cancel_session`（コスト暴走防止）

##### 4.4 ロギング/トレーシング方針

* backend:

  * 構造化ログ（session_id, phase, unit, elapsed_ms）
  * Secretsマスキング（prompt全文/キーは出力禁止）
* frontend:

  * WS接続状態、最新イベントtype/tsをconsoleに残す（開発時のみ）

##### 4.5 設定/環境変数

* backend:

  * `MAGI_API_KEY`（仮。実際のmagi-core要件に合わせて確定）
  * `MAX_CONCURRENCY`（default 10）
  * `SESSION_TTL_SEC`（default 600）
  * `CORS_ORIGINS`（devのみ）
* frontend:

  * `VITE_API_BASE`（default "" 同一オリジン）
  * `VITE_WS_BASE`（default "" 同一オリジン）

---

#### (5) 運用設計

* 監視（最小）:

  * `/api/health` のHTTP 200
  * backendプロセス死活（compose healthcheck）
  * 同時実行数、失敗率、平均実行時間（ログから算出）
* 障害対応:

  * WS接続不可: Nginx proxy設定/ポート/Upgradeヘッダ確認
  * magi-core失敗: Adapterのstderr収集→errorイベント送信→ログ確認
* バックアップ/リストア:

  * MVPは状態をメモリ保持（永続なし）
* デプロイ/ロールバック:

  * イメージタグ固定、`docker compose pull && up -d`、障害時は前タグへ戻す
* 変更管理:

  * `schema_version` を上げる場合はフロント互換期間を設ける

---

#### (6) テスト設計

* テスト方針:

  * 単体: SessionManager（状態遷移、TTL、キャンセル）
  * 結合: WSイベント順序、バックプレッシャ、切断時停止
  * E2E: ブラウザから prompt→完了表示、キャンセル動作
* 重要観点:

  * 異常系（magi-core例外、タイムアウト、WS再接続）
  * 同時実行数制限が効くこと
* 受入条件:

  * 最終判定がUI上で一意に表示され、各Unitの投票状態が一致する
  * エラー時に `error.code` と `message` が表示される

---

#### (7) リスク・課題・未決事項

* リスク一覧:

  * magi-core呼び出しI/F差異 → Adapterで隔離（対策）
  * WS更新頻度過多 → サーバ側で間引き/クライアント側で描画制限
  * Secrets漏洩 → バックエンド限定注入＋ログ禁止
* 未決事項（最小）:

  1. magi-core 実行I/F（Python API / CLI）確定
  2. 最終判定語彙（APPROVE/DENY/CONDITIONAL 等）の正確な名称確定
  3. prompt/結果の保存要否（保存する場合の保持期間）

---

### 作業手順書（実装・構築・起動）

#### 1) リポジトリ準備

1. `magi-web-system/` を新規作成（別repo推奨）
2. backend/frontend の雛形配置（提示ディレクトリ構造に準拠）
3. `.env.example` を作成（Secretsは例のみ、値は空で配布）

#### 2) Nginx（同一オリジン）設定

* `frontend/nginx.conf` に以下を満たす設定を追加（要件）

  * `/` 静的配信
  * `/api/` → `http://magi-backend:8000`
  * `/ws/` → `http://magi-backend:8000` へ **Upgrade/Connection** ヘッダ付きプロキシ

#### 3) Backend 実装手順

1. SessionManager 実装（状態・TTL・同時数）
2. MagiAdapter をインターフェース化し、まずは MockAdapter で疎通
3. WS実装:

   * 接続時に session_id を購読
   * server→client でイベント送信（schema_version付与）
4. REST実装:

   * POST /api/sessions（作成→run開始）
   * POST /api/sessions/{id}/cancel
   * GET /api/health
5. Secrets対応:

   * `MAGI_API_KEY` 等は backend のみ参照、ログ出力禁止

#### 4) Frontend 実装手順（MAGI風UI）

1. レイアウト:

   * 上部ヘッダ（CODE/PRIORITY）
   * 中央ノード（MAGI）
   * 上中央=BALTHASAR、左下=CASPER、右下=MELCHIOR の台形パネル
2. 表示要素:

   * Unit名、スコア（%）、短文メッセージ（投票/状態）、ログ（リングバッファ）
   * 進捗バー（progress.pct）
3. 通信:

   * POSTで session生成→返却 ws_url に接続
   * イベントを reducer で状態に反映（乱数ログ生成は禁止）
4. 演出（MVP）:

   * スキャンライン（CSS疑似要素）
   * 点滅（phase/decisionでクラス切替）
   * 赤背景（DENY/VETO）などルール化

#### 5) Docker Compose（dev/prod）手順

* `docker-compose.yml`（prod）:

  * frontend: build→nginx配信
  * backend: uvicorn起動
  * healthcheck / restart / env_file を設定
* `docker-compose.dev.yml`（dev）:

  * frontend: Vite dev server（任意、またはローカルnode）
  * backend: volume mount + `--reload`

#### 6) 起動確認手順（受入チェック）

1. `docker compose up --build`
2. ブラウザで `http://localhost:3000/` を開く
3. Prompt入力→Start
4. 3ユニットが THINKING→…→RESOLVED と遷移し、最終判定が出る
5. キャンセルボタンで CANCELLED 表示になる
6. ネットワーク遮断/WS切断で ERROR または CANCELLED になる（仕様通り）

---

## 5. RECOMMENDED ACTION

* 次に行うべき作業（最大5件）

  1. magi-core の実行I/Fを確定し、MagiAdapter を実装（Mock→実体へ差替）
  2. WSイベントスキーマ（schema_version=1.0）を固定し、フロント reducer を先に確定
  3. Nginxで `/api` `/ws` を同一オリジン集約し、フロントのURL固定を排除
  4. Secrets注入（env/secrets）とログマスキングを必須化
  5. 最小E2E（prompt→完了、キャンセル、エラー）をPlaywright等で自動化

* 重要な確認事項（最小数）

  1. magi-core呼び出しは Python API か CLI ラップか
  2. 最終判定語彙と投票語彙の正式名称
  3. prompt/結果の保存要否（保存するなら保持期間とアクセス制御）
