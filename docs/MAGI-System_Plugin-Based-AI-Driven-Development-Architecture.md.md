# **MAGIシステム：プラグイン拡張型AI駆動開発アーキテクチャ**

## **1\. 序論：モノリスからモジュラー型MAGIへ**

### **1.1 背景：汎用合議エンジンの必要性**

これまでのAIエージェント開発は、特定のタスク（コーディング、ライティング等）に特化した単一のシステムとして構築される傾向があった。しかし、実際の開発現場では、要件定義、実装、レビュー、テストとフェーズごとに求められる機能は異なる。これら全てを単一の巨大なプロンプトやシステムに詰め込むことは、メンテナンス性の低下とコンテキストの汚染を招く。

### **1.2 新アーキテクチャの提唱**

本報告書では、MAGIシステムを\*\*「汎用的な合議判定コア（MAGI Core）」**と、特定のエンジニアリング能力を提供する**「機能拡張プラグイン（MAGI Plugins）」\*\*に分離するアーキテクチャを提案する。

* **MAGI Core**: 3賢者（メルキオール、バルタザール、カスパー）による対話・投票エンジン。単体では通常のチャットボットとして機能する。  
* **MAGI Plugins**: コアに対し、特定の「専門スキル（Tools）」と「ドメイン知識（Context）」を注入する拡張パック。  
  * 例：magi-cc-sdd-plugin（仕様策定能力の付与）  
  * 例：magi-claude-code-review-plugin（コード監査能力の付与）

この構成により、ユーザーは必要な機能を「インストール」することで、MAGIを用途に合わせてカスタマイズ（仕様策定特化型、QA特化型など）することが可能となる。

## ---

**2\. MAGI Core：合議エンジンの定義**

MAGI Coreは、外部ツールへのアクセス権を持たず、純粋な思考と議論のみを行う「頭脳」である。

### **2.1 3賢者の基本人格（カーネル）**

コアシステムには、以下の3つの性格特性（Persona）のみが定義されている。これらはどのようなプラグインが読み込まれても不変である。

| エージェント | 思考特性 | 役割（デフォルト） |
| :---- | :---- | :---- |
| **MELCHIOR-1** | **論理・科学** | 提示された議題に対し、論理的整合性と事実に基づいた分析を行う。感情や忖度を排除し、客観的な正しさを追求する。 |
| **BALTHASAR-2** | **倫理・保護** | リスク回避と現状維持を優先する。新しい提案に対して慎重であり、潜在的な危険性や副作用を指摘する。 |
| **CASPER-3** | **欲望・実利** | ユーザーの利益と効率を最優先する。リスクがあってもリターンが大きければ採用し、直感的な「良さ」を評価する。 |

### **2.2 合議プロトコル**

MAGI Coreは、ユーザーからの入力（Prompt）を受け取ると、以下のプロセスを実行する。

1. **Thinking（思考）**: 3エージェントが独立して思考を出力。  
2. **Debate（議論）**: 他のエージェントの出力に対する反論。  
3. **Voting（投票）**: 最終的な結論に対し APPROVE / DENY / CONDITIONAL を投票。

## ---

**3\. プラグイン・アーキテクチャ**

プラグインは、MAGI Coreに対して\*\*「Skills（スキル/ツール）」**と**「Context（専門知識）」\*\*を追加するための定義ファイル群である。Claude Codeの拡張機能として実装される。

### **3.1 プラグインの構成要素（Manifest）**

各プラグインは、以下の要素を持つplugin.yaml（またはそれに準ずる定義）で構成される。

YAML

plugin:  
  name: magi-cc-sdd-plugin  
  version: 1.0.0  
  description: "Adds Spec-Driven Development capabilities to MAGI"

capabilities:  
  \- tool: "cc-sdd" \# 外部CLIツールへのバインディング  
  \- knowledge: "sdd-methodology.md" \# 仕様駆動開発のルールセット

agent\_overrides: \# 各エージェントへの役割注入  
  melchior: "Validate logic against strict requirements."  
  balthasar: "Check for missing edge cases in specs."  
  casper: "Ensure specs deliver user value."

## ---

**4\. 公式プラグインの実装詳細**

### **4.1 magi-cc-sdd-plugin：仕様駆動開発の実装**

このプラグインは、MAGIに「仕様書（Spec）」を読み書きする能力と、cc-sddフレームワークに基づいた開発フローを理解させる。

* **概要**: cc-sdd (Claude Code Spec-Driven Development) をバックエンドで使用し、仕様書の作成・検証プロセスをMAGIが代行する。  
* **追加されるコマンド**: /magi spec \<request\>

**各エージェントへの機能拡張:**

| エージェント | 追加される能力 (Skills) | プラグイン動作時の振る舞い |
| :---- | :---- | :---- |
| **MELCHIOR** | read\_spec, validate\_logic | cc-sddが生成した構造化仕様書（Requirements/Design）の整合性をチェックする。「要件Aと要件Bが矛盾している」といった論理的欠陥を検出する。 |
| **BALTHASAR** | risk\_assessment | 仕様の抜け漏れ（Edge Cases）を探す。「この仕様では、ネットワーク切断時の挙動が定義されていない」といった防御的な指摘を行う。 |
| **CASPER** | user\_story\_mapping | 仕様がユーザーの意図を満たしているか確認する。「機能は正しいが、使い勝手が悪い」といったUX視点での修正を要求する。 |

**実行フロー:**

1. ユーザー: /magi spec "ログイン画面を作って"  
2. MAGI Core: プラグインをロードし、cc-sddを使ってドラフト仕様を作成。  
3. 3賢者: ドラフト仕様を審議。  
   * Melchior: 「パスワードポリシーの定義が欠落している。」  
   * Balthasar: 「2要素認証がないのはセキュリティリスクだ。」  
   * Casper: 「入力欄が多すぎてユーザーが離脱する。ソーシャルログインを追加すべき。」  
4. 出力: 3名の指摘を反映した「修正版仕様書」を生成し、ユーザーに承認を求める。

### **4.2 magi-claude-code-review-plugin：コードレビューの実装**

このプラグインは、Claude Codeに標準搭載されているreviewコマンドやsecurity-review機能をMAGIの合議プロセスに統合する。

* **概要**: 単なるLinterの結果表示ではなく、コードの品質、セキュリティ、保守性について3視点から深いレビューを行う。  
* **追加されるコマンド**: /magi review \<file\>

**各エージェントへの機能拡張:**

| エージェント | 追加される能力 (Skills) | プラグイン動作時の振る舞い |
| :---- | :---- | :---- |
| **MELCHIOR** | static\_analysis, complexity\_check | 循環的複雑度やアルゴリズムの効率性を評価。「このネストされたループは $O(n^2)$ であり、リファクタリングが必要」と判定。 |
| **BALTHASAR** | security\_scan (Claude Security) | 脆弱性スキャン結果を参照し、厳格なセキュリティ基準を適用。「入力値のサニタイズが不十分。SQLインジェクションの恐れあり」として拒否権を行使。 |
| **CASPER** | readability\_check, naming\_convention | コードの可読性と命名規則を評価。「変数名 x は意味不明。user\_count に変更すべき」といった、人間にとってのメンテナンス性を重視。 |

**実行フロー:**

1. ユーザー: /magi review src/auth.ts  
2. MAGI Core: Claude Code review コマンドをバックグラウンドで実行し、diffと解析結果を取得。  
3. 3賢者: 解析結果を元に審議。  
4. 出力: MAGI\_REVIEW\_REPORT.md を生成。3名全員の承認（Vote: 3/3）が得られない限り、マージ不可（Exit Code 1）を返す設定も可能。

## ---

**5\. プラグイン開発仕様：Extensibility**

ユーザー自身が新たなプラグインを開発し、MAGIを拡張するための仕様を定義する。

### **5.1 プラグイン定義ファイル (magi-plugin.json)**

カスタムプラグインを作成するには、以下のJSONファイルを定義し、MAGIシステムにロードさせる。

JSON

{  
  "plugin\_id": "magi-performance-tuning",  
  "description": "Performance optimization plugin using specialized profilers",  
  "agents": {  
    "melchior": {  
      "instructions": "Focus strictly on execution time and memory usage.",  
      "tools": \["profiler\_tool", "flamegraph\_reader"\]  
    },  
    "balthasar": {  
      "instructions": "Ensure optimization does not compromise system stability.",  
      "tools": \["load\_testing\_tool"\]  
    },  
    "casper": {  
      "instructions": "Ensure speed improvements are perceptible to the user.",  
      "tools": \["lighthouse\_score"\]  
    }  
  },  
  "voting\_threshold": "unanimous" // 全会一致が必要なプラグインなどの設定  
}

### **5.2 インストール方法**

Claude Codeの環境において、以下のようなコマンド体系で管理することを想定する。

* **インストール**: /magi plugin install./my-plugin.json  
* **有効化**: /magi plugin enable magi-performance-tuning  
* **一覧表示**: /magi plugin list

## ---

**6\. 結論：エコシステムとしてのMAGI**

本アーキテクチャへの移行により、MAGIシステムは単なる「エヴァンゲリオンの再現」を超え、実用的なエンジニアリング・プラットフォームへと進化する。

1. **Coreの軽量化**: コア機能は純粋な推論に特化することで、モデルのアップデートや入れ替えが容易になる。  
2. **専門性のカプセル化**: cc-sddのような特定の手法や、セキュリティ監査のような専門知識をプラグインとして切り出すことで、必要な時に必要な能力だけをロードできる（トークン節約にも寄与）。  
3. **コミュニティ主導の拡張**: プラグイン仕様を公開することで、「要件定義特化MAGI」「リファクタリング特化MAGI」など、ユーザーによる多様な拡張が可能になる。

MAGIはもはや単一のシステムではなく、\*\*「3賢者というアーキテクチャ上で動作するアプリケーション・ランタイム」\*\*となる。