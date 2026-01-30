# Learnings

## 2026-01-30 異種モデルサポート実装に向けた現状調査

### MagiSettings (src/magi/config/settings.py)
- Pydantic V2 (`pydantic-settings`) を使用している。
- 環境変数は `MAGI_` プレフィックスで読み込まれる。
- 設定ソースの優先順位は `env > dotenv > init > file_secret`。
- `_apply_legacy_keys` で後方互換性を処理している。
- 現状、LLM設定はトップレベルに `api_key`, `model`, `timeout`, `retry_count` として存在している。

### ConsensusEngine (src/magi/core/consensus.py)
- `_create_agents` メソッドで 3 つのエージェント（MELCHIOR, BALTHASAR, CASPER）を生成。
- 現状は `self.llm_client_factory()` を 1 回呼び出し、生成された単一の `LLMClient` インスタンスを全てのエージェントで共有している。
- `llm_client_factory` はデフォルトで `self.config` (MagiSettings) の値を参照して生成される。

### LLMClient (src/magi/llm/client.py)
- `AsyncAnthropic` をラップしており、インスタンスごとに `model` 名を保持している。
- 生成時に `api_key`, `model`, `timeout`, `retry_count` などを指定する。

### 変更方針（Step 1/2）
- **Step 1**: `MagiSettings` に `personas: Dict[PersonaType, Dict[str, Any]]` フィールドを追加。
    - 各ペルソナごとに `model`, `api_key` などをオーバーライド可能にする。
- **Step 2**: `ConsensusEngine._create_agents` を修正。
    - 各ペルソナのループ内で、個別に `LLMClient` を生成するように変更。
    - `self.config.personas` に設定があれば優先し、なければデフォルト値を使用する。

### 影響範囲
- `ConsensusEngine` の初期化引数 `llm_client_factory` を利用しているテスト（`tests/unit/test_consensus_di_mocks.py` 等）。
- エージェントごとに異なるクライアントを持つようになるため、モックの検証方法に変更が必要になる可能性がある。

## 2026-01-30 Pydantic v2 によるネスト設定（personas.{name}.llm）の実装ガイド

Pydantic v2 (`pydantic-settings`) を用いて、`personas.{name}.llm` のようなネストした設定を安全かつ柔軟に扱うための調査結果とベストプラクティスをまとめる。

### 2026-01-30 Pydantic v2 によるネスト設定（personas.{name}.llm）の実装
- `SettingsConfigDict` に `env_nested_delimiter='__'` を追加した。
- これにより、`MAGI_PERSONAS__melchior__llm__model=m2` 形式でペルソナ別の LLM 設定を環境変数から個別に指定可能になった。
- 既存の JSON 形式 `MAGI_PERSONAS='{"melchior": {"llm": {...}}}'` も引き続き動作する。
- 同一のペルソナ設定に対して JSON 形式と個別環境変数の両方が指定された場合、個別環境変数（ネスト形式）が優先される。
- dict キー（ペルソナ名）は既存の実装（小文字推奨）に従う。

### 1. Pydantic v2 (`pydantic-settings`) の基本構成

Pydantic v2 では、設定管理は別パッケージの `pydantic-settings` に分離された。ネストしたモデルを `BaseSettings` に持たせる際は、以下の構造が推奨される。

```python
from typing import Dict, Optional
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class LLMConfig(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    # 必要に応じて他のフィールドを追加

class PersonaConfig(BaseModel):
    llm: Optional[LLMConfig] = Field(default_factory=LLMConfig)

class MagiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAGI_",
        env_nested_delimiter="__",  # ネストした環境変数の区切り文字
        nested_model_default_partial_update=True, # デフォルト値に対する部分更新を許可
        extra="ignore"
    )

    # グローバル設定
    model: str = "claude-3-5-sonnet-latest"
    api_key: Optional[str] = None

    # ペルソナ別設定
    personas: Dict[str, PersonaConfig] = Field(default_factory=dict)
```

### 2. 環境変数によるネスト設定の指定方法

`env_nested_delimiter="__"` を設定することで、ネストした辞書やモデルの値を環境変数から個別に上書きできる。

- **書式**: `{PREFIX}{TOP_FIELD}{DELIMITER}{KEY}{DELIMITER}{SUB_FIELD}`
- **例**: `MAGI_PERSONAS__MELCHIOR__LLM__MODEL=claude-3-opus`
    - これは `settings.personas["MELCHIOR"].llm.model` にマッピングされる。
- **JSON形式**: `MAGI_PERSONAS='{"MELCHIOR": {"llm": {"model": "gpt-4"}}}'` のように、親フィールドに JSON 文字列を渡すことも可能。

### 3. YAML からの読み込みと Dict[str, PersonaConfig]

Pydantic は辞書形式のデータを `Dict[str, BaseModel]` に自動的にパースする。YAML を辞書として読み込み、`BaseSettings` の初期化時に渡せば、自然に `PersonaConfig` インスタンスの辞書が生成される。

```yaml
# magi.yaml
model: "claude-3-sonnet"
personas:
  MELCHIOR:
    llm:
      model: "claude-3-opus"
  BALTHASAR:
    llm:
      model: "claude-3-haiku"
```

### 4. Optional フィールドのフォールバック（マージ）実装

ペルソナ固有の設定がない場合にグローバル設定を参照する（フォールバック）ロジックは、`@model_validator(mode='after')` で実装するのがクリーンである。

```python
    @model_validator(mode='after')
    def resolve_persona_settings(self) -> "MagiSettings":
        for name, persona in self.personas.items():
            if persona.llm:
                # model が未設定ならグローバルの model を使用
                persona.llm.model = persona.llm.model or self.model
                # api_key も同様
                persona.llm.api_key = persona.llm.api_key or self.api_key
        return self
```

### 5. 注意点と Pydantic v1 との違い

- **パッケージ**: v1 は `pydantic` 本体に含まれていたが、v2 は `pydantic-settings` が必要。
- **Configクラス**: v1 の `class Config` は、v2 では `model_config = SettingsConfigDict(...)` に変更。
- **部分更新**: v2 では `nested_model_default_partial_update` フラグにより、デフォルトのオブジェクトに対して環境変数から一部のフィールドのみを更新する挙動を制御できる（v1 では挙動が不安定な場合があった）。
- **検証の厳密さ**: v2 の方が検証が高速かつ厳密。`Optional` の扱い（`None` を許容するかどうか）に注意が必要。

### 参考
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [pydantic-settings GitHub](https://github.com/pydantic/pydantic-settings)

## 2026-01-30 異種モデルサポート実装 Step 1 完了報告

### 実装内容
- `src/magi/config/settings.py` に以下のモデル定義を追加。
    - `LLMConfig`: 個別LLM設定（model, api_key, timeout, retry_count）
    - `PersonaConfig`: ペルソナ設定コンテナ（llmフィールドを持つ）
- `MagiSettings` に `personas: Dict[str, PersonaConfig]` フィールドを追加。

### 検証結果
- `unittest tests/unit/test_config.py` がパスし、既存の読み込み機能や後方互換性が維持されていることを確認。
- `verify_step1.py` による手動検証にて、`personas` フィールドへの dict 注入、オブジェクト注入、デフォルト値（空dict）の動作が正常であることを確認。

## Pydantic v2 BaseSettings における階層構造設定のベストプラクティス

### env_nested_delimiter の活用
- `env_nested_delimiter="__"` を使用することで、`PERSONAS__MELCHIOR__LLM__MODEL` のような環境変数から階層化された `BaseModel` や `Dict` を透過的に初期化できる。
- YAML形式の構造と環境変数を 1:1 で対応させやすく、特定のネストされた値のみを CI/CD 等で上書きする際に非常に強力。

### 注意すべき挙動
1. **優先順位**: 階層化された個別環境変数は、親要素の JSON 文字列環境変数よりも優先される。
2. **Dictのキー**: `Dict[str, Any]` 等で受ける場合、環境変数の大文字小文字がそのままキー名に影響を与える場合があるため、`case_sensitive` 設定の明示的な管理が推奨される。
3. **安全なデリミタ**: `api_key` などの単語内アンダースコアとの衝突を避けるため、`__` (ダブルアンダースコア) を区切り文字として使用するのが一般的。

### 公式リファレンス
- https://docs.pydantic.dev/latest/concepts/pydantic_settings/

## 2026-01-30 異種モデルサポート実装 Step 2 実装完了報告

### 実装内容
- `src/magi/core/consensus.py` を改修し、`_create_agents` でのエージェント生成ロジックを変更。
- これまでは単一の `LLMClient` を全エージェントで共有していたが、ペルソナごとに `_resolve_llm_client` メソッドを呼び出して解決するように変更。
- **`_resolve_llm_client` のロジック**:
    1. `config.personas` から該当ペルソナの設定（`PersonaConfig`）を取得。
    2. 設定が存在し、かつ `llm` フィールド（`LLMConfig`）が設定されている場合：
        - `api_key`, `model`, `timeout`, `retry_count` の各パラメータについて、オーバーライド設定があればそれを使用し、なければグローバル設定 (`self.config`) を使用する。
        - 新しい `LLMClient` インスタンスを生成して返す。
        - **重要**: `concurrency_controller` は `self.concurrency_controller` を渡して共有させることで、システム全体での同時実行数制限を維持する。
    3. 設定が存在しない場合：
        - 既存の `self.llm_client_factory()` を呼び出して返す（DI互換性の維持）。

### 考慮事項
- **後方互換性**: テストコードなどで `llm_client_factory` をモックに差し替えている場合でも、オーバーライド設定がなければそのモックが使用されるため、既存の挙動を破壊しない。
- **並行処理制御**: 異なる `LLMClient` インスタンス間でも `ConcurrencyController` を共有することで、異種モデル混在時でもリソース制御を一元管理できるようにした。

## 2026-01-30 異種モデルサポート実装 Step 3 ドキュメント更新完了

### ドキュメント更新内容
- `README.md` に `personas` の設定例を追加し、`melchior`/`balthasar`/`casper` のキー使用を推奨。
- `docs/configuration_migration.md` に `MAGI_PERSONAS` 環境変数の使用例（JSON文字列）を追記。

### 学び・気づき
- **設定例の重要性**: Pydantic v2 の `env_nested_delimiter` は強力だが、複雑なネスト構造を環境変数で表現するのは認知負荷が高い。ユーザー向けには YAML 設定を基本としつつ、環境変数は JSON 文字列での注入を案内するのが現実的な解であると判断した。
- **推奨キーの明示**: Enum 値 (`PersonaType.value`) と設定キーを一致させるため、ドキュメントレベルで推奨キー（小文字）を明示した。これにより、実装側での複雑なキー正規化ロジックを避けつつ、ユーザー体験を損なわないようにした。

## 2026-01-30 ドキュメント設定例の修正

### 背景
`README.md` と `docs/configuration_migration.md` に記載されていた `personas` の設定例が、実際の実装スキーマ（`PersonaConfig` が `llm` フィールドを持つネスト構造）と一致していなかった。また、実装されていない `temperature` パラメータが例に含まれていた。

### 対応内容
- `README.md` の YAML 例を修正し、`llm` ネストを追加し、パラメータを実在するもの（`timeout`など）に変更。
- `docs/configuration_migration.md` の JSON 環境変数例を同様に修正。
- ユーザーが混乱しないよう、未指定項目のフォールバック挙動（グローバル設定の使用）についての注釈を明記した。

### 学び
- 機能実装後のドキュメント更新において、Pydantic モデルの構造変更（特にネストの追加）が設定例に正確に反映されているか、実際のコードと見比べて確認するプロセスが重要。

## Learnings (Temperature Configuration Support)

### Pattern: Configuration Precedence
- **Pattern**: Persona > Global > Default
- **Implementation**: `ConsensusEngine._resolve_llm_client` handles this logic before creating `LLMClient`.
- **Learnings**: Storing the resolved configuration (like `temperature`) on the `LLMClient` instance is a clean way to pass context-specific settings to the consumer (`Agent`) without polluting the `Agent` constructor with config objects. The `Agent` simply uses `self.llm_client.temperature`.

### Backward Compatibility with Mocks
- **Issue**: Adding attributes to `LLMClient.__init__` and expecting them in `Agent` broke existing tests that used `MagicMock(spec=LLMClient)` or custom `FakeLLMClient`.
- **Solution**:
    - For `MagicMock(spec=LLMClient)`, explicitly set the new attribute (`mock.temperature = 0.7`) because `spec` only mocks *existing* attributes (and instance attributes set in `__init__` might not always be detected if not statically defined or if `spec` inspection is shallow).
    - For custom `FakeLLMClient`, update the class definition to match the new interface.
- **Takeaway**: When modifying core interfaces, assume strict test mocks will break and plan to update them.

## 2026-01-30 MAGI_PERSONAS (JSON) パースのテスト担保

### 設定のパース検証
- `MagiSettings` が `MAGI_PERSONAS` 環境変数に渡された JSON 文字列を、`Dict[str, PersonaConfig]` 型として正しくパースできることをユニットテスト (`tests/unit/test_magi_settings.py`) で担保した。
- `{"persona_name": {"llm": {"model": "...", "timeout": ...}}}` のようなネスト構造が、Pydantic の自動デシリアライズによって期待通りに `PersonaConfig` および `LLMConfig` オブジェクトに変換されることが確認された。これにより、環境変数経由での詳細なペルソナ設定の注入が技術的に保証された。
