# Implementation Plan

- [x] 1. LLM クライアントの疎結合化とジッター付きリトライ
- [x] 1.1 LLM クライアント注入とデフォルトファクトリ設定
  - ConsensusEngine が外部から LLM クライアント（またはファクトリ）を受け取り、未指定時は既定ファクトリで生成するようにする
  - 既存の Agent 生成フローを新しい注入経路に置き換え、後方互換を維持する
  - _Requirements: 品質/D.I改善_
- [x] 1.2 ジッター付き指数バックオフの導入
  - LLM リトライで Full Jitter を用いた待機時間計算を行い、レートリミット時の同時再試行を分散する（計算式: `wait_time = random(0, min(cap, base * 2^attempt))`、base は 500ms を目安とする）
  - レート制限: 待機上限 cap = 60s、最大リトライ回数 = 6 回。その他エラー: cap = 10s、最大リトライ回数 = 3 回。リトライ上限超過時は適切な例外とエラーコードを返す
  - _Requirements: 性能/リトライジッター_
- [x] 1.3 LLM リトライのテスト拡充
  - ジッター範囲内で待機が行われること、リトライ上限超過で例外となることをモックで検証する
  - レート制限時に待機が長めになるパスを含めてカバレッジを確保する
  - _Requirements: 性能/リトライジッター, 品質/テスト容易性_

- [x] 2. Voting Strategy 抽象化とフォールバック整理
- [x] 2.1 Hardened/Legacy の Strategy 分離
  - Voting 処理を Strategy インターフェースで分離し、Hardened と Legacy を独立実装にする
  - 既存のハードニング有効/無効フラグに基づき Strategy を選択するエントリポイントを整備する
  - _Requirements: 品質/Legacy混在解消_
- [x] 2.2 フェイルセーフ時のレガシー切替整理
  - クオーラム未達やスキーマ再試行枯渇時に、設定フラグに応じて Legacy Strategy へフォールバックする流れを明示し、結果メタ情報に反映する
  - パーシャル結果や除外ペルソナをメタに記録し、ログ/イベントにも残す
  - _Requirements: 品質/Legacy混在解消, 性能/フェイルセーフ動作_
- [x] 2.3 Voting Strategy のテスト追加
  - ハードニング有効/無効、フェイルセーフ時のフォールバック有無、クオーラム閾値に応じた決定結果をテストで検証する
  - スキーマ検証リトライ枯渇パスを含めて例外/エラー記録が行われることを確認する
  - _Requirements: 品質/Legacy混在解消, 性能/クオーラム_

- [x] 3. Debate ストリーミング/パイプライン化
- [x] 3.1 ストリーミング出力の配信
  - Debate 実行中にエージェント出力をチャンク単位で StreamingEmitter へ逐次転送し、CLI へ即時反映できるようにする
  - StreamingEmitter にキュー長と emit タイムアウト（例: 2s）を設け、溢れた場合は最新優先で古いチャンクを破棄し警告ログを出す
  - _Requirements: 性能/直列性改善_
- [x] 3.2 パイプライン制御とトークン予算連携
  - ストリーム途中で TokenBudgetManager による要約や中断が必要な場合、ストリームを停止し fail-safe を返す動線を定義する
  - バックプレッシャや中断時のイベント/ログを記録し、再現性を確保する
  - _Requirements: 性能/直列性改善, セキュリティ/多層防御_
- [x] 3.3 Debate ストリーミングのテスト
  - テスト用 StreamingEmitter でチャンク配信順序と中断時の挙動（破棄・タイムアウト）を検証する。キュー満杯時は LIFO（最新優先）で古いチャンクをドロップすることを明示し、ドロップ発生時に警告ログが出ることをアサートする
  - ドロップ後も残存チャンクの配信順序が維持されることを検証する
  - ストリーミング OFF 時に既存の一括出力（バルク）経路が変化しないことを確認する
  - _Requirements: 性能/直列性改善_

- [x] 4. Guardrails 追加とサニタイズ順序の強化
- [x] 4.1 Guardrails チェックの挿入とフラグ制御
  - Guardrails を SecurityFilter の前段に挿入し、feature flag で有効化/無効化を制御する
  - タイムアウト（config: `guardrails.timeout_seconds`、既定 3s）と失敗時挙動（`guardrails.on_timeout_behavior` = fail-closed/fail-open, `guardrails.on_error_policy`）を設定駆動にし、既定は fail-closed とする
  - Config スキーマ設計: guardrails と StreamingEmitter の timeout キーをまとめて明記する（例）
    ```yaml
    guardrails:
      timeout_seconds: 3
      on_timeout_behavior: fail-closed
      on_error_policy: fail-closed
      providers:
        llama_guard:
          enabled: true
          model: meta-llama/llama-guard-3-8B
          endpoint: https://guard.example.com/v1/check
          timeout_seconds: 2
          on_error_policy: fail-open
    streaming:
      emitter:
        queue_size: 100
        emit_timeout_seconds: 2
    ```
  - 上記スキーマが design.md のガイド（プロバイダ差替え/モデル更新・fail-open/timeout キー）と整合することを確認し、設計側のサンプルと対応付ける
  - _Requirements: セキュリティ/ガード強化_
- [x] 4.2 サニタイズ順序と二重防御の整合
  - Guardrails → SecurityFilter → Template/Schema の順序をコードに反映し、二重サニタイズでの副作用がないようにする
  - 失敗・タイムアウト時のログと拒否レスポンスを統一し、`guardrails.timeout_seconds` / `guardrails.on_timeout_behavior` / `guardrails.on_error_policy` の設定値が実装に反映されることを確認する
  - _Requirements: セキュリティ/ガード強化_
- [x] 4.3 Guardrails テスト
  - ブロックケース、タイムアウト、fail-open/closed 切替時の挙動をテストで検証する
  - 難読化や多言語入力が検知されることを確認し、通過時に SecurityFilter へ正しく連携することを確かめる
  - _Requirements: セキュリティ/ガード強化_

- [x] 5. プラグイン署名検証の強化
- [x] 5.1 署名検証フローの実装
  - YAML 正規化後の内容を署名検証し、公開鍵を設定ファイルまたは `MAGI_PLUGIN_PUBKEY_PATH` からロードできるようにする（優先度: 設定ファイル > `MAGI_PLUGIN_PUBKEY_PATH` > ビルトイン/フェイルバック）。各段でロード可否をログ出力する
  - 「旧ハッシュパス」は SHA-256 のみを保持し署名検証できないレガシー形式（verify-only モード）であると定義し、検出時は verify-only として動作させる
  - 検証失敗時はブロックし、署名有無・鍵識別子・パスをログに残す
  - 移行計画: レガシー verify-only を 6 ヶ月 deprecation → 3 ヶ月警告 → 3 ヶ月後に完全削除のサンセットスケジュールを明記する
  - テスト準備: テスト用 RSA/ECDSA キーペア生成手順と、ハッシュのみケース用のハッシュ生成＋ verify-only フラグ付与のモック方法を明記する
  - _Requirements: セキュリティ/署名検証_
- [x] 5.2 署名検証のテスト
  - 正常署名・改ざん・鍵不一致・署名欠落の各ケースで適切に通過/拒否されることをテストする
  - ハッシュのみ提供される旧来パスでも後方互換を維持することを確認する
  - _Requirements: セキュリティ/署名検証_

- [x] 6. 統合・リグレッション・後方互換確認
- [x] 6.1 フラグ別動作の回帰確認
  - Hardened ON/OFF、ストリーミング ON/OFF、Guardrails ON/OFF、legacy フォールバック ON/OFF の組み合わせで主要フローが成立することを確認する
  - _Requirements: 全般_
- [x] 6.2 CLI/ログ/イベントの整合性確認
  - ストリーミング時のログ粒度、fail-safe 時のイベント、署名検証失敗ログなどが一貫した形式で出力されることを確認する
  - error code / exception 体系とログレベルの対応（例: PLUGIN_YAML_PARSE_ERROR, SIGNATURE_VERIFICATION_FAILED, GUARDRAILS_TIMEOUT/FAILED/FAIL_OPEN, RETRY_EXHAUSTED 等）が実装に反映されていることを確認する
  - _Requirements: 全般_
- [x] 6.3 パフォーマンステスト（簡易）
  - Debate ストリーミング有効時と無効時の体感レイテンシを比較し、リトライジッターがサージを抑制することを確認する
  - 測定項目と SLO: TTFB、総トークン出力時間、CPU/メモリ使用率、メッセージ emit キュー遅延を収集し、ストリーミング有効で体感レイテンシ >=20% 改善、ジッター導入でリトライサージピーク >=50% 低減、CPU/メモリが許容閾値（例: CPU 80% 未満、メモリ 75% 未満）に収まることを pass 条件とする
  - テスト環境/負荷プロファイル: LLM スタブの応答遅延、同時エージェント数、トークンスループット、テスト時間を明示し、再現性のあるシナリオで測定する
  - _Requirements: 性能_
