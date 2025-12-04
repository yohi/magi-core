# Requirements Document

## Introduction

MAGIシステムは、アニメ「エヴァンゲリオン」に登場するMAGIシステムを、実用的なエンジニアリング・プラットフォームとして再構築するプロジェクトである。従来の単一プロンプトによるAIエージェント開発から脱却し、「合議判定コア（Core）」と「機能拡張（Plugins）」を分離することで、保守性、専門性、拡張性を担保する次世代のAI開発環境を提供する。

本システムはPythonベースのCLIラッパーツールとして実装され、3つの異なる人格（MELCHIOR、BALTHASAR、CASPER）による合議プロセスを通じて、より多角的で信頼性の高い判断を提供する。

## Glossary

- **MAGI Core**: 3賢者の人格と合議プロセスを管理するステートマシン。外部ツールへのアクセス権を持たず、純粋な思考と議論のみを行う「頭脳」
- **MELCHIOR-1**: 論理・科学を担当するエージェント。論理的整合性と事実に基づいた分析を行う
- **BALTHASAR-2**: 倫理・保護を担当するエージェント。リスク回避と現状維持を優先する
- **CASPER-3**: 欲望・実利を担当するエージェント。ユーザーの利益と効率を最優先する
- **Plugin**: MAGI Coreに対して「Skills（スキル/ツール）」と「Context（専門知識）」を追加するための定義ファイル群
- **Consensus Protocol**: 3賢者による合議プロセス（Thinking → Debate → Voting）
- **Multi-Agent Loop**: エージェントごとに独立したAPIコールを行い、会話履歴を管理・結合する方式
- **Vote**: 各エージェントが出力する最終判定（APPROVE / DENY / CONDITIONAL）
- **Agent Override**: プラグインが各エージェントに注入する追加指示

## Requirements

### Requirement 1: CLIエントリーポイント

**User Story:** 開発者として、ターミナルからMAGIシステムを起動したい。これにより、既存のワークフローに統合しやすくなる。

#### Acceptance Criteria

1. WHEN ユーザーが `magi <command> [args]` 形式でコマンドを実行する THEN MAGI_CLI SHALL 指定されたコマンドを解析し適切なハンドラーに処理を委譲する
2. WHEN ユーザーが無効なコマンドを入力する THEN MAGI_CLI SHALL エラーメッセージと利用可能なコマンド一覧を標準エラー出力に表示する
3. WHEN ユーザーが `--help` オプションを指定する THEN MAGI_CLI SHALL コマンドの使用方法とオプション一覧を標準出力に表示する
4. WHEN ユーザーが `--version` オプションを指定する THEN MAGI_CLI SHALL 現在のバージョン番号を標準出力に表示する

### Requirement 2: LLM APIクライアント

**User Story:** システム管理者として、LLM APIとの通信を管理したい。これにより、各エージェントが独立して思考を生成できるようになる。

#### Acceptance Criteria

1. WHEN MAGI_CoreがエージェントにAPIリクエストを送信する THEN LLM_Client SHALL Anthropic APIを使用してレスポンスを取得する
2. WHEN APIリクエストがタイムアウトする THEN LLM_Client SHALL 設定された再試行回数まで再試行を行う
3. WHEN APIがエラーレスポンスを返す THEN LLM_Client SHALL エラー種別に応じた適切なエラーメッセージを生成する
4. WHEN 複数のエージェントが同時にAPIリクエストを必要とする THEN LLM_Client SHALL 各エージェントに対して独立したAPIコールを実行する

### Requirement 3: 3賢者ペルソナ管理

**User Story:** 開発者として、3つの異なる視点からの分析を得たい。これにより、単一視点では見落としがちな問題を発見できる。

#### Acceptance Criteria

1. WHEN MAGI_Coreが初期化される THEN Persona_Manager SHALL MELCHIOR-1、BALTHASAR-2、CASPER-3の3つのペルソナを生成する
2. WHEN MELCHIOR-1が思考を生成する THEN Persona_Manager SHALL 論理的整合性と事実に基づいた分析を出力する
3. WHEN BALTHASAR-2が思考を生成する THEN Persona_Manager SHALL リスク回避と潜在的危険性の指摘を出力する
4. WHEN CASPER-3が思考を生成する THEN Persona_Manager SHALL ユーザー利益と効率性の観点からの評価を出力する
5. WHEN プラグインがロードされる THEN Persona_Manager SHALL 各ペルソナの基本特性を維持しながらプラグイン固有の指示を追加する

### Requirement 4: 合議プロトコル（Thinking Phase）

**User Story:** 開発者として、各エージェントの独立した初期意見を得たい。これにより、相互影響のない純粋な各視点の分析を確認できる。

#### Acceptance Criteria

1. WHEN ユーザーがプロンプトを入力する THEN Consensus_Engine SHALL 3つのエージェントに対して独立した思考生成を要求する
2. WHEN Thinking Phaseが開始される THEN Consensus_Engine SHALL 各エージェントが他のエージェントの出力を参照できない状態で思考を生成する
3. WHEN 全エージェントが思考を完了する THEN Consensus_Engine SHALL 3つの独立した思考結果を収集し次のフェーズに進む
4. WHEN エージェントの思考生成が失敗する THEN Consensus_Engine SHALL エラーを記録し残りのエージェントの処理を継続する

### Requirement 5: 合議プロトコル（Debate Phase）

**User Story:** 開発者として、エージェント間の議論を通じた深い分析を得たい。これにより、各視点の相互作用から新たな洞察を得られる。

#### Acceptance Criteria

1. WHEN Debate Phaseが開始される THEN Consensus_Engine SHALL 各エージェントに他の2つのエージェントの思考結果を提供する
2. WHEN エージェントが反論を生成する THEN Consensus_Engine SHALL 他のエージェントの意見に対する反論または補足を出力する
3. WHEN 設定されたラウンド数に達する THEN Consensus_Engine SHALL Debate Phaseを終了しVoting Phaseに移行する
4. WHEN ラウンド数が設定されていない THEN Consensus_Engine SHALL デフォルトで1ラウンドのDebateを実行する

### Requirement 6: 合議プロトコル（Voting Phase）

**User Story:** 開発者として、各エージェントの最終判定を得たい。これにより、合議結果に基づいた意思決定ができる。

#### Acceptance Criteria

1. WHEN Voting Phaseが開始される THEN Consensus_Engine SHALL 各エージェントにAPPROVE、DENY、CONDITIONALのいずれかの投票を要求する
2. WHEN 全エージェントが投票を完了する THEN Consensus_Engine SHALL 投票結果を集計し最終判定を決定する
3. WHEN 投票結果がAPPROVEの場合 THEN Consensus_Engine SHALL Exit Code 0を返す
4. WHEN 投票結果がDENYの場合 THEN Consensus_Engine SHALL Exit Code 1を返す
5. WHEN 投票結果がCONDITIONALを含む場合 THEN Consensus_Engine SHALL 条件付き承認の詳細を出力に含める

### Requirement 7: 会話履歴管理

**User Story:** 開発者として、合議プロセス全体の履歴を追跡したい。これにより、判断の根拠を後から確認できる。

#### Acceptance Criteria

1. WHEN 各フェーズが完了する THEN Context_Manager SHALL エージェントの出力を会話履歴に追加する
2. WHEN 新しいフェーズが開始される THEN Context_Manager SHALL 必要な履歴情報を各エージェントのコンテキストに含める
3. WHEN 合議プロセスが完了する THEN Context_Manager SHALL 全体の会話履歴を構造化された形式で出力可能にする
4. WHEN 会話履歴のサイズがトークン制限に近づく THEN Context_Manager SHALL 古い履歴を要約または削除して制限内に収める

### Requirement 8: プラグインローダー

**User Story:** 開発者として、YAMLファイルからプラグイン定義を読み込みたい。これにより、MAGIの機能を柔軟に拡張できる。

#### Acceptance Criteria

1. WHEN ユーザーがプラグインファイルを指定する THEN Plugin_Loader SHALL 指定されたYAMLファイルを読み込みパースする
2. WHEN YAMLファイルが有効なプラグイン定義を含む THEN Plugin_Loader SHALL プラグインのメタデータと設定を抽出する
3. WHEN YAMLファイルが無効な形式の場合 THEN Plugin_Loader SHALL 具体的なエラー箇所を示すエラーメッセージを出力する
4. WHEN プラグインがagent_overridesを含む THEN Plugin_Loader SHALL 各エージェントのシステムプロンプトに追加指示を注入する

### Requirement 9: 外部コマンド実行

**User Story:** 開発者として、プラグインから外部ツールを実行したい。これにより、既存のCLIツールをMAGIワークフローに統合できる。

#### Acceptance Criteria

1. WHEN プラグインが外部コマンドの実行を要求する THEN Command_Executor SHALL subprocessを使用してコマンドを実行する
2. WHEN 外部コマンドが標準出力を生成する THEN Command_Executor SHALL 出力をキャプチャしMAGI Coreに提供する
3. WHEN 外部コマンドがエラーを返す THEN Command_Executor SHALL エラーコードとエラー出力をMAGI Coreに報告する
4. WHEN 外部コマンドがタイムアウトする THEN Command_Executor SHALL プロセスを終了しタイムアウトエラーを報告する

### Requirement 10: サンプルプラグイン（magi-cc-sdd-plugin）

**User Story:** 開発者として、cc-sddを使用した仕様レビュー機能を利用したい。これにより、仕様書の品質を3賢者の視点から検証できる。

#### Acceptance Criteria

1. WHEN ユーザーが `magi spec <request>` を実行する THEN SDD_Plugin SHALL cc-sddコマンドを実行しドラフト仕様書を生成する
2. WHEN ドラフト仕様書が生成される THEN SDD_Plugin SHALL 仕様書の内容を3賢者のレビュー対象として提供する
3. WHEN 3賢者がレビューを完了する THEN SDD_Plugin SHALL 指摘事項を反映した修正版仕様書を生成する
4. WHEN cc-sddコマンドが利用できない場合 THEN SDD_Plugin SHALL 適切なエラーメッセージを表示しプラグインの無効化を提案する

### Requirement 11: 出力フォーマット

**User Story:** 開発者として、合議結果を構造化された形式で受け取りたい。これにより、結果の解析や他ツールとの連携が容易になる。

#### Acceptance Criteria

1. WHEN 合議プロセスが完了する THEN Output_Formatter SHALL 各エージェントの思考、議論、投票結果を含む構造化出力を生成する
2. WHEN ユーザーがJSON形式を指定する THEN Output_Formatter SHALL 結果をJSON形式で標準出力に出力する
3. WHEN ユーザーがMarkdown形式を指定する THEN Output_Formatter SHALL 結果を人間が読みやすいMarkdown形式で出力する
4. WHEN 出力形式が指定されない THEN Output_Formatter SHALL デフォルトでMarkdown形式を使用する

### Requirement 12: 設定管理

**User Story:** 開発者として、MAGIの動作をカスタマイズしたい。これにより、プロジェクトごとの要件に合わせた設定ができる。

#### Acceptance Criteria

1. WHEN MAGIが起動する THEN Config_Manager SHALL 設定ファイルまたは環境変数から設定を読み込む
2. WHEN API キーが設定されていない THEN Config_Manager SHALL 明確なエラーメッセージを表示し起動を中止する
3. WHEN Debateラウンド数が設定される THEN Config_Manager SHALL 指定された回数をConsensus_Engineに適用する
4. WHEN 投票閾値が設定される THEN Config_Manager SHALL 指定された閾値（majority、unanimous等）をVoting判定に適用する
