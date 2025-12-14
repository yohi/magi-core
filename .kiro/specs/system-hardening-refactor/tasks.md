# 実装計画: System Hardening Refactor

## 1. 統合設定モデルの実装 (Pydantic V2)

 - [x] 1.1 (P) MagiSettings の Pydantic V2 モデル化
  - 既存の Config クラスを `pydantic.BaseSettings` に移行し、全設定項目を型付きフィールドとして定義
  - `model_config` で `env_prefix="MAGI_"`, `env_file=".env"`, `extra="forbid"` を設定し、環境変数ロードと未知キー検出を有効化
  - API 設定 (`api_key`, `model`, `timeout`, `retry_count`) および合議設定 (`debate_rounds`, `voting_threshold`, `quorum_threshold`, `token_budget`) を Field でバリデーション
  - 並行処理設定 (`llm_concurrency_limit`, `plugin_concurrency_limit`, `plugin_load_timeout`)、ストリーミング設定 (`streaming_enabled`, `streaming_queue_size`, `streaming_overflow_policy`, `streaming_emit_timeout`) を追加
  - Guardrails 設定 (`guardrails_enabled`, `guardrails_timeout`, `guardrails_on_timeout`, `guardrails_on_error`)、プラグイン権限設定 (`plugin_prompt_override_allowed`, `plugin_trusted_signatures`) を追加
  - 本番運用モード (`production_mode`, `plugin_public_key_path`) と出力設定 (`output_format`) を定義
  - `field_validator` で `production_mode=True` 時に `plugin_public_key_path` 必須を検証するクロスフィールドバリデーションを実装
  - `dump_masked()` メソッドで API キーをマスクした設定を返却 (診断出力用)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2_

 - [x] 1.2 ConfigManager の MagiSettings 統合
  - `ConfigManager.load()` を既存の Config インスタンス化から `MagiSettings()` 呼び出しに置き換え
  - 環境変数、`magi.yaml` ファイル、コマンドライン引数からの設定ロードを Pydantic の優先順位ルールで統一
  - Pydantic バリデーションエラーを捕捉し、修正可能なエラーメッセージ (`MagiException`) に変換
  - 実効設定の診断出力 (`dump_masked()`) を CLI `--config-check` オプションで提供
  - 既存コードベース全体の `Config` 参照箇所を `MagiSettings` に更新 (`src/magi/` 配下全体)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.3_

  - [x] 1.3 (P) プラグイン定義の Pydantic モデル化
  - `PluginMetadataModel`, `BridgeConfigModel`, `PluginModel` を Pydantic BaseModel として定義
  - `name`, `version`, `description`, `signature`, `hash` を PluginMetadataModel に型付きで定義
  - `command`, `interface`, `timeout` を BridgeConfigModel に定義し、`timeout` は `gt=0` で検証
  - `agent_overrides` を `dict[str, str]` として定義し、デフォルトを空辞書に設定
  - 既存の手動バリデーション (`isinstance` の多用) を Pydantic 自動バリデーションに置き換え
  - _Requirements: 6.1, 6.2, 6.4_

## 2. プラグインロードの非同期化と隔離

 - [x] 2.1 (P) PluginLoader の非同期化基盤構築
  - `load_async()` と `load_all_async()` の非同期メソッドを追加
  - ファイル読み込み (`path.read_text`) を `asyncio.to_thread` でオフロード
  - YAML パース結果を Pydantic モデルで検証し、スキーマエラーを `PluginLoadError` として返却
  - プラグインロード開始/終了イベントを監査ログに記録 (`plugin.load.started`, `plugin.load.completed`)
  - _Requirements: 1.1, 1.5, 6.1, 6.3_

- [x] 2.2 (P) プラグイン署名検証の非同期化
  - `_verify_security()` 内の署名検証とハッシュ計算を `asyncio.to_thread` でオフロード
  - 公開鍵パス解決ロジックを維持しつつ、非同期実行に対応
  - 署名検証失敗時に監査ログ (`plugin.load.signature_failed`) を記録し、PluginLoadError を送出
  - _Requirements: 1.1, 1.2, 1.5_

- [x] 2.3 プラグインロードのタイムアウトと隔離
  - `load_async()` に個別タイムアウトを適用 (`asyncio.wait_for` 使用)
  - タイムアウト時は当該プラグインのみ無効化し、起動処理を継続
  - タイムアウト理由とプラグイン識別子を監査ログ (`plugin.load.timeout`) に記録
  - プラグインロード失敗時の影響を他プラグインや合議処理に波及させない隔離機構を実装
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2.4 複数プラグインの同時ロード数制限
  - `load_all_async()` で `asyncio.Semaphore` を用いた同時ロード数制限を実装
  - 上限値は `MagiSettings.plugin_concurrency_limit` (デフォルト 3) から取得
  - 上限超過時のロード要求を待機させ、待機開始/終了を監査ログに記録
  - 各プラグインのロード結果 (成功/失敗) を含む `PluginLoadResult` リストを返却
  - _Requirements: 1.4, 1.5_

## 3. 公開鍵パス解決の厳格化

- [ ] 3.1 (P) 本番運用モードでの公開鍵パス厳格化
  - `_resolve_public_key_path()` に本番運用モード (`production_mode`) フラグを追加
  - 本番モード有効時は、カレントディレクトリからの探索を無効化し、明示指定されたパスのみ使用
  - 本番モードで公開鍵パスが解決できない場合は、起動を拒否し、必要な設定項目を明示したエラーメッセージを返却
  - 公開鍵パス解決元 (設定/環境変数/既定パス) を監査ログに記録
  - _Requirements: 9.1, 9.2, 9.3_

## 4. プラグイン権限ガードの実装

- [ ] 4.1 (P) PluginPermissionGuard の基本実装
  - `check_override_permission()` メソッドで `agent_overrides` の権限チェックを実装
  - 許可範囲 (`OverrideScope.CONTEXT_ONLY` / `FULL_OVERRIDE`) を設定で制御
  - `plugin_prompt_override_allowed` が false の場合は CONTEXT_ONLY のみ許可
  - 許可外変更を検出した場合は拒否し、プラグイン識別子と拒否理由を監査ログに記録
  - `PermissionCheckResult` (許可/拒否、スコープ、フィルタ済み上書き) を返却
  - _Requirements: 8.1, 8.2_

- [ ] 4.2 (P) 信頼されたプラグインの権限管理
  - `plugin_trusted_signatures` 設定に基づく信頼判定を実装
  - 署名検証済みかつ信頼リストに含まれるプラグインのみ FULL_OVERRIDE 権限を付与
  - 信頼されていないプラグインは CONTEXT_ONLY に制限
  - プロンプト変更適用時に、変更種別と適用元 (プラグイン識別子) を監査ログに記録
  - _Requirements: 8.3, 8.4_

- [ ] 4.3 PluginLoader への PluginPermissionGuard 統合
  - `load_async()` 内で `PluginPermissionGuard.check_override_permission()` を呼び出し
  - 権限チェック結果に基づき、`agent_overrides` をフィルタリング
  - フィルタ済みプラグインを返却し、拒否された上書きはログに記録
  - _Requirements: 8.1, 8.2, 8.4_

## 5. LLM 同時実行制御の実装

- [ ] 5.1 (P) ConcurrencyController の実装
  - `asyncio.Semaphore` でプロセス全体の LLM 同時実行数を制御
  - 上限値は `MagiSettings.llm_concurrency_limit` (デフォルト 5) から取得
  - `acquire()` コンテキストマネージャで同時実行許可を取得・解放
  - タイムアウト時は `ConcurrencyLimitError` を送出
  - `get_metrics()` で現在の同時実行数、待機数、総取得数、タイムアウト数を返却
  - `note_rate_limit()` でレート制限発生を記録
  - _Requirements: 2.1, 2.2, 2.5_

- [ ] 5.2 LLMClient のレート制限対応強化
  - レート制限エラー (HTTP 429) 検出時に、即座に再試行せずバックオフを適用
  - `ConcurrencyController.note_rate_limit()` を呼び出し、レート制限発生を記録
  - 再試行抑制がログに記録され、システム全体のスループット制御に寄与
  - _Requirements: 2.3, 2.5_

- [ ] 5.3 (P) TokenBudgetManager の Protocol 定義と基本実装
  - `TokenBudgetManagerProtocol` を定義 (`check_budget()`, `consume()` メソッド)
  - トークン予算チェックと消費記録の基本実装を作成
  - `check_budget()` は推定トークン数が予算内であるかを返却 (True: 続行可能, False: 予算超過)
  - `consume()` は実際に消費されたトークン数を記録 (過剰消費時も例外を発生させず記録)
  - None 値は予算管理なし/無制限を意味し、常に True を返す実装を用意
  - _Requirements: 2.6_

- [ ] 5.4 ConsensusEngine への ConcurrencyController 統合
  - `ConsensusEngineFactory.create()` に `concurrency_controller` 引数を追加
  - LLM 呼び出し前に `async with controller.acquire()` で同時実行許可を取得
  - タイムアウト時は `ConcurrencyLimitError` を捕捉し、クオーラム未達処理へ分岐
  - 同時実行数、待機数のメトリクスをログに記録
  - _Requirements: 2.1, 2.2, 2.4, 2.5_

- [ ] 5.5 ConsensusEngineFactory への TokenBudgetManager 統合
  - `ConsensusEngineFactory.create()` に `token_budget_manager` 引数を追加 (Optional, デフォルト None)
  - ConsensusEngine が TokenBudgetManager を受け取り、LLM 呼び出し前に `check_budget()` で予算チェックを実行
  - 予算超過時は LLM 呼び出しをスキップし、クオーラム未達処理へ分岐
  - LLM レスポンス受信後に `consume()` で実際のトークン数を記録
  - _Requirements: 2.6_

## 6. ストリーミング出力のバックプレッシャ対応

- [ ] 6.1 (P) StreamingEmitter のバックプレッシャ/ドロップ方針設定化
  - `streaming_overflow_policy` (`drop` / `backpressure`) を `MagiSettings` から取得
  - `emit()` メソッドで `priority` 引数 (`normal` / `critical`) を追加
  - `priority="critical"` のイベントは決してドロップせず、必要に応じて非クリティカルイベントを削除して挿入
  - キュー満杯時の動作: `drop` モードでは最古の非クリティカルイベントをドロップ、`backpressure` モードでは `streaming_emit_timeout` 秒間待機
  - _Requirements: 3.1, 3.2, 3.4_

- [ ] 6.2 (P) ストリーミング欠落のログ記録
  - ドロップ発生時に欠落件数、欠落区間 (可能な範囲)、発生理由をログに記録
  - バックプレッシャモードでタイムアウト時は `StreamingTimeoutError` を送出
  - 非クリティカルイベントのタイムアウト時のみ例外を送出し、クリティカルイベントは例外なく出力
  - ドロップおよびタイムアウトをイベント (`streaming.drop`, `streaming.timeout`) として記録
  - _Requirements: 3.2, 3.3_

- [ ] 6.3 (P) ストリーミングメトリクスの記録
  - TTFB (Time To First Byte)、送出遅延、欠落率を計測
  - `get_state()` で `StreamingState` (キューサイズ、現在長、送出数、ドロップ数、TTFB、経過時間、最終ドロップ理由) を返却
  - メトリクスを定期的にログに記録し、観測可能性を確保
  - _Requirements: 3.5_

- [ ] 6.4 ConsensusEngine への StreamingEmitter 統合
  - `ConsensusEngineFactory.create()` に `streaming_emitter` 引数を追加
  - 合議フローの各フェーズ (Thinking, Debate, Voting) で `emit()` を呼び出し
  - 最終結果 (合議の結論および要約) は `priority="critical"` で送出し、欠落を防止
  - ストリーミングが無効な場合はデフォルトの NoOpEmitter を使用
  - _Requirements: 3.1, 3.4_

## 7. 依存性注入 (DI) によるテスト容易性向上

- [ ] 7.1 ConsensusEngine の DI 対応
  - `ConsensusEngineFactory.create()` で主要依存 (PersonaManager, ContextManager, LLMClient, StreamingEmitter, GuardrailsAdapter, TokenBudgetManager) を外部注入可能に変更
  - 各依存は Optional 引数とし、None の場合はデフォルト実装を使用
  - デフォルト実装はファクトリ関数または既存クラスのインスタンス化で提供
  - Protocol を用いた依存の型定義 (`PersonaManagerProtocol`, `ContextManagerProtocol`, `TokenBudgetManagerProtocol`) を追加
  - 本番環境では `concurrency_controller` を明示的に注入することをドキュメント化
  - _Requirements: 4.1, 4.2_

- [ ] 7.2 (P) 単体テスト用モック依存の作成
  - `PersonaManagerProtocol`, `ContextManagerProtocol`, `LLMClient`, `StreamingEmitter`, `GuardrailsAdapter`, `TokenBudgetManagerProtocol` のモック実装を作成
  - モックはネットワークアクセスを不要とし、合議フローの分岐 (成功/失敗/クオーラム未達/リトライ枯渇) を再現可能に
  - モック依存を注入した ConsensusEngine の単体テストを実装
  - _Requirements: 4.3, 4.4_

## 8. Guardrails の拡張性と fail ポリシー明確化

- [ ] 8.1 (P) GuardrailsAdapter のマルチプロバイダ対応
  - `GuardrailsProviderProtocol` を定義 (`name`, `enabled`, `evaluate()` メソッド)
  - `register_provider()` メソッドでカスタムプロバイダを追加可能に
  - 複数プロバイダを順次評価し、判定結果 (許可/拒否/要サニタイズ) と理由コードを返却
  - 評価結果を監査ログ (`guardrails.evaluation`) に記録
  - _Requirements: 7.1, 7.2_

- [ ] 8.2 (P) Guardrails のタイムアウトと fail ポリシー適用
  - `guardrails_timeout` 設定に基づき、各プロバイダの評価にタイムアウトを適用
  - タイムアウトまたは例外発生時は、`guardrails_on_timeout` / `guardrails_on_error` ポリシー (`fail-open` / `fail-closed`) に従って処理
  - `fail-open`: 評価失敗時は許可扱い、`fail-closed`: 拒否扱い
  - 適用ポリシーを監査ログ (`guardrails.policy_applied`) に記録
  - _Requirements: 7.3_

- [ ] 8.3 (P) Guardrails による入力遮断と安全化
  - 拒否または要サニタイズ判定時は、LLM への送信前に要求を遮断または安全化
  - ユーザーに修正可能なエラーメッセージを返却 (遮断理由を含む)
  - サニタイズ処理をプロバイダから受け取り、適用後にログ記録
  - _Requirements: 7.4_

- [ ] 8.4 ConsensusEngine への GuardrailsAdapter 統合
  - `ConsensusEngineFactory.create()` に `guardrails_adapter` 引数を追加
  - 合議フロー開始前に入力を `guardrails_adapter.evaluate()` で評価
  - 拒否時は合議を中断し、ユーザーにエラーを返却
  - Guardrails が無効な場合はスキップ
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

## 9. 統合テストと検証

- [ ] 9.1 (P) MagiSettings の単体テスト
  - Pydantic バリデーション成功/失敗ケースのテスト
  - クロスフィールドバリデーション (`production_mode` と `plugin_public_key_path`) のテスト
  - 環境変数、設定ファイル、デフォルト値の優先順位テスト
  - `dump_masked()` によるマスク処理のテスト
  - 未知キー検出 (`extra="forbid"`) のテスト
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2_

- [ ] 9.2 (P) PluginLoader の非同期ロード単体テスト
  - `load_async()` の正常系 (ロード成功) テスト
  - タイムアウト時の動作テスト (当該プラグインのみ無効化)
  - スキーマエラー時のテスト (Pydantic バリデーション失敗)
  - 署名検証失敗時のテスト
  - 監査ログ記録のテスト
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 6.1, 6.2, 6.3_

- [ ] 9.3 (P) ConcurrencyController の単体テスト
  - セマフォによる同時実行数制限のテスト
  - タイムアウト時の `ConcurrencyLimitError` 送出テスト
  - メトリクス記録 (`get_metrics()`) のテスト
  - レート制限記録 (`note_rate_limit()`) のテスト
  - _Requirements: 2.1, 2.2, 2.5_

- [ ] 9.4 (P) PluginPermissionGuard の単体テスト
  - `check_override_permission()` の権限チェックテスト (CONTEXT_ONLY / FULL_OVERRIDE)
  - 信頼されたプラグインの権限管理テスト
  - 許可外変更の拒否とログ記録テスト
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 9.5 (P) StreamingEmitter のバックプレッシャ単体テスト
  - `drop` モードでのドロップ動作テスト
  - `backpressure` モードでの待機とタイムアウトテスト
  - クリティカルイベントの欠落防止テスト
  - メトリクス記録 (`get_state()`) のテスト
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 9.6 (P) GuardrailsAdapter のマルチプロバイダ単体テスト
  - カスタムプロバイダ登録のテスト
  - タイムアウト時の fail-open/fail-closed ポリシー適用テスト
  - 判定結果の監査ログ記録テスト
  - 入力遮断と安全化のテスト
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 9.7 プラグインロードの統合テスト
  - 複数プラグインの同時ロード (`load_all_async()`) テスト
  - 同時ロード数制限の動作テスト
  - 失敗プラグインの隔離テスト (他プラグインへの影響がないこと)
  - _Requirements: 1.3, 1.4, 1.5_

- [ ] 9.8 合議フローの統合テスト (DI 注入あり)
  - モック依存を注入した ConsensusEngine の完全フロー実行テスト
  - 成功/失敗/クオーラム未達/リトライ枯渇の各分岐テスト
  - ConcurrencyController, StreamingEmitter, GuardrailsAdapter, TokenBudgetManager の統合動作テスト
  - _Requirements: 4.1, 4.3, 4.4, 2.1, 2.4, 3.1, 7.1_

- [ ] 9.9 (P) 本番運用モードの統合テスト
  - `production_mode=True` 時の公開鍵パス厳格化テスト
  - 公開鍵パス解決不可時の起動拒否テスト
  - 監査ログ記録のテスト
  - _Requirements: 9.1, 9.2, 9.3_

- [ ] 9.10 (P) Property テストの追加
  - MagiSettings の任意の有効な設定値でのバリデーション成功を検証
  - PluginLoader の任意のタイムアウト値での動作を検証
  - ConcurrencyController の任意の同時実行数での動作を検証

## 10. ドキュメントと移行ガイド

- [ ] 10.1 (P) 設定移行ガイドの作成
  - 既存の環境変数から新しい `MagiSettings` フィールドへのマッピングを文書化
  - `magi.yaml` の設定例を提供
  - Pydantic バリデーションエラーのトラブルシューティングガイドを作成

- [ ] 10.2 (P) プラグイン開発者向けガイドの更新
  - `agent_overrides` の権限制御を説明
  - 信頼されたプラグインとして登録する方法を文書化
  - プラグイン署名検証の手順を更新

- [ ] 10.3 (P) 本番運用ガイドの作成
  - `production_mode` の有効化方法と影響を文書化
  - 公開鍵パスの設定と管理方法を説明
  - 監査ログの活用方法を提供

## 11. 最終統合とリグレッションテスト

- [ ] 11.1 全コンポーネントの統合
  - MagiSettings, PluginLoader, ConcurrencyController, StreamingEmitter, GuardrailsAdapter, PluginPermissionGuard を MagiCLI および ConsensusEngine に統合
  - CLI の起動時に全設定をロードし、バリデーションエラーを適切にハンドリング
  - 合議フローの全フェーズで新機能が正しく動作することを確認
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3_

- [ ] 11.2 リグレッションテストの実施
  - 既存の全単体テスト、property テスト、統合テストを実行
  - 既存機能の互換性を確認 (マルチプロバイダ対応、合議フロー、プラグイン拡張)
  - パフォーマンステスト (10 プラグインの同時ロードで 5 秒以内完了、LLM 同時実行数 5 でのスループット測定)
  - 全テストが pass することを確認

- [ ] 11.3 エラーハンドリングとログ記録の検証
  - 各エラーカテゴリ (設定バリデーション失敗、プラグインタイムアウト、署名検証失敗、同時実行タイムアウト、Guardrails タイムアウト、LLM レート制限) の動作を確認
  - 監査ログが適切に記録されることを確認
  - ユーザー向けエラーメッセージが修正可能な情報を含むことを確認
