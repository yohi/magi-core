# MAGI System: Project Charter & Architectural Concept

## 1\. Vision & Core Value

**「エヴァンゲリオン」のMAGIシステムを、実用的なエンジニアリング・プラットフォームとして再構築する。**
従来の「単一の巨大なプロンプト」によるAIエージェント開発から脱却し、\*\*「合議判定コア（Core）」**と**「機能拡張（Plugins）」\*\*を分離することで、保守性、専門性、拡張性を担保する次世代のAI開発環境を提供する。

## 2\. System Architecture

### 2.1 Form Factor

  * **Type:** Wrapper CLI Tool (Python-based application)
  * **Entry Point:** `magi <command> [args]`
  * **Distribution:** `pip install magi-core` (想定)
  * **Execution Model:**
      * MAGIはユーザーのターミナル上で動作するオーケストレーターである。
      * 外部ツール（例：`cc-sdd`、`claude` CLI、Linter等）はサブプロセスとして実行し、その標準出力をMAGIが取得してコンテキストとして利用する。

### 2.2 The "MAGI Core" Implementation

3賢者の人格と合議プロセスを管理するステートマシン。

  * **LLM Strategy:** **Multi-Agent Loop (Stateful)**
      * Single-Shot（1回のAPIコール）ではなく、エージェントごとに独立したAPIコールを行い、Python側で会話履歴（Context）を管理・結合する。
      * これにより、各人格の純粋性を保ち、複雑な議論が可能になる。
  * **Consensus Protocol:**
    1.  **Thinking:** 3名が独立して初期意見を出力。
    2.  **Debate:** 他者の意見を参照し、反論または補足を行う（設定によりラウンド数を指定可能）。
    3.  **Voting:** `APPROVE` / `DENY` / `CONDITIONAL` の投票を行い、最終的なExit Codeや出力を決定する。

## 3\. The 3 Magi Personas (Kernel)

これらはCoreにハードコードされる不変の特性である。

| Agent           | Personality   | Role in Engineering                                                                                                    |
| :-------------- | :------------ | :--------------------------------------------------------------------------------------------------------------------- |
| **MELCHIOR-1**  | **SCIENTIST** | **Logic & Consistency**<br>論理的整合性、アルゴリズムの正当性、事実確認。感情を排除したドライな視点。                  |
| **BALTHASAR-2** | **MOTHER**    | **Security & Stability**<br>リスク回避、エッジケースの指摘、システム全体の保護。保守的で慎重な視点。                   |
| **CASPER-3**    | **WOMAN**     | **Intuition & Pragmatism**<br>UX（使い勝手）、開発効率、ユーザー利益。多少のリスクを負ってでも「良さ」を追求する視点。 |

## 4\. Plugin System Architecture

MAGIに「ドメイン知識」と「ツール実行能力」を付与する仕組み。

### 4.1 Definition Structure (`plugin.yaml`)

プラグインは宣言的なYAMLファイルと、任意の実行可能スクリプト/バイナリで構成される。

```yaml
plugin:
  name: "magi-cc-sdd-plugin"
  description: "Spec-Driven Development capability via cc-sdd"

# Coreとの接続定義
bridge:
  command: "cc-sdd"  # 実際に叩く外部コマンド
  interface: "stdio" # 標準入出力を通じて連携

# 3賢者への役割注入 (Overlay Instructions)
agent_overrides:
  melchior: "Check requirements for logical contradictions."
  balthasar: "Identify missing error handling scenarios."
  casper: "Ensure the spec solves the user's core problem."
```

### 4.2 Integration Example (`magi-cc-sdd-plugin`)

  * **Target:** `cc-sdd` (Existing Library: [https://github.com/gotalab/cc-sdd](https://github.com/gotalab/cc-sdd))
  * **Flow:**
    1.  ユーザーが `magi spec "ログイン機能"` を実行。
    2.  MAGIがプラグイン定義をロード。
    3.  MAGI内部で `cc-sdd` を実行し、ドラフト仕様書を生成させる。
    4.  生成された仕様書をテキストとして読み込み、3賢者がレビュー・修正議論を行う。
    5.  合意形成された修正版仕様書をファイルとして書き出す。

## 5\. MVP Scope (Phase 1)

今回の開発フェーズで実現する範囲を定義する。

### In Scope (やること)

  * **MAGI Core Framework:**
      * CLI引数解析 (`argparse`/`click`)
      * LLM API Client (Anthropic API想定)
      * 3賢者のPersona管理とConversation Loopの実装
      * Voting / Consensus Logicの実装
  * **Plugin Loader:**
      * 指定されたYAMLを読み込み、System Promptに追加指示（Override）を注入する機能。
      * 外部コマンド実行機能 (`subprocess`)。
  * **Sample Plugin:**
      * `magi-cc-sdd-plugin` の最小構成（`cc-sdd` をラップして仕様レビューさせる）。

### Out of Scope (やらないこと)

  * **Native MCP Server化:** 今回はCLIアプリとしての完成度を優先する。
  * **Web UI / GUI:** ターミナルのみで完結させる。
  * **Complex Plugin Implementation:** コードレビュー機能 (`magi-claude-code-review-plugin`) はアーキテクチャ検証用としては重すぎるため、フェーズ2以降とする。
  * **User Plugin Store:** プラグインの配布・管理機構（Registry）は作らない。ローカルファイル指定のみ。
