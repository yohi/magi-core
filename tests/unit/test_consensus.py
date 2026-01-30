"""ConsensusEngineのユニットテスト

Requirements:
    - 4.1: ユーザーがプロンプトを入力すると3つのエージェントに対して独立した思考生成を要求
    - 4.3: 全エージェントが思考を完了すると3つの独立した思考結果を収集し次のフェーズに進む
    - 5.3: 設定されたラウンド数に達するとDebate Phaseを終了しVoting Phaseに移行
    - 6.1: Voting PhaseでAPPROVE、DENY、CONDITIONALのいずれかの投票を要求
    - 6.2: 全エージェントが投票を完了すると投票結果を集計し最終判定を決定
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from magi.core.concurrency import ConcurrencyLimitError, ConcurrencyMetrics
from magi.core.consensus import ConsensusEngine, ConsensusEngineFactory
from magi.core.context import ContextManager
from magi.core.streaming import NullStreamingEmitter
from magi.core.token_budget import TokenBudgetManager
from magi.agents.persona import PersonaManager
from magi.agents.agent import Agent
from magi.config.manager import Config
from magi.config.settings import PersonaConfig, LLMConfig
from magi.errors import MagiException
from magi.security.guardrails import GuardrailsAdapter, GuardrailsResult
from magi.models import (
    ConsensusPhase,
    ConsensusResult,
    ThinkingOutput,
    DebateOutput,
    DebateRound,
    VoteOutput,
    Vote,
    Decision,
    PersonaType,
)


class _StubConcurrencyController:
    """テスト用のシンプルな ConcurrencyController スタブ."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []

    @asynccontextmanager
    async def acquire(self, timeout=None):
        self.calls.append(timeout)
        if self.fail:
            raise ConcurrencyLimitError("acquire failed in stub")
        yield

    def get_metrics(self) -> ConcurrencyMetrics:
        return ConcurrencyMetrics(
            active_count=0,
            waiting_count=0,
            total_acquired=len(self.calls),
            total_timeouts=1 if self.fail else 0,
            total_rate_limits=0,
        )


class _SanitizingGuardrailsAdapter:
    """サニタイズ結果を返すガードレールモック."""

    def __init__(self, sanitized: str = "sanitized-input") -> None:
        self.sanitized = sanitized
        self.calls: list[str] = []

    async def check(self, prompt: str) -> GuardrailsResult:
        self.calls.append(prompt)
        return GuardrailsResult(
            blocked=False,
            reason="sanitize",
            provider="sanitizer",
            failure=None,
            fail_open=False,
            metadata={"original": prompt},
            sanitized_prompt=self.sanitized,
        )


class TestConsensusEngineInit(unittest.TestCase):
    """ConsensusEngineの初期化テスト"""

    def test_init_with_config(self):
        """Configを指定して初期化できることを確認"""
        config = Config(
            api_key="test-api-key",
            debate_rounds=2,
            voting_threshold="unanimous"
        )

        engine = ConsensusEngine(config)

        self.assertIsInstance(engine.persona_manager, PersonaManager)
        self.assertIsInstance(engine.context_manager, ContextManager)
        self.assertEqual(engine.current_phase, ConsensusPhase.THINKING)
        self.assertEqual(engine.config.debate_rounds, 2)
        self.assertEqual(engine.config.voting_threshold, "unanimous")

    def test_initial_phase_is_thinking(self):
        """初期フェーズがTHINKINGであることを確認"""
        config = Config(api_key="test-api-key")
        engine = ConsensusEngine(config)

        self.assertEqual(engine.current_phase, ConsensusPhase.THINKING)


class TestConsensusEnginePhaseTransition(unittest.TestCase):
    """フェーズ遷移のテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(
            api_key="test-api-key",
            debate_rounds=1,
            voting_threshold="majority"
        )
        self.engine = ConsensusEngine(self.config)

    def test_transition_from_thinking_to_debate(self):
        """THINKINGからDEBATEへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.THINKING
        self.engine._transition_to_phase(ConsensusPhase.DEBATE)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.DEBATE)

    def test_transition_from_debate_to_voting(self):
        """DEBATEからVOTINGへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.DEBATE
        self.engine._transition_to_phase(ConsensusPhase.VOTING)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.VOTING)

    def test_transition_from_voting_to_completed(self):
        """VOTINGからCOMPLETEDへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.VOTING
        self.engine._transition_to_phase(ConsensusPhase.COMPLETED)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.COMPLETED)


class TestConsensusEventContext(unittest.TestCase):
    """イベントにプロバイダ情報を含めるテスト"""

    def test_record_event_includes_provider_context(self):
        """event_context がイベントにマージされる"""
        config = Config(api_key="test")
        engine = ConsensusEngine(
            config,
            event_context={
                "provider": "openai",
                "missing_fields": ["api_key"],
                "auth_error": "invalid",
            },
        )

        engine._record_event("unit.test", foo="bar")

        event = engine.events[-1]
        self.assertEqual(event["type"], "unit.test")
        self.assertEqual(event["provider"], "openai")
        self.assertEqual(event["missing_fields"], ["api_key"])
        self.assertEqual(event["auth_error"], "invalid")
        self.assertEqual(event["foo"], "bar")

    def test_payload_overrides_context(self):
        """payload の provider が event_context より優先される"""
        config = Config(api_key="test")
        engine = ConsensusEngine(
            config,
            event_context={"provider": "default"},
        )

        engine._record_event("unit.override", provider="override")

        event = engine.events[-1]
        self.assertEqual(event["provider"], "override")


class TestThinkingPhase(unittest.TestCase):
    """Thinking Phaseのテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(api_key="test-api-key")
        self.engine = ConsensusEngine(self.config)

    def test_thinking_phase_calls_all_agents(self):
        """Thinking Phaseで3つのエージェント全てが呼び出されることを確認

        Requirements 4.1: 3つのエージェントに対して独立した思考生成を要求
        """
        # モックの設定
        mock_thinking_output = ThinkingOutput(
            persona_type=PersonaType.MELCHIOR,
            content="テスト思考内容",
            timestamp=datetime.now()
        )

        with patch.object(
            self.engine,
            '_create_agents',
            return_value={
                PersonaType.MELCHIOR: MagicMock(
                    think=AsyncMock(return_value=mock_thinking_output)
                ),
                PersonaType.BALTHASAR: MagicMock(
                    think=AsyncMock(return_value=ThinkingOutput(
                        persona_type=PersonaType.BALTHASAR,
                        content="BALTHASAR思考",
                        timestamp=datetime.now()
                    ))
                ),
                PersonaType.CASPER: MagicMock(
                    think=AsyncMock(return_value=ThinkingOutput(
                        persona_type=PersonaType.CASPER,
                        content="CASPER思考",
                        timestamp=datetime.now()
                    ))
                ),
            }
        ):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            self.assertEqual(len(result), 3)
            self.assertIn(PersonaType.MELCHIOR, result)
            self.assertIn(PersonaType.BALTHASAR, result)
            self.assertIn(PersonaType.CASPER, result)

    def test_thinking_phase_returns_independent_outputs(self):
        """Thinking Phaseが各エージェントの独立した出力を返すことを確認

        Requirements 4.2: 各エージェントが他のエージェントの出力を参照できない状態で思考を生成
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="MELCHIOR独立思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="BALTHASAR独立思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="CASPER独立思考",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # 各エージェントのthinkメソッドが同じプロンプトで呼ばれていることを確認
            for agent in mock_agents.values():
                agent.think.assert_called_once_with("テストプロンプト", attachments=None)

    def test_thinking_phase_transitions_to_debate(self):
        """Thinking Phase完了後にDEBATEフェーズに遷移することを確認

        Requirements 4.3: 全エージェントが思考を完了すると次のフェーズに進む
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            self.assertEqual(self.engine.current_phase, ConsensusPhase.THINKING)

            asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # Thinking Phase実行後、フェーズがDEBATEに遷移していることを確認
            self.assertEqual(self.engine.current_phase, ConsensusPhase.DEBATE)

    def test_thinking_phase_continues_on_agent_failure(self):
        """エージェントが失敗しても他のエージェントの処理が継続されることを確認

        Requirements 4.4: エージェントの思考生成が失敗した場合、
        エラーを記録し残りのエージェントの処理を継続する
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(side_effect=Exception("MELCHIOR失敗"))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="BALTHASAR成功",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="CASPER成功",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # 失敗したエージェント以外の結果が返されることを確認
            self.assertEqual(len(result), 2)
            self.assertIn(PersonaType.BALTHASAR, result)
            self.assertIn(PersonaType.CASPER, result)
            self.assertNotIn(PersonaType.MELCHIOR, result)


class TestConsensusEngineAgentCreation(unittest.TestCase):
    """エージェント作成のテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(api_key="test-api-key")
        self.engine = ConsensusEngine(self.config)

    def test_create_agents_returns_three_agents(self):
        """3つのエージェントが作成されることを確認"""
        with patch('magi.core.consensus.LLMClient'):
            agents = self.engine._create_agents()

            self.assertEqual(len(agents), 3)
            self.assertIn(PersonaType.MELCHIOR, agents)
            self.assertIn(PersonaType.BALTHASAR, agents)
            self.assertIn(PersonaType.CASPER, agents)

    def test_create_agents_with_correct_personas(self):
        """各エージェントが正しいペルソナで作成されることを確認"""
        with patch('magi.core.consensus.LLMClient'):
            agents = self.engine._create_agents()

            for persona_type, agent in agents.items():
                self.assertIsInstance(agent, Agent)
                self.assertEqual(agent.persona.type, persona_type)

    def test_create_agents_uses_injected_llm_client_factory(self):
        """注入されたLLMクライアントファクトリが利用されることを確認"""
        factory_calls = 0
        injected_client = MagicMock()

        def factory():
            nonlocal factory_calls
            factory_calls += 1
            return injected_client

        engine = ConsensusEngine(self.config, llm_client_factory=factory)
        agents = engine._create_agents()

        # 各ペルソナごとに呼ばれるため3回
        self.assertEqual(factory_calls, 3)
        for agent in agents.values():
            self.assertIs(agent.llm_client, injected_client)

    def test_create_agents_uses_persona_specific_config(self):
        """ペルソナごとの設定が反映されることを確認"""
        config = Config(
            api_key="default-key",
            model="default-model",
            personas={
                "melchior": PersonaConfig(
                    llm=LLMConfig(
                        model="melchior-model",
                        api_key="melchior-key"
                    )
                )
            }
        )
        engine = ConsensusEngine(config)
        
        # 実際のLLMClient生成をモック化せず、属性をチェックしたいが、
        # 外部通信を防ぐためにLLMClientのコンストラクタをパッチする
        with patch('magi.core.consensus.LLMClient') as mock_llm_cls:
            agents = engine._create_agents()
            
            # MELCHIORの設定確認
            melchior_call = [
                call for call in mock_llm_cls.call_args_list 
                if call.kwargs.get('api_key') == 'melchior-key'
            ]
            self.assertEqual(len(melchior_call), 1)
            self.assertEqual(melchior_call[0].kwargs['model'], 'melchior-model')
            
            # 他のペルソナのフォールバック確認（デフォルト値が使われる）
            default_calls = [
                call for call in mock_llm_cls.call_args_list 
                if call.kwargs.get('api_key') == 'default-key'
            ]
            self.assertEqual(len(default_calls), 2)
            self.assertEqual(default_calls[0].kwargs['model'], 'default-model')

    def test_create_agents_passes_concurrency_controller(self):
        """ConcurrencyControllerが正しく渡されることを確認"""
        controller = _StubConcurrencyController()
        engine = ConsensusEngine(self.config, concurrency_controller=controller)
        
        with patch('magi.core.consensus.LLMClient') as mock_llm_cls:
            engine._create_agents()
            
            for call in mock_llm_cls.call_args_list:
                self.assertIs(call.kwargs['concurrency_controller'], controller)



class TestConsensusTokenBudget(unittest.TestCase):
    """Voting前のトークン予算管理のテスト"""

    def setUp(self):
        self.config = Config(api_key="test-api-key", token_budget=50)
        self.engine = ConsensusEngine(self.config)

    def _mock_agents(self, vote_output: VoteOutput):
        return {
            PersonaType.MELCHIOR: MagicMock(
                vote=AsyncMock(return_value=vote_output)
            ),
            PersonaType.BALTHASAR: MagicMock(
                vote=AsyncMock(return_value=vote_output)
            ),
            PersonaType.CASPER: MagicMock(
                vote=AsyncMock(return_value=vote_output)
            ),
        }

    def test_over_budget_context_is_compressed_and_logged(self):
        """投票前コンテキストが予算超過なら圧縮されログが記録される"""
        long_context = "【Debate結果】\n" + ("詳細" * 400)
        vote_output = VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok"
        )

        with patch.object(
            self.engine, "_build_voting_context", return_value=long_context
        ), patch.object(
            self.engine, "_create_agents", return_value=self._mock_agents(vote_output)
        ):
            result = asyncio.run(
                self.engine._run_voting_phase({}, [])
            )

        self.assertTrue(result["summary_applied"])
        logs = self.engine.context_reduction_logs
        self.assertGreater(len(logs), 0)
        self.assertEqual(logs[0].phase, ConsensusPhase.VOTING.value)
        self.assertLess(logs[0].after_tokens, logs[0].before_tokens)
        # 予算を超えていないことを確認
        self.assertLessEqual(
            self.engine.token_budget_manager.estimate_tokens(result["context"]),
            self.config.token_budget
        )

    def test_under_budget_context_passes_through(self):
        """予算内なら要約せずそのまま渡す"""
        short_context = "短いコンテキスト"
        vote_output = VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok"
        )

        with patch.object(
            self.engine, "_build_voting_context", return_value=short_context
        ), patch.object(
            self.engine, "_create_agents", return_value=self._mock_agents(vote_output)
        ):
            result = asyncio.run(
                self.engine._run_voting_phase({}, [])
            )

        self.assertFalse(result["summary_applied"])
        self.assertEqual([], self.engine.context_reduction_logs)
        self.assertEqual(short_context, result["context"])


class TestConsensusConcurrencyIntegration(unittest.TestCase):
    """ConcurrencyController との統合テスト."""

    def test_thinking_phase_acquires_concurrency(self):
        """Thinking Phase が acquire を呼び出す."""
        controller = _StubConcurrencyController()
        config = Config(api_key="test-api-key")
        engine = ConsensusEngine(config, concurrency_controller=controller)
        thinking_output = ThinkingOutput(
            persona_type=PersonaType.MELCHIOR,
            content="ok",
            timestamp=datetime.now(),
        )
        agent = MagicMock(think=AsyncMock(return_value=thinking_output))

        with patch.object(
            engine,
            "_create_agents",
            return_value={PersonaType.MELCHIOR: agent},
        ):
            result = asyncio.run(engine._run_thinking_phase("hello"))

        self.assertEqual(len(controller.calls), 1)
        self.assertEqual(controller.calls[0], config.timeout)
        agent.think.assert_awaited_once()
        self.assertIn(PersonaType.MELCHIOR, result)
        self.assertEqual(result[PersonaType.MELCHIOR].content, "ok")

    def test_concurrency_timeout_is_handled(self):
        """ConcurrencyLimitError を捕捉して結果を欠落として扱う."""
        controller = _StubConcurrencyController(fail=True)
        engine = ConsensusEngine(
            Config(api_key="test-api-key"), concurrency_controller=controller
        )
        agent = MagicMock(think=AsyncMock())

        with patch.object(
            engine,
            "_create_agents",
            return_value={PersonaType.MELCHIOR: agent},
        ):
            result = asyncio.run(engine._run_thinking_phase("hello"))

        agent.think.assert_not_awaited()
        self.assertEqual(result, {})
        self.assertTrue(
            any(
                err.get("phase") == ConsensusPhase.THINKING.value
                for err in engine.errors
            )
        )


class TestConsensusEngineFactoryDI(unittest.TestCase):
    """ConsensusEngineFactory で依存を注入できることを確認するテスト."""

    def test_factory_allows_dependency_injection(self):
        """主要依存が工場経由で差し替えられる。"""
        config = Config(api_key="test-api-key")
        persona_manager = MagicMock()
        context_manager = MagicMock()
        guardrails_adapter = MagicMock(spec=GuardrailsAdapter)
        streaming_emitter = MagicMock()
        token_budget_manager = MagicMock(spec=TokenBudgetManager)
        llm_client = object()

        def llm_factory():
            return llm_client

        factory = ConsensusEngineFactory()
        engine = factory.create(
            config,
            persona_manager=persona_manager,
            context_manager=context_manager,
            llm_client_factory=llm_factory,
            guardrails_adapter=guardrails_adapter,
            streaming_emitter=streaming_emitter,
            token_budget_manager=token_budget_manager,
            concurrency_controller=_StubConcurrencyController(),
        )

        self.assertIs(engine.persona_manager, persona_manager)
        self.assertIs(engine.context_manager, context_manager)
        self.assertIs(engine.guardrails, guardrails_adapter)
        self.assertIs(engine.streaming_emitter, streaming_emitter)
        self.assertIs(engine.token_budget_manager, token_budget_manager)
        self.assertIs(engine.llm_client_factory, llm_factory)

    def test_factory_uses_defaults_when_dependencies_not_provided(self):
        """依存を渡さない場合はデフォルト実装が利用される。"""
        config = Config(api_key="test-api-key")
        engine = ConsensusEngineFactory().create(config)

        self.assertIsInstance(engine.persona_manager, PersonaManager)
        self.assertIsInstance(engine.context_manager, ContextManager)
        self.assertIsInstance(engine.guardrails, GuardrailsAdapter)
        self.assertIsInstance(engine.streaming_emitter, NullStreamingEmitter)
        self.assertIsInstance(engine.token_budget_manager, TokenBudgetManager)

    def test_factory_guardrails_sanitizes_before_security_filter(self):
        """工場経由のガードレールが SecurityFilter 前にサニタイズを適用する."""
        config = Config(api_key="test-api-key", enable_guardrails=True)
        adapter = _SanitizingGuardrailsAdapter(sanitized="cleaned")
        factory = ConsensusEngineFactory()
        engine = factory.create(config, guardrails_adapter=adapter)

        detection = MagicMock(blocked=False, matched_rules=[])
        with patch.object(
            engine.security_filter,
            "detect_abuse",
            return_value=detection,
        ) as detect_mock, patch.object(
            engine,
            "_run_thinking_phase",
            AsyncMock(return_value={}),
        ), patch.object(
            engine,
            "_run_debate_phase",
            AsyncMock(return_value=[]),
        ), patch.object(
            engine,
            "_run_voting_phase",
            AsyncMock(
                return_value={
                    "voting_results": {},
                    "decision": Decision.APPROVED,
                    "exit_code": 0,
                    "all_conditions": [],
                }
            ),
        ):
            asyncio.run(engine.execute("unsafe input"))

        self.assertEqual(adapter.calls, ["unsafe input"])
        detect_mock.assert_called_once_with("cleaned")


class TestConsensusSecurityFilter(unittest.TestCase):
    """SecurityFilterによる入力ブロックのテスト"""

    def setUp(self):
        self.engine = ConsensusEngine(Config(api_key="test-api-key"))

    def test_execute_raises_when_abuse_detected(self):
        """detect_abuseがブロックを返した場合にMagiExceptionを送出すること"""
        blocked_detection = MagicMock(blocked=True, matched_rules=["ruleX"])
        with patch.object(
            self.engine.security_filter,
            "detect_abuse",
            return_value=blocked_detection,
        ):
            with self.assertRaises(MagiException) as ctx:
                asyncio.run(self.engine.execute("forbidden input"))

        exc = ctx.exception
        self.assertEqual(
            "入力に禁止パターンが含まれているため処理を中断しました。",
            exc.error.message,
        )
        self.assertEqual(["ruleX"], exc.error.details["rules"])


class TestConsensusEngineTemperatureResolution(unittest.TestCase):
    """温度パラメータ解決のテスト"""

    def test_default_temperature_used(self):
        """デフォルトで設定値のtemperatureが使用される"""
        config = Config(api_key="test-key", temperature=0.7)
        engine = ConsensusEngine(config)

        with patch('magi.core.consensus.LLMClient') as mock_llm_cls:
            engine._create_agents()

            for call in mock_llm_cls.call_args_list:
                self.assertEqual(call.kwargs['temperature'], 0.7)

    def test_global_temperature_override(self):
        """グローバル設定のtemperatureが反映される"""
        config = Config(api_key="test-key", temperature=0.5)
        engine = ConsensusEngine(config)

        with patch('magi.core.consensus.LLMClient') as mock_llm_cls:
            engine._create_agents()

            for call in mock_llm_cls.call_args_list:
                self.assertEqual(call.kwargs['temperature'], 0.5)

    def test_persona_temperature_override(self):
        """ペルソナごとのtemperature設定が優先される"""
        config = Config(
            api_key="test-key",
            temperature=0.7,
            personas={
                "melchior": PersonaConfig(
                    llm=LLMConfig(temperature=0.2)
                ),
                "casper": PersonaConfig(
                    llm=LLMConfig(temperature=0.9)
                )
            }
        )
        engine = ConsensusEngine(config)

        with patch('magi.core.consensus.LLMClient') as mock_llm_cls:
            engine._create_agents()
            
            temps = [call.kwargs['temperature'] for call in mock_llm_cls.call_args_list]
            self.assertIn(0.2, temps)
            self.assertIn(0.9, temps)
            self.assertIn(0.7, temps)

if __name__ == '__main__':
    unittest.main()
