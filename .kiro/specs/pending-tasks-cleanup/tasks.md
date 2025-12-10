# Implementation Plan

- [x] 1. `magi ask` 合議フローの統合と結果提示
  - CLI から ConsensusEngine を起動し、Thinking/Debate/Voting 結果またはフェイルセーフ応答を表示する経路を実装する。
  - 合議開始・終了・所要時間・採用モデルを監査ログへ記録し、ログ出力先未設定時は警告を STDERR へ出力する。
  - フェイルセーフ発生時に段階と理由を CLI へ要約表示し、再実行可能な状態を維持する。
  - _Requirements: 1_
  - テスト方法:
    - Unit: `tests/unit/test_cli.py::TestMagiCLI` で成功・フェイルセーフ・ログ警告の出力を検証する。
    - Integration: `tests/integration/test_end_to_end.py::TestEndToEnd` で `magi ask` が Thinking/Debate/Voting を通過し、フェイルセーフ時も終了コードとstderrが整合することを確認する。
    - Property: 入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms で合議結果/フェイルセーフが安定すること。

- [x] 2. Voting ペイロードの jsonschema 検証とリトライ制御
  - Voting ペイロードを jsonschema で検証する処理を実装し、必須項目・型・値域を網羅的にチェックする。
  - 検証失敗時に最大回数まで再生成をリトライし、各失敗理由と retry カウントを監査ログへ残す。
  - リトライ上限超過時にフェイルセーフ応答を生成し、ConsensusEngine/CLI に伝播させる。
  - _Requirements: 4_
  - テスト方法:
    - Unit: `tests/unit/test_consensus_schema_retry.py` と `tests/unit/test_schema_validator.py` で成功・リトライ・上限超過・フェイルセーフを網羅する。
    - Integration: `tests/integration/test_end_to_end.py` で Voting スキーマ検証が CLI フローに組み込まれることを確認する。
    - Property: Voting ペイロードの入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms で検証/リトライが安定すること。

- [x] 3. トークン圧縮の要約ステップと削減ログ精度向上
  - 入力コンテキストが閾値超過時に重要度選択後の要約ステップを追加し、再計算後の出力を返す。
  - 削減ログに size_before/after、retain_ratio、summary_applied、strategy を記録し、監査ログへ出力する。
  - `LOG_CONTEXT_REDUCTION_KEY` 有効時に削減前後サイズと要約概要を含む監査ログを出力する。
  - _Requirements: 5_
  - テスト方法:
    - Unit: `tests/unit/test_token_budget.py` で要約有無・保持率・戦略・トークン閾値を確認する。
    - Integration: `tests/integration/test_end_to_end.py` で合議フロー中に削減ログが残ることを検証する。
    - Property: 長大コンテキストの入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms で圧縮とログが安定すること。

- [x] 4. SecurityFilter の禁止パターン監査ログ強化
  - 禁止パターン検知・除去時に `removed_patterns` は空配列禁止とし、未検知時は `[{ "pattern_id": "none", "count": 0 }]` と `removed_patterns_present=false` を必ず記録する。検知時は `{ "pattern_id": "<id>", "count": <n> }` 群と `removed_patterns_present=true` を記録する。
  - マスク済み入力断片とパターン ID を監査ログへ出力し、監査ログ無効時はプロセス起動ごと 1 回だけ STDERR へ警告しつつ、`removed_patterns` は上記フォールバックを必ず書き出す。
  - マスク処理は機微断片を ASCII アスタリスク 8 文字固定トークン「`********`」で置換し、最大 32 UTF-8 コードポイントにパディング/切り詰めする。`original_length` メタデータで元長を併記する。
  - フォーマット統一として `mask_hashing` ブール設定が true の場合のみ `masked:sha256:<first8hex>`（SHA-256 の先頭 8 文字、小文字 hex）をログに用い、false の場合は固定トークンを用いる。
  - _Requirements: 3_
  - テスト方法:
    - Unit: `tests/unit/test_security_filter.py` で禁止パターン検知、フォールバック、マスク形式、監査ログ警告を検証する。
    - Integration: `tests/integration/test_end_to_end.py` で CLI フローにおけるサニタイズと監査ログ出力を確認する。
    - Property: 入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms でブロック/非ブロック判定と `removed_patterns` 記録が安定すること。

- [x] 5. `magi spec --review` での 3 賢者レビュー統合表示
  - cc-sdd プラグイン契約を明文化し、役割を「賢者別レビュー JSON を返す」こととする。出力スキーマは `reviewer_id`, `status`, `score`, `message`, `timestamp` を必須フィールドとする。
  - 部分失敗を許容し、成功したレビューは即時表示、失敗したレビューは集約してフラグ表示しつつ全体表示を中断しない。
  - リトライは最大試行回数・待機方式（固定または指数バックオフ）・試行ごとのタイムアウトを設定し、デフォルト値（例: max_attempts=3, fixed_wait=1s, per_attempt_timeout=5s, global_timeout=15s）を明記する。無限待ちを避けるためグローバル/リクエストタイムアウトを必須とする。
  - CLI ステータス表示は行ごとにレビューアアイコン+ステータス+スコア+メッセージを並べ、進捗率と全体インジケータ（例: `[✔︎] sage-a 0.92 "looks good"`, `[✖] sage-b retrying...`, `[…] overall 2/3 complete`）のフォーマット例を示す。
  - _Requirements: 2_
  - テスト方法:
    - Unit: `tests/unit/test_sdd_plugin.py` と `tests/unit/test_plugin_loader.py` でプラグイン契約と部分失敗時の集約表示を確認する。
    - Integration: `tests/integration/test_end_to_end.py` で `magi spec --review` のステータス表示とリトライ制御を検証する。
    - Property: レビュー応答の入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms で部分失敗許容と全体進捗表示が安定すること。

- [x] 6. Spec メタデータと tasks の整合性回復
  - tasks.md を機械可読に解析する手段を明記する（例: Markdown AST でチェックボックスを抽出し、正規化したタスク ID/タイトル/状態を得る正規表現は使用禁止）。
  - チェックボックス状態から `remaining_tasks` を算出するロジック（未完了数、完了率、完了日時の最終値）を定義する。
  - 原子的更新は一時ファイルへの書き込み・`fsync`・リネームで行い、必要ならファイルロック（advisory）を併用する手順を示す。
  - ロールバックは更新前の spec.json バックアップと一時ファイルを対象にし、失敗時はバックアップへ戻して再試行手順を記録する。
  - タイムスタンプ/ソース記録は spec.json 内に JSON メタデータ（例: `{"synced_from":"tasks.md","synced_at":"<ISO8601Z>","generator_version":"<cli-ver>"}`）として保持し、tasks.md とは分離することで循環依存を避ける。
  - _Requirements: 6_
  - テスト方法:
    - Unit: `tests/unit/test_spec_metadata_sync.py` と `tests/unit/test_plugin_loader_property.py` でチェックボックス解析と remaining_tasks 同期ロジックを検証する。
    - Integration: `tests/integration/test_end_to_end.py` でタスク状態とメタデータが矛盾しないことを確認する。
    - Property: タスク記述の入力サイズ・型・境界値・特殊文字・JSON 深度をランダム生成し、許容失敗率 <1%・P95 レイテンシ <500ms で解析・同期が安定すること。

- [x] 7. テスト強化と回帰防止
  - タスク 1–6 の受け入れ基準として統合し、各タスク項目に「テスト方法」サブセクションを追加して Unit/Integration/Property の観点を紐づける。独立タスク扱いは廃止する。
  - Property テストでは入力サイズ・型・境界値・ランダムケース（最大長、null/undefined、特殊文字、JSON 深度など）を明示し、「安定」は許容失敗率 <1%・P95 レイテンシ <500ms と定義する。
  - カバレッジ目標: ステートメント 80%、ブランチ 70%。CI 有効化は別タスクで管理し、`.github/workflows/tests.yml` に `unit`/`integration` 必須ジョブ・必要環境変数・`artifacts/coverage/` 保存先を列挙する。
  - _Requirements: 1, 2, 3, 4, 5, 6_
