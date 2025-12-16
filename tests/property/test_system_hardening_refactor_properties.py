"""System Hardening Refactor の追加プロパティテスト."""

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from magi.config.settings import MagiSettings
from magi.core.concurrency import ConcurrencyController
from magi.plugins.loader import PluginLoader


def _safe_text(min_size: int = 1, max_size: int = 64) -> st.SearchStrategy[str]:
    """制御文字を含まない安全な文字列ストラテジー."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=min_size,
        max_size=max_size,
    ).filter(lambda v: v.strip() != "")


class TestMagiSettingsProperty(unittest.TestCase):
    """MagiSettings の任意有効値がバリデーションを通過することを検証する."""

    @given(
        api_key=_safe_text(),
        model=_safe_text(),
        timeout=st.integers(min_value=1, max_value=600),
        retry_count=st.integers(min_value=0, max_value=10),
        debate_rounds=st.integers(min_value=1, max_value=10),
        voting_threshold=st.sampled_from(["majority", "unanimous"]),
        quorum_threshold=st.integers(min_value=1, max_value=3),
        token_budget=st.integers(min_value=1, max_value=10000),
        llm_concurrency_limit=st.integers(min_value=1, max_value=8),
        plugin_concurrency_limit=st.integers(min_value=1, max_value=8),
        plugin_load_timeout=st.floats(min_value=0.1, max_value=120, allow_infinity=False, allow_nan=False),
        streaming_enabled=st.booleans(),
        streaming_queue_size=st.integers(min_value=1, max_value=500),
        streaming_overflow_policy=st.sampled_from(["drop", "backpressure"]),
        streaming_emit_timeout=st.floats(min_value=0.01, max_value=10, allow_infinity=False, allow_nan=False),
        guardrails_enabled=st.booleans(),
        guardrails_timeout=st.floats(min_value=0.1, max_value=30, allow_infinity=False, allow_nan=False),
        guardrails_on_timeout=st.sampled_from(["fail-open", "fail-closed"]),
        guardrails_on_error=st.sampled_from(["fail-open", "fail-closed"]),
        plugin_prompt_override_allowed=st.booleans(),
        plugin_trusted_signatures=st.lists(_safe_text(min_size=4, max_size=32), max_size=5),
        production_mode=st.booleans(),
        plugin_public_key_path=st.one_of(
            st.none(),
            st.sampled_from([Path("/tmp/key.pem"), Path("/var/tmp/key.pem")]),
        ),
        output_format=st.sampled_from(["json", "markdown"]),
    )
    @settings(max_examples=80)
    def test_valid_random_settings_pass_validation(
        self,
        api_key: str,
        model: str,
        timeout: int,
        retry_count: int,
        debate_rounds: int,
        voting_threshold: str,
        quorum_threshold: int,
        token_budget: int,
        llm_concurrency_limit: int,
        plugin_concurrency_limit: int,
        plugin_load_timeout: float,
        streaming_enabled: bool,
        streaming_queue_size: int,
        streaming_overflow_policy: str,
        streaming_emit_timeout: float,
        guardrails_enabled: bool,
        guardrails_timeout: float,
        guardrails_on_timeout: str,
        guardrails_on_error: str,
        plugin_prompt_override_allowed: bool,
        plugin_trusted_signatures: list[str],
        production_mode: bool,
        plugin_public_key_path: Path | None,
        output_format: str,
    ) -> None:
        """有効なランダム値で MagiSettings が生成される."""
        if production_mode and plugin_public_key_path is None:
            plugin_public_key_path = Path("/tmp/required.pem")

        settings_model = MagiSettings(
            api_key=api_key,
            model=model,
            timeout=timeout,
            retry_count=retry_count,
            debate_rounds=debate_rounds,
            voting_threshold=voting_threshold,
            quorum_threshold=quorum_threshold,
            token_budget=token_budget,
            llm_concurrency_limit=llm_concurrency_limit,
            plugin_concurrency_limit=plugin_concurrency_limit,
            plugin_load_timeout=plugin_load_timeout,
            streaming_enabled=streaming_enabled,
            streaming_queue_size=streaming_queue_size,
            streaming_overflow_policy=streaming_overflow_policy,
            streaming_emit_timeout=streaming_emit_timeout,
            guardrails_enabled=guardrails_enabled,
            guardrails_timeout=guardrails_timeout,
            guardrails_on_timeout=guardrails_on_timeout,
            guardrails_on_error=guardrails_on_error,
            plugin_prompt_override_allowed=plugin_prompt_override_allowed,
            plugin_trusted_signatures=plugin_trusted_signatures,
            production_mode=production_mode,
            plugin_public_key_path=plugin_public_key_path,
            output_format=output_format,
        )

        self.assertEqual(settings_model.api_key, api_key)
        self.assertEqual(settings_model.plugin_load_timeout, plugin_load_timeout)
        self.assertEqual(settings_model.llm_concurrency_limit, llm_concurrency_limit)


class TestPluginLoaderTimeoutProperty(unittest.TestCase):
    """PluginLoader のタイムアウト解決ロジックのプロパティテスト."""

    @given(timeout=st.floats(min_value=0.01, max_value=30, allow_infinity=False, allow_nan=False))
    @settings(max_examples=50)
    def test_explicit_timeout_is_respected(self, timeout: float) -> None:
        """引数で与えたタイムアウトがそのまま適用される."""
        loader = PluginLoader()
        self.assertAlmostEqual(loader._get_load_timeout(timeout), timeout)

    @given(
        config_timeout=st.one_of(
            st.integers(min_value=1, max_value=120),
            st.floats(min_value=0.1, max_value=120, allow_infinity=False, allow_nan=False),
        )
    )
    @settings(max_examples=50)
    def test_config_timeout_is_used_when_not_explicit(self, config_timeout: float) -> None:
        """config に設定されたタイムアウトが採用される."""
        config = SimpleNamespace(plugin_load_timeout=config_timeout)
        loader = PluginLoader(config=config)
        resolved = loader._get_load_timeout(timeout=None)
        self.assertAlmostEqual(resolved, float(config_timeout))


class TestConcurrencyControllerProperty(unittest.TestCase):
    """ConcurrencyController の同時実行数管理をプロパティで検証する."""

    @given(max_concurrent=st.integers(min_value=1, max_value=5))
    @settings(max_examples=30)
    def test_acquire_updates_metrics(self, max_concurrent: int) -> None:
        """任意の上限値で取得と解放が正しくメトリクスに反映される."""

        async def _run() -> None:
            controller = ConcurrencyController(max_concurrent=max_concurrent)
            async with controller.acquire():
                metrics = controller.get_metrics()
                self.assertEqual(metrics.active_count, 1)
                self.assertEqual(metrics.waiting_count, 0)

            final = controller.get_metrics()
            self.assertEqual(final.active_count, 0)
            self.assertEqual(final.waiting_count, 0)
            self.assertEqual(final.total_acquired, 1)

        asyncio.run(_run())
