# Implementation Plan

- [ ] 1. `magi ask` 合議フローの統合と結果提示
  - CLI から ConsensusEngine を起動し、Thinking/Debate/Voting 結果またはフェイルセーフ応答を表示する経路を実装する。
  - 合議開始・終了・所要時間・採用モデルを監査ログへ記録し、ログ出力先未設定時は警告を STDERR へ出力する。
  - フェイルセーフ発生時に段階と理由を CLI へ要約表示し、再実行可能な状態を維持する。
  - _Requirements: 1_

- [ ] 2. Voting ペイロードの jsonschema 検証とリトライ制御
  - Voting ペイロードを jsonschema で検証する処理を実装し、必須項目・型・値域を網羅的にチェックする。
  - 検証失敗時に最大回数まで再生成をリトライし、各失敗理由と retry カウントを監査ログへ残す。
  - リトライ上限超過時にフェイルセーフ応答を生成し、ConsensusEngine/CLI に伝播させる。
  - _Requirements: 4_

- [ ] 3. トークン圧縮の要約ステップと削減ログ精度向上
  - 入力コンテキストが閾値超過時に重要度選択後の要約ステップを追加し、再計算後の出力を返す。
  - 削減ログに size_before/after、retain_ratio、summary_applied、strategy を記録し、監査ログへ出力する。
  - `LOG_CONTEXT_REDUCTION_KEY` 有効時に削減前後サイズと要約概要を含む監査ログを出力する。
  - _Requirements: 5_

- [ ] 4. SecurityFilter の禁止パターン監査ログ強化
  - 禁止パターン検知・除去時に `removed_patterns` へ種別と件数を記録し、空配列にならないようにする。
  - マスク済み入力断片とパターン ID を監査ログへ出力し、ログ未設定時は警告を STDERR に出す。
  - マスク処理で最大長やフォーマットを統一し、機微情報漏洩を防止する。
  - _Requirements: 3_

- [ ] 5. `magi spec --review` での 3 賢者レビュー統合表示
  - cc-sdd プラグインを呼び出して賢者別レビューを取得し、CLI で整形表示する。
  - 取得失敗時に理由と再試行手順を含むメッセージを表示し、部分失敗も含めて監査ログへ記録する。
  - レビュー進行中/完了のステータスを CLI に表示し、再試行時の手順を明示する。
  - _Requirements: 2_

- [ ] 6. Spec メタデータと tasks の整合性回復
  - tasks.md からタスク状態を読み取り、remaining_tasks を含むメタデータを spec.json に同期する処理を実装する。
  - 書き戻し時に原子的更新を行い、タイムスタンプやソースを記録して不整合を防止する。
  - 同期失敗時にロールバックまたは警告を行い、再試行手順を記録する。
  - _Requirements: 6_

- [ ] 7. テスト強化と回帰防止
  - Unit テストで合議結果表示、サニタイズ監査、投票検証リトライ、トークン圧縮ログの分岐を網羅する。
  - Integration テストで `magi ask` と `magi spec --review` のフローを通し、フェイルセーフとログ出力を検証する。
  - Property テストで PluginLoader の登録・実行が総称的入力で安定することを確認し、CI 実行を有効化する。
  - _Requirements: 1, 2, 3, 4, 5, 6_
