import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ModelsFetcher:
    """
    models.dev からモデル定義を取得し、ホワイトリストでフィルタリングするクラス
    """
    
    SCHEMA_URL = "https://models.dev/model-schema.json"
    
    def __init__(self, config: Any):
        self.config = config
        self._cached_models: List[Dict[str, str]] = []
        self._last_fetch_time = 0

    async def fetch_models(self) -> List[Dict[str, str]]:
        """
        models.dev および OpenRouter API からモデル定義を取得し、
        設定されたホワイトリストに基づいてフィルタリングして返す
        """
        # ホワイトリストの取得
        whitelist = getattr(self.config, "whitelist_providers", None)
        if whitelist is None:
            # デフォルトのホワイトリスト
            whitelist = ["anthropic", "openai", "google", "groq", "openrouter", "flixa"]
        
        whitelist = [p.lower() for p in whitelist]
        models = []

        # 1. models.dev から取得
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.SCHEMA_URL)
                if response.status_code == 200:
                    schema = response.json()
                    enum_values = []
                    if isinstance(schema, dict):
                        if "$defs" in schema and "Model" in schema["$defs"] and "enum" in schema["$defs"]["Model"]:
                            enum_values = schema["$defs"]["Model"]["enum"]
                        elif "models" in schema:
                            enum_values = schema["models"]
                    
                    logger.info(f"Fetched {len(enum_values)} raw model strings from models.dev")
                    
                    for raw in enum_values:
                        if not isinstance(raw, str) or "/" not in raw:
                            continue
                        
                        slash_idx = raw.find("/")
                        provider = raw[:slash_idx].lower()
                        model_id = raw[slash_idx + 1:]
                        
                        if provider in whitelist:
                            models.append({
                                "id": model_id,
                                "provider": provider,
                                "name": model_id
                            })
        except Exception as e:
            logger.error(f"Failed to fetch models from {self.SCHEMA_URL}: {e}")

        # 2. OpenRouter API から取得 (ホワイトリストにある場合のみ)
        if "openrouter" in whitelist:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    or_response = await client.get("https://openrouter.ai/api/v1/models")
                    if or_response.status_code == 200:
                        or_data = or_response.json()
                        or_models = or_data.get("data", [])
                        logger.info(f"Fetched {len(or_models)} models from OpenRouter API")
                        for m in or_models:
                            m_id = m.get("id")
                            if m_id:
                                models.append({
                                    "id": m_id,
                                    "provider": "openrouter",
                                    "name": m.get("name", m_id)
                                })
            except Exception as e:
                logger.error(f"Failed to fetch models from OpenRouter API: {e}")

        # 3. Flixa API から取得 (ホワイトリストにある場合のみ)
        if "flixa" in whitelist:
            try:
                # 設定からエンドポイントを取得、なければデフォルト
                flixa_endpoint = getattr(self.config, "flixa", {}).get("endpoint") or "https://api.flixa.engineer/v1/agent"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    flixa_response = await client.get(f"{flixa_endpoint}/models")
                    if flixa_response.status_code == 200:
                        flixa_data = flixa_response.json()
                        flixa_models = flixa_data.get("data", [])
                        logger.info(f"Fetched {len(flixa_models)} models from Flixa API")
                        for m in flixa_models:
                            m_id = m.get("id")
                            if m_id:
                                models.append({
                                    "id": m_id,
                                    "provider": "flixa",
                                    "name": m.get("name", m_id)
                                })
            except Exception as e:
                logger.debug(f"Could not fetch models from Flixa API (expected if no API key): {e}")

        # 取得できたモデルがあればキャッシュを更新
        if models:
            self._cached_models = models
            return models
        else:
            return self._get_fallback_models(whitelist)

    def _get_fallback_models(self, whitelist: List[str]) -> List[Dict[str, str]]:
        """フォールバックモデルリストを返す"""
        fallbacks = [
            {"id": "claude-sonnet-4.5", "provider": "anthropic", "name": "Claude 3.5 Sonnet (Fallback)"},
            {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "name": "Claude 3.5 Sonnet (20241022)"},
            {"id": "gpt-4o", "provider": "openai", "name": "GPT-4o (Fallback)"},
            {"id": "gpt-4o", "provider": "flixa", "name": "Flixa GPT-4o (Fallback)"},
            {"id": "gemini-1.5-pro", "provider": "google", "name": "Gemini 1.5 Pro (Fallback)"}
        ]
        return [f for f in fallbacks if f["provider"] in whitelist]
