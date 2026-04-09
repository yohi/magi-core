"""
MagiAdapterの実装

WebUIとMagi Core（ConsensusEngine）を接続するためのアダプターインターフェースと実装を提供する。
"""
import asyncio
import copy
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Optional

from magi.config.manager import Config
from magi.config.provider import ProviderConfigLoader
from magi.core.consensus import ConsensusEngine
from magi.core.providers import (
    ProviderAdapterFactory,
    ProviderRegistry,
    ProviderSelector,
)
from magi.core.streaming import StreamChunk, QueueStreamingEmitter
from magi.models import ConsensusPhase, Decision, PersonaType, Vote, ConsensusResult
from magi.webui_backend.models import SessionOptions, UnitType, UnitState

logger = logging.getLogger(__name__)

class MagiAdapter(ABC):
    """Magi Coreを実行し、イベントストリームを生成するアダプターインターフェース"""

    @abstractmethod
    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        """Magiを実行し、イベントを非同期にyieldする"""
        pass
        yield {}


class MockMagiAdapter(MagiAdapter):
    """WebUI開発用のモックアダプター"""

    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "log", "lines": ["MOCKセッションを開始します..."], "level": "INFO"}
        yield {"type": "phase", "phase": "THINKING"}
        yield {"type": "progress", "pct": 10}
        await asyncio.sleep(1)
        yield {"type": "progress", "pct": 100}
        yield {
            "type": "final", "decision": "APPROVE",
            "votes": {"MELCHIOR-1": {"vote": "YES", "reason": "Mock"}},
            "summary": "Mock Result"
        }


class ConsensusEngineMagiAdapter(MagiAdapter):
    """ConsensusEngineを直接呼び出すアダプター"""

    def __init__(
        self,
        config: Config,
        llm_client_factory: Optional[Callable] = None,
        engine_factory: Optional[Callable[..., ConsensusEngine]] = None,
        provider_factory: Optional[ProviderAdapterFactory] = None,
    ):
        self.config = config
        self.llm_client_factory = llm_client_factory
        self.engine_factory = engine_factory or ConsensusEngine
        self.provider_factory = provider_factory or ProviderAdapterFactory()

    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        run_config = copy.deepcopy(self.config)
        run_config.template_base_path = str(Path("/app/templates").absolute())

        api_keys = getattr(options, "api_keys", {}) or {}
        unit_configs = getattr(options, "unit_configs", None)

        # 1. プロバイダ Registry の再構築
        # UIからの入力を反映し、既存の(不完全な)設定を上書きする
        provider_loader = ProviderConfigLoader()
        whitelist = getattr(run_config, "whitelist_providers", None) or ["anthropic", "openai", "google", "groq", "openrouter"]
        p_configs = provider_loader.load(whitelist_providers=whitelist, skip_validation=True)

        from magi.config.provider import ProviderConfig

        # 有効なAPIキーを持つプロバイダを追跡する
        _PLACEHOLDER_KEYS = {"none", "", "sk-ant-dummy-key"}

        for pid in whitelist:
            pl = pid.lower()
            ui_key = api_keys.get(pl) or api_keys.get(pid)

            # UIで明示的に鍵が入力されている場合は、その設定を最優先で作成
            if ui_key and ui_key.strip() and ui_key.strip() not in _PLACEHOLDER_KEYS:
                p_configs.providers[pl] = ProviderConfig(
                    provider_id=pl,
                    api_key=ui_key.strip(),
                    model="default-model"
                )
            elif pl not in p_configs.providers:
                # 鍵がない場合でも Registry で蹴られないようにプレースホルダを置く
                p_configs.providers[pl] = ProviderConfig(
                    provider_id=pl,
                    api_key="none",
                    model="none"
                )

        # 互換性同期 (環境変数等の鍵を anthropic に反映)
        if run_config.api_key and "anthropic" in p_configs.providers:
            if p_configs.providers["anthropic"].api_key in _PLACEHOLDER_KEYS:
                p_configs.providers["anthropic"].api_key = run_config.api_key.strip()

        # 有効なキーを持つプロバイダを特定（ユニットのフォールバック用）
        valid_providers = {
            pl: cfg for pl, cfg in p_configs.providers.items()
            if cfg.api_key and cfg.api_key.strip() not in _PLACEHOLDER_KEYS
        }

        registry = ProviderRegistry(p_configs)

        # デフォルトプロバイダを有効なキーを持つプロバイダから選択する
        default_pid = p_configs.default_provider
        if unit_configs and "melchior" in unit_configs:
            melchior_pid = (unit_configs["melchior"].get("provider") or "").lower()
            # Melchior のプロバイダが有効な場合はそれを使う、そうでなければ有効なプロバイダにフォールバック
            if melchior_pid and melchior_pid in valid_providers:
                default_pid = melchior_pid
            elif valid_providers:
                default_pid = next(iter(valid_providers))

        # デフォルトプロバイダ自体が有効でない場合もフォールバック
        if default_pid not in valid_providers and valid_providers:
            default_pid = next(iter(valid_providers))

        selector = ProviderSelector(registry, default_provider=default_pid)

        # 2. 各ユニットの設定を構築
        if unit_configs:
            from magi.config.settings import PersonaConfig, LLMConfig
            for unit_key, cfg in unit_configs.items():
                p_type = self._map_unit_to_persona(unit_key)
                if not p_type: continue

                original_pid = (cfg.get("provider") or "").lower()
                pid = original_pid
                raw_model = cfg.get("model") or "default"

                # プロバイダの指定があり、かつそれがホワイトリストに含まれていない場合、
                # あるいは指定がない場合にのみ、有効なプロバイダにフォールバック
                if not pid or pid not in [p.lower() for p in whitelist]:
                    if valid_providers:
                        fallback_pid = next(iter(valid_providers))
                        logger.warning(
                            "Unit %s: provider '%s' is not in whitelist or not specified, falling back to '%s'",
                            unit_key, pid, fallback_pid,
                        )
                        pid = fallback_pid

                # モデル名の構築
                if pid:
                    if pid == "openrouter":
                        # OpenRouter はモデルIDに必ずプレフィックスを付ける
                        if raw_model.startswith("openrouter/"):
                            model_name = raw_model
                        else:
                            model_name = f"openrouter/{raw_model}"
                    else:
                        # 非OpenRouterプロバイダ: 従来通りプレフィックスを付与
                        if not raw_model.startswith(f"{pid}/"):
                            model_name = f"{pid}/{raw_model}"
                        else:
                            model_name = raw_model
                else:
                    model_name = raw_model

                logger.info("Unit %s: Final Selection -> provider=%s, model=%s", unit_key, pid, model_name)

                unit_api_key = cfg.get("apiKey") or api_keys.get(f"{unit_key}_override")
                
                # APIキーの存在チェック
                # 1. システム設定(valid_providers)にあるか
                # 2. ユニット固有のOverride(unit_api_key)があるか
                has_system_key = pid in valid_providers
                has_override_key = unit_api_key and unit_api_key.strip() and unit_api_key.strip() not in _PLACEHOLDER_KEYS
                
                if not has_system_key and not has_override_key:
                    raise RuntimeError(
                        f"Unit {unit_key}: Provider '{pid}' requires an API key. "
                        f"Please set it in System Settings or provide an Override key for this unit."
                    )

                run_config.personas[p_type.value] = PersonaConfig(
                    llm=LLMConfig(
                        model=model_name,
                        temperature=cfg.get("temp"),
                        api_key=unit_api_key if has_override_key else None
                    )
                )

        # 3. エンジンの起動 (レガシーフォールバックを完全に遮断)
        def strict_factory():
            # ここに来るということは、ProviderSelector がアダプタを見つけられなかったということ
            raise RuntimeError("LLM provider resolution failed. Please check if the provider/model string matches registered providers.")

        try:
            logger.info("Initializing ConsensusEngine with forced adapter selection")
            engine = self.engine_factory(
                config=run_config,
                llm_client_factory=self.llm_client_factory or strict_factory,
                provider_selector=selector,
                provider_factory=self.provider_factory,
                streaming_emitter=None
            )

            # ペルソナプロンプト上書き
            if unit_configs:
                for unit_key, cfg in unit_configs.items():
                    p_type = self._map_unit_to_persona(unit_key)
                    if not p_type: continue
                    persona = engine.persona_manager.get_persona(p_type)
                    if persona: persona.override_prompt = cfg.get("persona")

            yield {"type": "phase", "phase": "THINKING"}
            yield {"type": "progress", "pct": 10}

            sent_final_progress = False
            async for event in engine.run_stream(prompt, plugin=options.plugin, attachments=options.attachments):
                if event["type"] == "stream":
                    u_type = self._map_persona_to_unit(event["persona"])
                    if u_type:
                        yield {
                            "type": "unit", "unit": u_type.value,
                            "state": self._map_phase_to_unit_state(event["phase"]).value,
                            "message": event["content"], "stream": True
                        }
                elif event["type"] == "event":
                    payload = event["payload"]
                    if event["event_type"] == "phase.transition":
                        p_val = str(payload.get("phase", "")).upper()
                        # COMPLETED はフロントエンドでは RESOLVED として扱う
                        if p_val == "COMPLETED":
                            p_val = "RESOLVED"
                        
                        yield {"type": "phase", "phase": p_val}
                        if "THINKING" in p_val: yield {"type": "progress", "pct": 10}
                        elif "DEBATE" in p_val: yield {"type": "progress", "pct": 40}
                        elif "VOTING" in p_val: yield {"type": "progress", "pct": 80}
                        elif "RESOLVED" in p_val and not sent_final_progress:
                            yield {"type": "progress", "pct": 100}
                            sent_final_progress = True
                elif event["type"] == "result":
                    if not sent_final_progress:
                        yield {"type": "progress", "pct": 100}
                        sent_final_progress = True
                    yield self._build_final_payload(event["data"])

        except Exception as e:
            logger.exception("ConsensusEngine failed")
            # 詳細なエラーメッセージをフロントエンドに返す
            error_msg = str(e)
            if "AuthenticationError" in error_msg or "401" in error_msg:
                error_msg = f"LLM Authentication Failed: Please check your API keys for the selected provider. ({error_msg})"
            yield {"type": "error", "code": "MAGI_CORE_ERROR", "message": error_msg}

    def _map_unit_to_persona(self, unit_key: str) -> Optional[PersonaType]:
        k = unit_key.lower()
        if "melchior" in k: return PersonaType.MELCHIOR
        if "balthasar" in k: return PersonaType.BALTHASAR
        if "casper" in k: return PersonaType.CASPER
        return None

    def _map_persona_to_unit(self, persona: Any) -> Optional[UnitType]:
        v = persona.value if hasattr(persona, "value") else str(persona)
        if v == PersonaType.MELCHIOR.value: return UnitType.MELCHIOR
        if v == PersonaType.BALTHASAR.value: return UnitType.BALTHASAR
        if v == PersonaType.CASPER.value: return UnitType.CASPER
        return None

    def _map_phase_to_unit_state(self, phase: Any) -> UnitState:
        v = phase.value if hasattr(phase, "value") else str(phase)
        if v == ConsensusPhase.THINKING.value: return UnitState.THINKING
        if v == ConsensusPhase.DEBATE.value: return UnitState.DEBATING
        if v == ConsensusPhase.VOTING.value: return UnitState.VOTING
        return UnitState.IDLE

    def _build_final_payload(self, result: ConsensusResult) -> Dict[str, Any]:
        d_map = {Decision.APPROVED: "APPROVE", Decision.DENIED: "DENY", Decision.CONDITIONAL: "CONDITIONAL"}
        v_map = {Vote.APPROVE: "YES", Vote.DENY: "NO", Vote.CONDITIONAL: "ABSTAIN"}
        v_res = {}
        for p, vo in result.voting_results.items():
            u = self._map_persona_to_unit(p)
            if u:
                vv = v_map.get(vo.vote, "ABSTAIN")
                v_res[u.value] = {"vote": vv, "reason": vo.reason}
        return {
            "type": "final", "decision": d_map.get(result.final_decision, "DENY"),
            "votes": v_res, "summary": f"Final Decision: {d_map.get(result.final_decision, 'DENY')}",
            "result": {"decision": d_map.get(result.final_decision, "DENY"), "voting_results": v_res, "exit_code": result.exit_code}
        }
