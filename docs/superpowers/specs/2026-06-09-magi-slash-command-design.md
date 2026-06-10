# /magi スラッシュコマンド設計仕様

**作成日**: 2026-06-09  
**ステータス**: 承認済み  
**スコープ**: magi本体の `--preset` オプション追加 + Claude Code / OpenCode 向けスラッシュコマンド定義

---

## 概要

AIエージェント環境（Claude Code / OpenCode）から `/magi <質問>` または `/magi:arch <質問>` のようなスラッシュコマンドで MAGI System の合議判定を呼び出せるようにする。

ペルソナセット（3賢者の人格定義）は **コード組込みの `BUILTIN_PRESETS`** を基本とし、`magi.yaml` の `presets` で上書き・追加する。人格定義を SKILL.md に埋め込まないため二重管理を排除する。

---

## ゴール

- `Claude Code` と `OpenCode` の両方でスラッシュコマンドとして動作する
- `/magi` でデフォルトプリセット（赤木ナオコの3側面）、`/magi:arch` でアーキテクチャレビュープリセットが使える
- 出力は構造化テキスト（Thinking / Debate / Voting フェーズ別）
- プリセットの追加は組込み（`BUILTIN_PRESETS`）または `magi.yaml` の1エントリ + スキルファイル1つで完結する

---

## アーキテクチャ

```text
ユーザー: /magi:arch コンテキストを全部メモリに持つべき？
    ↓
.claude/skills/magi-arch/SKILL.md が発火（description マッチ）
    ↓
uv run magi ask --preset arch "コンテキストを全部メモリに持つべき？"
    ↓
magi本体: merged presets（組込み+magi.yaml）の arch を読み PersonaManager.apply_preset()
    ↓
Thinking → Debate → Voting（並列 asyncio）
    ↓
構造化テキスト出力 → チャット画面に表示
```

---

## Section 1: magi 本体の拡張

### 1-1. プリセットの定義場所と解決順序

プリセットは **コード組込み（`src/magi/agents/presets.py` の `BUILTIN_PRESETS`）** を基本とし、`magi.yaml` の `presets` セクションがあればキー単位でマージ上書きする。これにより `/magi:arch` はクローン直後から動作し、かつユーザーは `magi.yaml` 一箇所でカスタマイズできる（人格定義を SKILL.md に埋め込まないため二重管理にならない）。

#### 組込みプリセット（`BUILTIN_PRESETS`）

`default` はキーとして持たず「組込みの `base_prompt` を据え置く」ことを意味する。`arch` のみを同梱する:

```python
BUILTIN_PRESETS: Dict[str, Dict[str, str]] = {
    "arch": {
        "melchior": "あなたはシステムアーキテクトです。大局的な設計判断と長期的な技術的影響を重視して…",
        "balthasar": "あなたはリードエンジニアです。実装の現実性、品質、チームへの影響を重視して…",
        "casper": "あなたはクリエイターです。革新性、ユーザー体験、新しい可能性を重視して…",
    },
}
```

#### magi.yaml による上書き（任意）

```yaml
presets:
  arch:
    melchior: "（archのMELCHIOR人格を部分上書き）"
  security:               # 新規プリセットの追加も可能
    melchior: "..."
    balthasar: "..."
    casper: "..."
```

#### 解決順序

1. `merged = {**BUILTIN_PRESETS, **(config.presets or {})}`（同名キーは magi.yaml が優先）
2. `--preset` 省略時または `default` 指定時: `merged` に `default` があればそれを `apply_preset()` で適用、無ければ組込みの `base_prompt` を据え置く（`apply_preset()` を呼ばない）
3. それ以外の名前: `merged[name]` を `apply_preset()` で適用。存在しなければエラー（Section 3 参照）

**後方互換**: `presets` セクションがない `magi.yaml` も従来通り動作する（`default` は `base_prompt` 据え置き、`arch` は組込みを使用）。

### 1-2. CLI の変更

```bash
magi ask "スイカは果物？"                    # --preset 省略 = default
magi ask --preset default "スイカは果物？"  # 明示指定
magi ask --preset arch "スイカは果物？"     # archプリセット
```

### 1-3. 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `src/magi/agents/presets.py` | **新規**: `BUILTIN_PRESETS`（`arch` を同梱）を定義 |
| `src/magi/config/settings.py` | `presets: Dict[str, Dict[str, str]] = Field(default_factory=dict)` フィールド追加 |
| `src/magi/cli/parser.py` | `--preset <name>` オプション追加 |
| `src/magi/cli/main.py` | preset 名の解決（`{**BUILTIN_PRESETS, **(config.presets or {})}` マージ）→ `PersonaManager` を構築し `apply_preset()` 適用 → `persona_manager=` で `ConsensusEngine` に注入。未知名はエラー |
| `src/magi/agents/persona.py` | `apply_preset()` メソッドを新設（`base_prompt` を置換。既存の `apply_overrides()` は追記挙動のまま不変） |

---

## Section 2: スラッシュコマンド定義

### 2-1. ファイル配置

```text
magi-core/
└── .claude/
    └── skills/
        ├── magi/
        │   └── SKILL.md          # /magi <質問>（defaultプリセット）
        └── magi-arch/
            └── SKILL.md          # /magi:arch <質問>
```

OpenCode は `.claude/skills/` を探索するため、同一ファイルが両エージェントで機能する。  
新プリセット追加 = `BUILTIN_PRESETS` または `magi.yaml` に1エントリ + `.claude/skills/magi-<name>/SKILL.md` を1ファイル追加するだけ。

### 2-2. SKILL.md 構造（デフォルト）

````markdown
---
name: magi
description: MAGIシステムの3賢者（科学者・母親・女としての赤木ナオコ）に質問して合議判定を得る。質問への多角的な判断が必要なとき、あるいはユーザーが /magi と入力したときに使う。
---

# MAGI System — デフォルトプリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行:
   ```bash
   uv run magi ask "$ARGUMENTS"
   ```
3. 出力をそのままチャットに返す

## 注意事項

- 質問は必ず指定すること（空の場合はユーザーに質問を求める）
- `uv` が PATH にない場合は `python -m magi ask "$ARGUMENTS"` を試みる
- 実行にはプロジェクトルートの `magi.yaml` または環境変数 `MAGI_ANTHROPIC_API_KEY` が必要
````

### 2-3. SKILL.md 構造（arch プリセット）

デフォルトと同一構造で、実行コマンドのみ異なる:

```bash
uv run magi ask --preset arch "$ARGUMENTS"
```

---

## Section 3: エラーハンドリング

| ケース | 挙動 |
|---|---|
| 存在しないプリセット名 | `Unknown preset: 'xxx'. Available: <merged presets のキー一覧 + default>` を動的生成して表示し終了コード1（`merged = {**BUILTIN_PRESETS, **(config.presets or {})}`） |
| `presets` セクションなし | 組込み `BUILTIN_PRESETS`（`arch`）はそのまま動作。`default`/省略時は組込み `base_prompt` を据え置き（後方互換） |
| `$ARGUMENTS` が空 | スキルの `description` に明記 + CLI側の既存バリデーション（`"Usage: magi ask <question>"`）が発動 |
| `uv` が PATH にない | スキルに `python -m magi` フォールバック手順を記載 |
| プリセットのペルソナ定義が一部欠けている | 欠けているペルソナは `base_prompt` をそのまま使用（部分上書き） |

---

## テスト方針

- **ユニットテスト**: `ConfigManager` がプリセットを正しく読み込むテスト、`PersonaManager.apply_preset()` が `base_prompt` を置換するテスト、`--preset` がエンジン経由で適用されるテスト
- **手動確認**: `uv run magi ask --preset arch "テスト"` の動作確認、Claude Code / OpenCode でのスラッシュコマンド発火確認

---

## 将来の拡張

新しいプリセット（例: `/magi:security`、`/magi:ux`）を追加するには:

1. 組込みにしたい場合: `src/magi/agents/presets.py` の `BUILTIN_PRESETS` にエントリ追加（クローン直後から動作）
2. ユーザー固有にしたい場合: `magi.yaml` の `presets` にエントリ追加（組込みにマージ上書き）
3. いずれの場合も `.claude/skills/magi-<name>/SKILL.md` を 1 ファイル作成

本体への追加変更は不要。
