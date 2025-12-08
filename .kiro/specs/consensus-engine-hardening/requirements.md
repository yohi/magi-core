# 要件ドキュメント

## Introduction
本機能では MAGI の Consensus Engine を性能・信頼性・セキュリティの観点で堅牢化し、合議プロセスの待ち時間とリスクを抑えつつ保守性を高める。トークン予算超過を防ぐための要約・圧縮、ストリーミング応答によるユーザー体験向上、構造化出力とテンプレート外部化による再現性向上、エージェント障害時のクオーラム管理、プロンプト/プラグイン経由の攻撃リスク低減を狙う。

## 要件

### Requirement 1: トークン最適化と応答性
**Objective:** CLI 利用者として、レイテンシとコストを抑えつつ議論・投票結果を迅速に得たいので、コンテキスト膨張を防ぎつつ応答を途切れなく受け取りたい

#### Acceptance Criteria
1. WHEN debate ラウンド終了後に結合コンテキストサイズが設定した予算を超過した場合 THEN Consensus Engine SHALL 議論ログを要約し、次ラウンド以降は要約を元ログの代わりに用いる。
2. IF 投票フェーズの総コンテキスト長が予算を超過する見込みの場合 THEN Consensus Engine SHALL 固定長切り捨てではなく重要度に基づく要約/圧縮を行った上で LLM を呼び出す。
3. WHILE CLI セッションが LLM 出力を待機している間 THE Magi CLI SHALL 生成トークンを到着次第ストリーミング表示し続ける。
4. WHERE コンテキスト削減が発生する場合 THE Consensus Engine SHALL 削減理由と削減後のトークン指標をログに記録する。

### Requirement 2: 構造化出力とプロンプト保守性
**Objective:** 開発者として、LLM 出力の再現性を高めつつプロンプト変更を安全に回せるようにしたいので、構造化出力とテンプレート管理を強化したい

#### Acceptance Criteria
1. WHEN エージェントに投票を要求する場合 THEN Consensus Engine SHALL 定義済みスキーマに従うツールベースの JSON 形式での出力を必須とする。
2. IF 受信した投票ペイロードがスキーマ検証に失敗した場合 THEN Consensus Engine SHALL 設定回数まで再生成を試み、上限到達後は明示的なエラーで処理を中断する。
3. WHERE プロンプトテンプレートをコード外で更新する場合 THE Consensus Engine SHALL 外部設定ファイルからテンプレートを読み込み、コード変更なしで再読み込みできるようにする。
4. WHEN スキーマまたはテンプレートの不整合が検出された場合 THEN Consensus Engine SHALL 影響するテンプレート名とフィールドを含む実行可能なログを出力する。

### Requirement 3: フェイルセーフとクオーラム管理
**Objective:** 運用者として、エージェント障害時でも誤った合議結果を出さないようにしたいので、クオーラムとリトライ挙動を制御したい

#### Acceptance Criteria
1. IF いずれかのフェーズで有効なエージェント数が設定したクオーラムを下回った場合 THEN Consensus Engine SHALL セッションを中断し、CLI にフェイルセーフ状態を返す。
2. WHEN 個別エージェント呼び出しが失敗した場合 THEN Consensus Engine SHALL 設定回数までリトライし、上限超過後は当該エージェントを投票から除外した理由を記録する。
3. WHEN クオーラム不足による中断が発生した場合 THEN Consensus Engine SHALL 投票結果を出力せず、ユーザー向けに不足状況を示すメッセージを返す。
4. WHILE リトライ処理を進行している間 THE Consensus Engine SHALL 既に取得済みの有効出力を保持し、上書きしない。

### Requirement 4: セキュリティ強化
**Objective:** セキュリティ担当として、プロンプトインジェクションやプラグイン経由のコマンドインジェクションを防ぎたいので、入力の境界と検証を強化したい

#### Acceptance Criteria
1. WHERE ユーザー提供テキストをプロンプトに埋め込む場合 THE Consensus Engine SHALL データ領域を明示するマーカーで囲み、制御シーケンスをエスケープした上で LLM に送信する。
2. IF ユーザープロンプトや議論コンテキストに禁止パターンやインジェクション指示が含まれる場合 THEN Consensus Engine SHALL 入力を拒否またはサニタイズし、事象を監査ログに残す。
3. WHEN プラグインコマンドを読み込みまたは実行する場合 THEN Plugin Loader SHALL 引数を検証してシェルインジェクションを防ぎ、検証失敗時は実行を拒否する。
4. WHERE プラグインに要求される署名または許可リスト情報が欠落している場合 THE Plugin Loader SHALL プラグインを無効化し、実行前に理由を通知する。
