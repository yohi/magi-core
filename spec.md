# ❖ MAGI SYSTEM DESIGN DOC: Heterogeneous Model Support ❖

## 1. 概要 (Overview)

現在のMAGIシステムは、全エージェントが単一の「グローバルLLM設定」を共有しています。これを改修し、**ペルソナごとの個別設定（Override）** を可能にします。設定は階層構造を持ち、個別設定がない場合はグローバル設定が適用されます（フォールバック機構）。

### 目的

* **適材適所:** 論理推論には高精度モデル、直感には高速モデルなど、役割に応じたモデル選定を可能にする。
* **コスト最適化:** 全てに最高級モデルを使うのではなく、重要度の低い工程には軽量モデルを使用可能にする。

## 2. アーキテクチャ設計 (Architecture)

### 2.1 設定スキーマの拡張 (`settings.py`)

`MagiSettings` クラスに、ペルソナごとの設定を保持する `personas` フィールドを追加します。Pydanticモデルのネスト構造を採用し、型安全性を確保します。

* **Global Level:** `api_key`, `model` (既存) - デフォルトとして機能
* **Persona Level:** `personas.{name}.llm` - 個別の上書き設定

### 2.2 エージェント生成ロジックの変更 (`consensus.py`)

`ConsensusEngine._create_agents` メソッドにおいて、単一の `LLMClient` を使い回すのではなく、ペルソナごとに設定を解決（Resolve）し、個別の `LLMClient` インスタンス（または設定適用済みのクライアント）を生成するように変更します。

---

## 3. 実装仕様書 (Specifications)

### 変更対象ファイル 1: `src/magi/config/settings.py`

Pydanticのモデル構造を追加し、設定ファイル（YAML/Env）からの読み込みに対応させます。

**変更点:**

1. `LLMConfig` クラス（モデル設定の部品）を定義。
2. `PersonaConfig` クラス（ペルソナ設定の部品）を定義。
3. `MagiSettings` に `personas: Dict[str, PersonaConfig]` フィールドを追加。

```python
# [追加] 必要なインポート
from pydantic import BaseModel

# [新規クラス] 個別のLLM設定
class LLMConfig(BaseModel):
    """LLM設定のオーバーライド用モデル"""
    api_key: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    temperature: Optional[float] = None

# [新規クラス] ペルソナごとの設定
class PersonaConfig(BaseModel):
    """ペルソナ個別設定"""
    llm: Optional[LLMConfig] = None

# [修正] MagiSettingsクラス
class MagiSettings(BaseSettings):
    # ... (既存フィールド) ...

    # [追加] ペルソナ設定 (key: melchior, balthasar, casper)
    personas: Dict[str, PersonaConfig] = Field(default_factory=dict)

    # ...

```

### 変更対象ファイル 2: `src/magi/core/consensus.py`

エージェント生成時に、設定の「解決（Resolution）」ロジックを実装します。

**ロジックフロー:**

1. ペルソナのキー（`melchior`等）で `config.personas` を検索。
2. 個別設定があれば取得、なければ `None`。
3. パラメータ（APIキー、モデル名等）ごとに、`個別設定 > グローバル設定` の優先順位で値を決定。
4. 決定したパラメータで `LLMClient` を初期化。

---

## 4. 作業手順 (Implementation Steps)

以下の手順でコードベースを修正してください。

### Step 1: `src/magi/config/settings.py` の修正

既存の `MagiSettings` クラス定義の前に、サブモデルを追加し、`MagiSettings` にフィールドを追加します。

```python
# src/magi/config/settings.py

# ... imports ...
from pydantic import BaseModel, Field, ValidationInfo, field_validator # BaseModelを追加
# ...

# --- [ADD START] ---
class LLMConfig(BaseModel):
    """LLM設定のオーバーライド用モデル"""
    model: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[int] = None
    retry_count: Optional[int] = None

class PersonaConfig(BaseModel):
    """ペルソナ個別設定"""
    llm: Optional[LLMConfig] = None
# --- [ADD END] ---

class MagiSettings(BaseSettings):
    # ... (既存のフィールド) ...

    # 出力設定
    output_format: Literal["json", "markdown"] = "markdown"

    # --- [ADD START] ---
    # ペルソナ別設定
    personas: Dict[str, PersonaConfig] = Field(default_factory=dict)
    # --- [ADD END] ---

    # ... (以降のメソッドはそのまま) ...

```

### Step 2: `src/magi/core/consensus.py` の修正

`_create_agents` メソッドを全面的に書き換えます。

```python
# src/magi/core/consensus.py

    # ... (既存メソッド) ...

    def _resolve_llm_config(self, persona_type: PersonaType) -> LLMClient:
        """ペルソナごとの設定を解決し、LLMClientを生成する"""
        # デフォルト値の取得
        target_model = self.config.model
        target_api_key = self.config.api_key
        target_timeout = self.config.timeout
        target_retry_count = self.config.retry_count
        
        # オーバーライドの確認
        persona_key = persona_type.name.lower() # melchior, balthasar, casper
        if self.config.personas and persona_key in self.config.personas:
            p_config = self.config.personas[persona_key]
            if p_config.llm:
                if p_config.llm.model:
                    target_model = p_config.llm.model
                if p_config.llm.api_key:
                    target_api_key = p_config.llm.api_key
                if p_config.llm.timeout:
                    target_timeout = p_config.llm.timeout
                if p_config.llm.retry_count:
                    target_retry_count = p_config.llm.retry_count

        # クライアントの生成
        # Note: 同時実行制御(concurrency_controller)はグローバルで共有する
        return LLMClient(
            api_key=target_api_key,
            model=target_model,
            timeout=target_timeout,
            retry_count=target_retry_count,
            concurrency_controller=self.concurrency_controller,
        )

    def _create_agents(self) -> Dict[PersonaType, Agent]:
        """3つのエージェントを作成 (Multi-Model対応)

        Returns:
            ペルソナタイプをキーとするAgentの辞書
        """
        agents = {}
        for persona_type in PersonaType:
            persona = self.persona_manager.get_persona(persona_type)
            
            # ペルソナごとに設定を解決してクライアントを生成
            llm_client = self._resolve_llm_config(persona_type)

            agents[persona_type] = Agent(
                persona,
                llm_client,
                schema_validator=self.schema_validator,
                template_loader=self.template_loader,
                security_filter=self.security_filter,
                token_budget_manager=self.token_budget_manager,
            )

        return agents

```

### Step 3: 設定ファイルの更新（動作確認用）

`magi.yaml` または `.env` で設定をテストします。

**magi.yaml の例:**

```yaml
api_key: "sk-global-key..."
model: "claude-3-5-sonnet-20240620" # デフォルト（Balthasar用など）

personas:
  melchior:
    llm:
      model: "gpt-4-turbo" # Melchiorは論理重視モデル
  casper:
    llm:
      model: "gpt-4o" # Casperは速度と直感重視
      # api_key: "sk-special-key..." # 必要ならキーも変更可

```

### 補足: 影響範囲の確認

* **後方互換性:** `personas` 設定がない場合、ロジックはグローバル設定を使用するため、既存の動作は保証されます。
* **テスト:** 既存のテスト `tests/unit/test_consensus.py` などが、ファクトリ経由ではなく `_create_agents` の内部ロジック変更の影響を受ける可能性があります。モックを使用している箇所で `LLMClient` の生成呼び出しが増えるため、期待するコール数を調整する必要があるかもしれません。
