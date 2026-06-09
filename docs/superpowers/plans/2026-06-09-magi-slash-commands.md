# /magi スラッシュコマンド 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `magi ask` に `--preset` オプションを追加し、3賢者の人格セット（`default`/`arch`）を切り替え可能にして、Claude Code / OpenCode の `/magi`・`/magi:arch` スラッシュコマンドから呼び出せるようにする。

**Architecture:** プリセットはコード組込み（`BUILTIN_PRESETS`）を基本とし、`magi.yaml` の `presets` セクションでキー単位マージ上書きする。`PersonaManager.apply_preset()` が `base_prompt` を置換（既存の追記型 `apply_overrides()` とは別物）。`main.py` はプリセットを解決して `PersonaManager` を構築し、`persona_manager=` で `ConsensusEngine` に注入する（エンジン本体は変更不要）。

**Tech Stack:** Python 3.11+, Pydantic V2 (`MagiSettings`), unittest, uv

**参照仕様:** `docs/superpowers/specs/2026-06-09-magi-slash-command-design.md`

---

## ファイル構成

| ファイル | 責務 | 変更種別 |
|---|---|---|
| `src/magi/agents/presets.py` | `BUILTIN_PRESETS` 定義 + `resolve_preset_prompts()` 解決ロジック | 新規 |
| `src/magi/agents/persona.py` | `apply_preset()` メソッド追加（base_prompt 置換） | 変更 |
| `src/magi/config/settings.py` | `presets` フィールド追加 | 変更 |
| `src/magi/cli/parser.py` | `--preset <name>` オプション解析 | 変更 |
| `src/magi/cli/main.py` | プリセット解決 → PersonaManager 構築 → エンジン注入 | 変更 |
| `.claude/skills/magi/SKILL.md` | `/magi`（default）コマンド定義 | 新規 |
| `.claude/skills/magi-arch/SKILL.md` | `/magi:arch` コマンド定義 | 新規 |
| `tests/unit/test_presets.py` | presets.py のテスト | 新規 |
| `tests/unit/test_persona.py` | apply_preset テスト追加 | 変更 |
| `tests/unit/test_magi_settings.py` | presets フィールドテスト追加 | 変更 |
| `tests/unit/test_cli.py` | `--preset` パース + 配線テスト追加 | 変更 |

**依存関係:** Task 1〜4 は相互独立（並列実行可能）。Task 5 は Task 1〜4 に依存。Task 6 は独立。Task 7 は全タスクに依存。

---

## Task 1: 組込みプリセットモジュール

**Files:**
- Create: `src/magi/agents/presets.py`
- Test: `tests/unit/test_presets.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/unit/test_presets.py`:

```python
"""組込みプリセットと解決ロジックのユニットテスト"""
import unittest

from magi.agents.presets import BUILTIN_PRESETS, resolve_preset_prompts


class TestBuiltinPresets(unittest.TestCase):
    """BUILTIN_PRESETS の構造を検証する"""

    def test_arch_preset_exists(self):
        """arch プリセットが3賢者すべてを定義している"""
        self.assertIn("arch", BUILTIN_PRESETS)
        arch = BUILTIN_PRESETS["arch"]
        self.assertIn("melchior", arch)
        self.assertIn("balthasar", arch)
        self.assertIn("casper", arch)

    def test_default_is_not_a_key(self):
        """default はキーとして持たない（base_prompt 据え置きを意味する）"""
        self.assertNotIn("default", BUILTIN_PRESETS)


class TestResolvePresetPrompts(unittest.TestCase):
    """resolve_preset_prompts の解決順序を検証する"""

    def test_none_returns_none(self):
        """--preset 省略時は None（base_prompt 据え置き）"""
        self.assertIsNone(resolve_preset_prompts(None, None))

    def test_default_returns_none(self):
        """default 指定かつ config に default 無し → None"""
        self.assertIsNone(resolve_preset_prompts("default", {}))

    def test_arch_returns_builtin(self):
        """arch 指定 → 組込みの arch プロンプトを返す"""
        result = resolve_preset_prompts("arch", None)
        self.assertEqual(result, BUILTIN_PRESETS["arch"])

    def test_config_overrides_builtin(self):
        """magi.yaml の presets が組込みを上書きする"""
        config_presets = {"arch": {"melchior": "上書き済み"}}
        result = resolve_preset_prompts("arch", config_presets)
        self.assertEqual(result, {"melchior": "上書き済み"})

    def test_config_adds_new_preset(self):
        """magi.yaml で新規プリセットを追加できる"""
        config_presets = {"security": {"melchior": "セキュリティ専門家"}}
        result = resolve_preset_prompts("security", config_presets)
        self.assertEqual(result, {"melchior": "セキュリティ専門家"})

    def test_config_default_overrides_base_prompt(self):
        """config に default があればそれを返す（base_prompt 上書き）"""
        config_presets = {"default": {"melchior": "カスタムデフォルト"}}
        result = resolve_preset_prompts("default", config_presets)
        self.assertEqual(result, {"melchior": "カスタムデフォルト"})

    def test_unknown_preset_raises_value_error(self):
        """未知のプリセット名は ValueError を送出する"""
        with self.assertRaises(ValueError) as ctx:
            resolve_preset_prompts("nonexistent", None)
        msg = str(ctx.exception)
        self.assertIn("Unknown preset: 'nonexistent'", msg)
        self.assertIn("arch", msg)
        self.assertIn("default", msg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run python -m unittest tests.unit.test_presets -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magi.agents.presets'`

- [ ] **Step 3: presets.py を実装**

Create `src/magi/agents/presets.py`:

```python
"""3賢者の人格プリセット定義と解決ロジック

プリセットはコード組込み（BUILTIN_PRESETS）を基本とし、magi.yaml の
presets セクションでキー単位マージ上書きする。default はキーを持たず、
組込みの base_prompt を据え置くことを意味する。
"""
from typing import Dict, Optional

# 組込みプリセット。default は持たない（base_prompt 据え置きを意味する）。
BUILTIN_PRESETS: Dict[str, Dict[str, str]] = {
    "arch": {
        "melchior": (
            "あなたはシステムアーキテクトです。"
            "大局的な設計判断と長期的な技術的影響を重視し、"
            "スケーラビリティ・保守性・整合性の観点から分析してください。"
        ),
        "balthasar": (
            "あなたはリードエンジニアです。"
            "実装の現実性、品質、チームへの影響を重視し、"
            "技術的負債とレビュー容易性の観点から評価してください。"
        ),
        "casper": (
            "あなたはクリエイターです。"
            "革新性、ユーザー体験、新しい可能性を重視し、"
            "プロダクト価値と独創性の観点から提案してください。"
        ),
    },
}


def resolve_preset_prompts(
    preset_name: Optional[str],
    config_presets: Optional[Dict[str, Dict[str, str]]],
) -> Optional[Dict[str, str]]:
    """プリセット名を解決してペルソナプロンプト辞書を返す

    解決順序:
        1. merged = {**BUILTIN_PRESETS, **config_presets}（同名キーは config 優先）
        2. preset_name 省略 or "default" かつ merged に "default" 無し → None
        3. それ以外 → merged[name]。存在しなければ ValueError

    Args:
        preset_name: --preset で指定された名前（None の場合は default 扱い）
        config_presets: magi.yaml の presets セクション（None 可）

    Returns:
        ペルソナプロンプト辞書。base_prompt を据え置く場合は None。

    Raises:
        ValueError: 未知のプリセット名が指定された場合
    """
    merged: Dict[str, Dict[str, str]] = {
        **BUILTIN_PRESETS,
        **(config_presets or {}),
    }
    name = preset_name or "default"

    if name in merged:
        return merged[name]
    if name == "default":
        return None

    available = ", ".join(sorted(set(merged.keys()) | {"default"}))
    raise ValueError(f"Unknown preset: '{name}'. Available: {available}")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run python -m unittest tests.unit.test_presets -v`
Expected: PASS（8 テスト）

- [ ] **Step 5: コミット**

```bash
git add src/magi/agents/presets.py tests/unit/test_presets.py
git commit -m "feat: 組込みプリセット BUILTIN_PRESETS と解決ロジックを追加"
```

---

## Task 2: PersonaManager.apply_preset()

**Files:**
- Modify: `src/magi/agents/persona.py`（`clear_overrides` の後、ファイル末尾付近に追加）
- Test: `tests/unit/test_persona.py`（`TestPersonaManager` クラスに追加）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_persona.py` の `test_clear_overrides`（195行目付近）の後、`if __name__` の前に以下を追加:

```python
    def test_apply_preset_replaces_base_prompt(self):
        """apply_preset は base_prompt を置換する"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        preset = {"melchior": "あなたはシステムアーキテクトです。"}

        manager.apply_preset(preset)

        melchior = manager.get_persona(PersonaType.MELCHIOR)
        self.assertEqual(melchior.base_prompt, "あなたはシステムアーキテクトです。")
        # 元の論理・科学プロンプトは残っていない
        self.assertNotIn("論理と科学", melchior.base_prompt)

    def test_apply_preset_only_affects_specified_personas(self):
        """apply_preset は指定外のペルソナに影響しない"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        balthasar_base_before = manager.get_persona(
            PersonaType.BALTHASAR
        ).base_prompt

        manager.apply_preset({"melchior": "アーキテクト"})

        balthasar_after = manager.get_persona(PersonaType.BALTHASAR)
        self.assertEqual(balthasar_after.base_prompt, balthasar_base_before)

    def test_apply_preset_preserves_override_prompt(self):
        """apply_preset は既存の override_prompt を保持する（プラグイン併用）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        manager.apply_overrides({"melchior": "プラグイン追加指示"})

        manager.apply_preset({"melchior": "新しい基本人格"})

        melchior = manager.get_persona(PersonaType.MELCHIOR)
        self.assertEqual(melchior.base_prompt, "新しい基本人格")
        self.assertEqual(melchior.override_prompt, "プラグイン追加指示")
        # system_prompt は新base + override を連結
        self.assertEqual(
            melchior.system_prompt, "新しい基本人格\n\nプラグイン追加指示"
        )

    def test_apply_preset_with_unknown_persona(self):
        """未知のペルソナ名は無視される"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        manager.apply_preset({"unknown": "何か", "melchior": "アーキテクト"})

        melchior = manager.get_persona(PersonaType.MELCHIOR)
        self.assertEqual(melchior.base_prompt, "アーキテクト")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run python -m unittest tests.unit.test_persona.TestPersonaManager.test_apply_preset_replaces_base_prompt -v`
Expected: FAIL with `AttributeError: 'PersonaManager' object has no attribute 'apply_preset'`

- [ ] **Step 3: apply_preset を実装**

`src/magi/agents/persona.py` の `clear_overrides` メソッド（189-199行目）の後、クラス末尾に追加:

```python
    def apply_preset(self, preset: Dict[str, str]) -> None:
        """プリセットを適用して base_prompt を置換する

        apply_overrides がプラグイン指示を base_prompt に追記するのに対し、
        apply_preset はペルソナの基本人格そのものを差し替える。
        override_prompt は保持され、新しい base_prompt の上にプラグイン指示が
        追記される（system_prompt プロパティ経由）。

        Args:
            preset: ペルソナ名（小文字）をキー、置換後の base_prompt を値とする辞書
                    例: {"melchior": "あなたはシステムアーキテクトです...", ...}
        """
        for persona_name, prompt in preset.items():
            persona_type = self._STRING_TO_TYPE.get(persona_name.lower())
            if persona_type is None:
                # 未知のペルソナ名は無視
                continue

            existing = self.personas[persona_type]
            self.personas[persona_type] = Persona(
                type=existing.type,
                name=existing.name,
                base_prompt=prompt,
                override_prompt=existing.override_prompt,
            )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run python -m unittest tests.unit.test_persona -v`
Expected: PASS（既存 + 新規4テスト）

- [ ] **Step 5: コミット**

```bash
git add src/magi/agents/persona.py tests/unit/test_persona.py
git commit -m "feat: PersonaManager.apply_preset() で base_prompt を置換可能に"
```

---

## Task 3: MagiSettings.presets フィールド

**Files:**
- Modify: `src/magi/config/settings.py:69`（`personas` フィールドの直後）
- Test: `tests/unit/test_magi_settings.py`（`TestMagiSettings` クラス） + `tests/unit/test_config.py`（`TestConfigManagerWithMagiSettings` クラス）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_magi_settings.py` の `TestMagiSettings` クラス内（`test_default_values` の後）に追加:

```python
    def test_presets_default_empty(self):
        """presets はデフォルトで空辞書"""
        settings = MagiSettings()
        self.assertEqual(settings.presets, {})

    def test_presets_accepts_nested_dict(self):
        """presets はネストした辞書を受け入れる"""
        settings = MagiSettings(
            presets={
                "arch": {
                    "melchior": "アーキテクト",
                    "balthasar": "リードエンジニア",
                    "casper": "クリエイター",
                }
            }
        )
        self.assertEqual(settings.presets["arch"]["melchior"], "アーキテクト")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run python -m unittest tests.unit.test_magi_settings.TestMagiSettings.test_presets_accepts_nested_dict -v`
Expected: FAIL — `extra="forbid"` により `presets` が未定義フィールドとして拒否され `ValidationError` が発生

- [ ] **Step 3: presets フィールドを追加**

`src/magi/config/settings.py` の `personas` フィールド定義（69行目）の直後に追加:

```python
    # ペルソナプリセット設定（人格セットの切り替え用）
    presets: Dict[str, Dict[str, str]] = Field(default_factory=dict)
```

変更後の該当箇所（68-70行目付近）:

```python
    # ペルソナ設定
    personas: Dict[str, PersonaConfig] = Field(default_factory=dict)

    # ペルソナプリセット設定（人格セットの切り替え用）
    presets: Dict[str, Dict[str, str]] = Field(default_factory=dict)
```

- [ ] **Step 4: ConfigManager 経由の読み込みテストを追加**

`tests/unit/test_config.py` の `TestConfigManagerWithMagiSettings` クラスに追加（spec のテスト方針「ConfigManager がプリセットを正しく読み込む」を満たす）:

```python
    def test_load_presets_from_yaml(self):
        """magi.yaml の presets セクションが MagiSettings に読み込まれる"""
        yaml_content = (
            "presets:\n"
            "  arch:\n"
            "    melchior: アーキテクト\n"
            "    balthasar: リードエンジニア\n"
            "    casper: クリエイター\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            config_path = Path(f.name)
        try:
            config = self.manager.load(config_path=config_path)
            self.assertEqual(config.presets["arch"]["melchior"], "アーキテクト")
            self.assertEqual(config.presets["arch"]["casper"], "クリエイター")
        finally:
            config_path.unlink()
```

注: このテストは Step 3 で `presets` フィールドを追加済みなら PASS する（`_normalize_config` が `dict(data)` で presets キーをそのまま通すため）。読み込み経路の回帰検証として追加する。

- [ ] **Step 5: テストが通ることを確認**

Run: `uv run python -m unittest tests.unit.test_magi_settings tests.unit.test_config -v`
Expected: PASS（test_magi_settings 新規2 + test_config 新規1）

- [ ] **Step 6: コミット**

```bash
git add src/magi/config/settings.py tests/unit/test_magi_settings.py tests/unit/test_config.py
git commit -m "feat: MagiSettings に presets フィールドを追加"
```

---

## Task 4: parser に --preset オプション追加

**Files:**
- Modify: `src/magi/cli/parser.py:121`（`--provider` ブロックの後）
- Test: `tests/unit/test_cli.py`（`TestArgumentParser` クラスに追加）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_cli.py` の `TestArgumentParser` クラス内、`test_parse_provider_option`（98行目付近）の後に追加:

```python
    def test_parse_preset_option(self):
        """プリセットオプションのパース"""
        result = self.parser.parse(["--preset", "arch", "ask"])
        self.assertEqual(result.command, "ask")
        self.assertEqual(result.options.get("preset"), "arch")

    def test_parse_preset_lowercased(self):
        """プリセット名は小文字化される"""
        result = self.parser.parse(["--preset", "ARCH", "ask"])
        self.assertEqual(result.options.get("preset"), "arch")

    def test_parse_no_preset_option(self):
        """--preset 省略時は preset オプションが無い"""
        result = self.parser.parse(["ask", "質問"])
        self.assertIsNone(result.options.get("preset"))
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run python -m unittest tests.unit.test_cli.TestArgumentParser.test_parse_preset_option -v`
Expected: FAIL — `result.options.get("preset")` が `None`（`--preset` がコマンドとして扱われず無視される）

- [ ] **Step 3: --preset 解析を実装**

`src/magi/cli/parser.py` の `--provider` ブロック（114-120行目）の後に追加:

```python
            # プリセットオプション
            if arg == "--preset":
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    options["preset"] = argv[i + 1].lower()
                    i += 2
                    continue
                i += 1
                continue
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run python -m unittest tests.unit.test_cli.TestArgumentParser -v`
Expected: PASS（既存 + 新規3テスト）

- [ ] **Step 5: コミット**

```bash
git add src/magi/cli/parser.py tests/unit/test_cli.py
git commit -m "feat: parser に --preset オプションを追加"
```

---

## Task 5: main.py でプリセットを解決しエンジンに注入

**Files:**
- Modify: `src/magi/cli/main.py`（import 追加 + `_run_ask_command` 内のエンジン構築前後）
- Test: `tests/unit/test_cli.py`（`TestMagiCLI` クラスに追加）

**依存:** Task 1（resolve_preset_prompts）, Task 2（apply_preset）, Task 3（presets フィールド）, Task 4（--preset パース）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_cli.py` の `TestMagiCLI` クラス内、`test_run_ask_executes_consensus_and_outputs`（297行目付近）の後に追加:

```python
    def test_run_ask_unknown_preset_returns_error(self):
        """未知のプリセット指定でエラー終了する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
            exit_code = cli._run_ask_command(["hello"], {"preset": "nonexistent"})

        self.assertEqual(exit_code, 1)
        self.assertIn("Unknown preset: 'nonexistent'", mock_stderr.getvalue())

    def test_run_ask_arch_preset_applied_to_engine(self):
        """arch プリセットが PersonaManager 経由でエンジンに注入される"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        from magi.agents.persona import PersonaManager

        result = ConsensusResult(
            thinking_results={
                PersonaType.MELCHIOR: ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="thinking",
                    timestamp=datetime.utcnow(),
                )
            },
            debate_results=[],
            voting_results={
                PersonaType.MELCHIOR: VoteOutput(
                    persona_type=PersonaType.MELCHIOR,
                    vote=Vote.APPROVE,
                    reason="ok",
                    conditions=[],
                )
            },
            final_decision=Decision.APPROVED,
            exit_code=0,
            all_conditions=[],
        )

        captured = {}

        class DummyEngine:
            def __init__(self, *_args, **kwargs):
                captured["persona_manager"] = kwargs.get("persona_manager")

            async def execute(self, prompt: str, plugin=None):
                return result

        config = Config(api_key="test-key")
        cli = MagiCLI(config, output_format=OutputFormat.JSON)

        with patch("magi.cli.main.ConsensusEngine", side_effect=DummyEngine):
            with patch.object(cli, "_has_logging_destination", return_value=True):
                with patch("sys.stdout", new_callable=StringIO):
                    exit_code = cli._run_ask_command(["hello"], {"preset": "arch"})

        self.assertEqual(exit_code, 0)
        pm = captured["persona_manager"]
        self.assertIsInstance(pm, PersonaManager)
        melchior = pm.get_persona(PersonaType.MELCHIOR)
        self.assertIn("アーキテクト", melchior.base_prompt)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run python -m unittest tests.unit.test_cli.TestMagiCLI.test_run_ask_unknown_preset_returns_error -v`
Expected: FAIL — 現状は preset を解決しないため exit_code が 1 にならない（プロバイダ処理に進む）

- [ ] **Step 3: import を追加**

`src/magi/cli/main.py` の import 群（`from magi.core.consensus import ConsensusEngine` の後、33行目付近）に追加:

```python
from magi.agents.persona import PersonaManager
from magi.agents.presets import resolve_preset_prompts
```

- [ ] **Step 4: _run_ask_command にプリセット解決を実装**

`src/magi/cli/main.py` の `_run_ask_command` 内、`question` バリデーション（735-737行目）の後、`try:`（739行目）の前に追加:

```python
        # プリセットを解決して PersonaManager を構築する
        try:
            preset_prompts = resolve_preset_prompts(
                options.get("preset"), self.config.presets
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        persona_manager = PersonaManager()
        if preset_prompts is not None:
            persona_manager.apply_preset(preset_prompts)
```

- [ ] **Step 5: エンジン構築に persona_manager を渡す**

`src/magi/cli/main.py` の `ConsensusEngine(...)` 構築（776-783行目）に `persona_manager=persona_manager` を追加:

```python
        engine = ConsensusEngine(
            self.config,
            persona_manager=persona_manager,
            llm_client_factory=lambda: llm_client,
            event_context={"provider": provider.provider_id},
            concurrency_controller=concurrency_controller,
            provider_selector=self.provider_selector,
            provider_factory=self.provider_factory,
        )
```

- [ ] **Step 6: テストが通ることを確認**

Run: `uv run python -m unittest tests.unit.test_cli.TestMagiCLI -v`
Expected: PASS（既存 + 新規2テスト）

- [ ] **Step 7: コミット**

```bash
git add src/magi/cli/main.py tests/unit/test_cli.py
git commit -m "feat: --preset を解決し PersonaManager をエンジンに注入"
```

---

## Task 6: スラッシュコマンド定義（SKILL.md）

**Files:**
- Create: `.claude/skills/magi/SKILL.md`
- Create: `.claude/skills/magi-arch/SKILL.md`

- [ ] **Step 1: default プリセットのスキルを作成**

Create `.claude/skills/magi/SKILL.md`:

```markdown
---
name: magi
description: MAGIシステムの3賢者（科学者・母親・女としての赤木ナオコ）に質問して合議判定を得る。多角的な判断が必要なとき、あるいはユーザーが /magi と入力したときに使う。
---

# MAGI System — デフォルトプリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行する:
   `uv run magi ask "$ARGUMENTS"`
3. 標準出力の合議結果をそのままチャットに返す

## 注意事項

- 質問は必須。空の場合はユーザーに質問内容を求める
- `uv` が PATH にない場合は `python -m magi ask "$ARGUMENTS"` を試みる
- 実行にはプロジェクトルートの `magi.yaml`、または環境変数 `MAGI_ANTHROPIC_API_KEY` が必要
- 終了コード: 0=APPROVE, 1=DENY, 2=CONDITIONAL
```

- [ ] **Step 2: arch プリセットのスキルを作成**

Create `.claude/skills/magi-arch/SKILL.md`:

```markdown
---
name: magi-arch
description: MAGIシステムをアーキテクチャレビュー人格（システムアーキテクト・リードエンジニア・クリエイター）で起動し、設計判断の合議を得る。技術設計・アーキテクチャの是非を多角的に判断したいとき、あるいはユーザーが /magi:arch と入力したときに使う。
---

# MAGI System — arch プリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行する:
   `uv run magi ask --preset arch "$ARGUMENTS"`
3. 標準出力の合議結果をそのままチャットに返す

## 注意事項

- 質問は必須。空の場合はユーザーに質問内容を求める
- `uv` が PATH にない場合は `python -m magi ask --preset arch "$ARGUMENTS"` を試みる
- arch プリセットは組込み（`BUILTIN_PRESETS`）のためクローン直後から動作する
- `magi.yaml` の `presets.arch` を定義すると人格を上書きできる
- 終了コード: 0=APPROVE, 1=DENY, 2=CONDITIONAL
```

- [ ] **Step 3: ファイルが正しく作成されたことを確認**

Run: `cat .claude/skills/magi/SKILL.md .claude/skills/magi-arch/SKILL.md`
Expected: 両ファイルの内容が表示され、frontmatter（`name`/`description`）が正しい

- [ ] **Step 4: コミット**

```bash
git add .claude/skills/magi/SKILL.md .claude/skills/magi-arch/SKILL.md
git commit -m "feat: /magi・/magi:arch スラッシュコマンド定義を追加"
```

---

## Task 7: 統合検証

**Files:** なし（検証のみ）

- [ ] **Step 1: 全ユニットテストを実行**

Run: `uv run python -m unittest discover -s tests/unit -v`
Expected: 全テスト PASS（新規テスト含む）

- [ ] **Step 2: プロパティテストを実行（ペルソナ不変条件の確認）**

Run: `uv run python -m unittest discover -s tests/property -v`
Expected: 全テスト PASS（`apply_preset` 追加が既存の不変条件を壊していない）

- [ ] **Step 3: default プリセットの手動スモークテスト**

Run: `uv run magi ask "スイカは果物ですか？"`
Expected: 3賢者の合議結果が構造化テキストで出力され、終了コードが 0/1/2 のいずれか
（`MAGI_ANTHROPIC_API_KEY` 等の API キーが必要。未設定環境ではプロバイダ選択エラーで 1 を返すことを確認）

- [ ] **Step 4: arch プリセットの手動スモークテスト**

Run: `uv run magi ask --preset arch "全コンテキストをメモリに保持すべきか？"`
Expected: アーキテクト/リードエンジニア/クリエイター人格での合議結果が出力される

- [ ] **Step 5: 未知プリセットのエラー確認**

Run: `uv run magi ask --preset nonexistent "テスト"; echo "exit=$?"`
Expected: `Unknown preset: 'nonexistent'. Available: arch, default` が表示され `exit=1`

- [ ] **Step 6: 完了報告**

全タスクの完了とテスト結果をユーザーに報告する。
