# Requirements Document

## Introduction
残課題で停滞している CLI 合議機能とガバナンスの不整合を解消し、監査可能性・フェイルセーフ性・テスト健全性を回復する。`magi` CLI が質問処理・仕様レビュー・セキュリティログ・スキーマ検証・トークン予算圧縮を安定稼働させ、メタデータとテストが一貫して信頼できる状態を提供することを目的とする。

## Requirements

### Requirement 1: `magi ask` の合議実行と結果提示
**Objective:** CLI 利用者として、`magi ask` で質問を入力すると 3 賢者合議の結果を受け取りたい。プロセスを統合して未実装エラーを解消し、再実行性とログを担保するため。

#### Acceptance Criteria
1. WHEN ユーザが `magi ask "<質問>"` を実行したとき THEN システムは ConsensusEngine を起動し Thinking/Debate/Voting を完了した合議結果を CLI に提示 SHALL。
2. IF 合議中に LLM エラーやクオーラム未達が発生したとき THEN システムはフェイルセーフメッセージと発生段階を含む要約ログを CLI に出力 SHALL。
3. WHERE CLI 実行時にログディレクトリが設定されているとき THEN システムは合議開始・終了・所要時間・採用モデルを含む実行ログを保存 SHALL。

### Requirement 2: `magi spec` の 3 賢者レビュー統合表示
**Objective:** 開発者として、`magi spec` 実行後に 3 賢者レビュー結果と進行ステータスを確認したい。レビュー未統合状態を解消し、進行状況を可視化するため。

#### Acceptance Criteria
1. WHEN `magi spec --review` を実行したとき THEN システムは cc-sdd プラグインを通じて各賢者のレビュー出力を取得し CLI に整形表示 SHALL。
2. IF レビュー結果が取得できなかったとき THEN システムは失敗理由と再試行手順を含むメッセージを表示 SHALL。
3. WHILE レビューが完了していない間 THE システム SHALL ステータスを「進行中」と表示し、完了時には「完了」として要約を表示 SHALL。

### Requirement 3: SecurityFilter の禁止パターン監査ログ
**Objective:** セキュリティ担当として、入力サニタイズで除去された禁止パターンを監査ログに残したい。`removed_patterns` が空になる問題を解消し、追跡可能性を確保するため。

#### Acceptance Criteria
1. WHEN SecurityFilter が入力から禁止パターンを除去したとき THEN システムは除去したパターン種別と件数を `removed_patterns` に記録 SHALL。
2. WHEN 禁止パターン除去が行われたとき THEN システムは監査ログに入力断片（マスク済み）とパターン ID を出力 SHALL。
3. IF ログ出力先が未設定のとき THEN システムは標準エラーに警告を出し、サニタイズは継続 SHALL。

### Requirement 4: 投票ペイロード検証のスキーマ化とリトライ
**Objective:** 合議エンジン維持者として、Voting フェーズのペイロードを jsonschema で検証し、自動リトライでフェイルセーフにしたい。手書き検証と無防備な失敗を解消するため。

#### Acceptance Criteria
1. WHEN Voting ペイロード生成後に検証を行うとき THEN システムは定義済み jsonschema で構造・型・必須項目を検証 SHALL。
2. IF 検証が失敗したとき THEN システムは最大設定回数まで再生成をリトライし、各失敗理由をログに残す SHALL。
3. IF リトライ後も失敗したとき THEN システムはフェイルセーフ応答を返し、クオーラム計算を中断した理由を記録 SHALL。

### Requirement 5: トークン予算圧縮の要約ステップと削減ログ精度
**Objective:** 合議エンジン維持者として、トークン予算圧縮に要約ステップを追加し、削減ログを精緻化したい。単純セグメント選択による精度低下と監査性不足を改善するため。

#### Acceptance Criteria
1. WHEN 入力コンテキストが予算閾値を超えるとき THEN システムは重要度選択後に要約ステップを実施し、要約差分を再計算 SHALL。
2. WHILE 圧縮を行う間 THE システム SHALL 削減トークン数・保持率・要約適用の有無をログに記録 SHALL。
3. WHERE `LOG_CONTEXT_REDUCTION_KEY` が有効なとき THEN システムは削減前後のサイズと要約概要を監査ログへ出力 SHALL。

### Requirement 6: メタデータ整合性とテスト健全性の回復
**Objective:** メンテナとして、spec メタデータと tasks の整合を取り、無効化されたプロパティテストを再有効化したい。残課題表示の不整合と CI の欠落カバレッジを解消するため。

#### Acceptance Criteria
1. WHEN `.kiro/specs/magi-core/spec.json` を更新するとき THEN システムは tasks.md の完了状態と remaining_tasks を同期させた値を保持 SHALL。
2. IF プラグインローダーのプロパティテストが `.disabled` で無効化されているとき THEN システムはテストを有効化し CI で実行されるよう設定 SHALL。
3. WHEN テストスイートを実行したとき THEN システムはプラグインローダーのプロパティテスト結果をレポートに含め SHALL。
