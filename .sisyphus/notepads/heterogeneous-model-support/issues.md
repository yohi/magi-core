# Issues

## `_create_agents` のリファクタリングに伴うテストへの影響調査結果 (2026-01-30)

`_create_agents` が `LLMClient` をペルソナ別に生成するように変更されることで、以下のテストに影響が出ることが判明した。

### 1. 直接的な破損が予想されるテスト
- **ファイル**: `/home/y_ohi/program/magi-core/tests/unit/test_consensus.py`
- **テスト名**: `test_create_agents_uses_injected_llm_client_factory`
- **原因**: 
  - 現在、`llm_client_factory` の呼び出し回数 (`factory_calls`) が `1` であることを期待している (`self.assertEqual(factory_calls, 1)`)。
  - ペルソナ別に生成する場合、この回数は `3` に増加するため、アサーションが失敗する。
  - また、`factory` のシグネチャに `PersonaType` が追加された場合、呼び出し側での引数不足エラーが発生する。

### 2. モック/パッチの修正が必要な箇所
- **ファイル**: `/home/y_ohi/program/magi-core/tests/unit/test_consensus.py` 内の `TestConsensusEngineAgentCreation`
- **影響**: `with patch('magi.core.consensus.LLMClient'):` を使用している箇所では、呼び出し回数に応じた戻り値の設定が必要になる可能性がある。

### 3. 修正方針案
#### 最小差分案
- `llm_client_factory` のインターフェースは維持（引数なし）し、`_create_agents` のループ内で呼び出すように変更。
- テストの期待値を `1` から `3` に修正する。

#### 望ましい設計案
- `llm_client_factory` に `PersonaType` を引数として渡すように変更。
- テストコードにおいて、各ペルソナに対して正しくファクトリが呼ばれたか（`call_args_list` 等で）検証するように更新する。

### 4. 追加すべきテスト観点
- `PersonaType` ごとに異なる設定（モデル名、APIキー等）が正しく `LLMClient` に反映されているかの検証。
### 5. 整理作業 (2026-01-30)
- 不要ファイル `verify_step1.py` を削除。Step 2 実装に向けた環境整理。

## `_create_agents` のリファクタリングに伴う影響調査詳細 (2026-01-30)

### 1. 影響を受けるファイル
- **`src/magi/core/consensus.py`**: 
  - `_create_agents` 内で `llm_client_factory` を呼び出す回数が1回から3回に増える。
  - `_resolve_llm_client` が `LLMClient` を直接インスタンス化しており、注入されたファクトリ（テスト用Fake等）を無視する可能性がある。
- **`src/magi/cli/main.py`**:
  - `_run_ask_command` 内で `lambda: llm_client` を渡しており、単一インスタンスの注入に固定されている。
- **`tests/unit/test_consensus.py`**:
  - `test_create_agents_uses_injected_llm_client_factory` (369行目) が呼び出し回数不一致で失敗する。
- **`tests/unit/test_consensus_di_mocks.py`**, **`tests/unit/test_consensus_schema_retry.py`**, **`tests/unit/test_quorum_streaming.py`**:
  - `llm_client_factory=lambda: FakeLLMClient()` というシグネチャを使用しており、ファクトリに引数が追加された場合に破損する。

### 2. 懸念事項
- **ファクトリと直接生成の混在**: `_resolve_llm_client` 内で `PersonaConfig` がある場合に `LLMClient(...)` を直接呼んでいるが、テスト時にこれらを Fake に差し替える仕組みが必要。ファクトリ自体を `persona_type` 引数対応にするのがクリーン。
- **CLIの単一プロバイダ前提**: 現在の CLI は 1 つのプロバイダを選択してエンジンに渡す構造になっており、`config.personas` による多種モデル利用と CLI でのプロバイダ指定（`--provider`）の優先順位を整理する必要がある。

### 3. テストの仮定
- 多くのテストで「全エージェントが同一の `llm_client` インスタンスを共有している」ことを前提にモック検証を行っている。個別のインスタンスになると、`mock_client.send.assert_called()` の回数集計などが変わる。

## テスト追従 (2026-01-30)

`tests/unit/test_consensus.py` に対して、`_create_agents` の仕様変更に伴う以下の修正とテスト追加を実施し、全てのテストが通過することを確認した。

1. **既存テストの修正**:
  - `test_create_agents_uses_injected_llm_client_factory`: `llm_client_factory` の呼び出し回数の期待値を `1` から `3` に変更。
2. **新規テストの追加**:
  - `test_create_agents_uses_persona_specific_config`: `config.personas` に設定がある場合、モデル名やAPIキーがペルソナ固有の設定で上書きされること、および設定がない場合はデフォルト値にフォールバックすることを確認。
  - `test_create_agents_passes_concurrency_controller`: `ConsensusEngine` に渡された `concurrency_controller` が、生成される `LLMClient` に正しく引き継がれていることを確認。

## テスト修正 (2026-01-30)

- `tests/unit/test_consensus_schema_retry.py` および `tests/unit/test_quorum_streaming.py` の相対インポートが `unittest discover` 実行時に失敗する問題を解決するため、try-except によるフォールバックインポートを実装。これにより、ファイルを直接実行する場合と discover 経由で実行する場合の両方に対応した。


## Git 状態の棚卸しと整理 (2026-01-30)

Step 2 の実装完了に伴い、現在の git 状態を棚卸しした。

### 1. 意図しない/無関係な変更 (分離・差し戻し推奨)
- **`.serena/project.yml`**: Serena プロジェクトの設定項目（`base_modes`, `default_modes`, `fixed_tools`）が追加されている。これらは機能開発とは無関係。
- **`AGENTS.md`**: 言語ポリシーや技術標準、コードスタイルガイドラインが大幅に追記されている。プロジェクト全体の設定変更であり、本機能のコミットに含めるべきではない。

### 2. 機能に関連する変更 (コミット対象)
- **`src/magi/config/settings.py`**: `LLMConfig`, `PersonaConfig` クラス追加、`MagiSettings` への `personas` フィールド追加。
- **`src/magi/core/consensus.py`**: `_resolve_llm_client` 実装によるペルソナ別モデル解決。
- **`README.md`**: 設定例の追記。
- **`docs/configuration_migration.md`**: 環境変数指定方法の追記。
- **`tests/unit/test_consensus.py`**: ペルソナ固有設定の検証テスト。
- **`tests/unit/test_consensus_schema_retry.py`, `tests/unit/test_quorum_streaming.py`**: インポートエラー回避のための try-except 処理。

### 3. 未追跡ファイルの分類
- **`.sisyphus/`**: コミット対象。プロジェクト管理・計画データ。
- **`spec.md`**: コミット対象。本機能の仕様定義。

### 4. セキュリティ・ hygiene 確認
- `api_key` 等の機密情報のハードコードは検出されなかった。
- `.env` 等の無視すべきファイルが追跡対象に含まれていないことを確認。

## Issues (Temperature Configuration Support)

### Mocking Instance Attributes
- **Problem**: `unittest.mock.MagicMock(spec=Class)` does not automatically populate instance attributes defined in `__init__` if they are not also defined as class attributes.
- **Impact**: Tests accessing `self.llm_client.temperature` failed with `AttributeError` even though `spec=LLMClient` was used.
- **Workaround**: Manually set `mock_client.temperature = 0.7` in tests.
- **Future Consideration**: Use `autospec=True` or ensure all instance attributes are type-hinted at the class level if possible/idiomatic, though manual setting is safe and explicit.
