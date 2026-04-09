import asyncio
import httpx
import logging
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ModelsFetcher:
    """
    models.dev からモデル定義を取得し、ホワイトリストでフィルタリングするクラス
    """
    
    SCHEMA_URL = "https://models.dev/model-schema.json"
    CACHE_TTL = 3600  # 1 hour
    
    def __init__(self, config: Any):
        self.config = config
        self._cached_models: List[Dict[str, str]] = []
        self._last_fetch_time = 0
        self._fetch_lock = asyncio.Lock()

    async def fetch_models(self) -> List[Dict[str, str]]:
        """
        models.dev および OpenRouter API からモデル定義を取得し、
        設定されたホワイトリストに基づいてフィルタリングして返す
        """
        # キャッシュのチェック (ロックなしで素早く返す)
        now = time.time()
        if self._cached_models and (now - self._last_fetch_time) < self.CACHE_TTL:
            return self._cached_models

        async with self._fetch_lock:
            # ロック取得後に再度キャッシュをチェック
            now = time.time()
            if self._cached_models and (now - self._last_fetch_time) < self.CACHE_TTL:
                return self._cached_models

            # ヘルパー: dictまたはオブジェクトの両方から値を取得
            def get_cfg_val(obj, key, default=None):
                if obj is None: return default
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            # Flixa専用のSSL検証設定を取得 (デフォルトは True)
            flixa_verify = True
            if hasattr(self.config, "providers") and isinstance(self.config.providers, dict):
                p_cfg = self.config.providers.get("flixa")
                if p_cfg:
                    options = get_cfg_val(p_cfg, "options")
                    v = get_cfg_val(options, "verify_ssl")
                    if v is not None:
                        flixa_verify = v if isinstance(v, bool) else str(v).lower() not in ("false", "0", "no")

            # ホワイトリストの取得
            whitelist = getattr(self.config, "whitelist_providers", None)
            if whitelist is None:
                # デフォルトのホワイトリスト
                whitelist = ["anthropic", "openai", "gemini", "openrouter", "flixa"]

            from magi.config.provider import resolve_provider_alias
            whitelist = [resolve_provider_alias(p.lower()) for p in whitelist]

            models = []
            seen = set()  # 重複排除用: (provider, id)

            def add_model(provider: str, model_id: str, name: Optional[str] = None):
                key = (provider.lower(), model_id)
                if key not in seen:
                    seen.add(key)
                    models.append({
                        "id": model_id,
                        "provider": provider.lower(),
                        "name": name or model_id
                    })

            # 1. models.dev から取得 (パブリックAPIは verify=True)
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
                    response = await client.get(self.SCHEMA_URL)
                    response.raise_for_status()
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
                            provider = resolve_provider_alias(raw[:slash_idx].lower())
                            model_id = raw[slash_idx + 1:]
                            
                            # 通常のプロバイダ追加
                            if provider in whitelist:
                                add_model(provider, model_id)
                            
                            # Flixa は OpenAI 互換のため、OpenAI のモデルを Flixa にも適用する
                            if provider == "openai" and "flixa" in whitelist:
                                add_model("flixa", model_id, f"Flixa {model_id}")
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP status error fetching models from {self.SCHEMA_URL}: {e}")
            except httpx.RequestError as e:
                logger.error(f"HTTP request error fetching models from {self.SCHEMA_URL}: {e}")
            except (ValueError, TypeError) as e:
                logger.error(f"Data parsing error fetching models from {self.SCHEMA_URL}: {e}")
            except Exception:
                logger.exception(f"Unexpected error fetching models from {self.SCHEMA_URL}")

            # 2. OpenRouter API から取得 (パブリックAPIは verify=True)
            if "openrouter" in whitelist:
                try:
                    async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
                        or_response = await client.get("https://openrouter.ai/api/v1/models")
                        or_response.raise_for_status()
                        if or_response.status_code == 200:
                            or_data = or_response.json()
                            or_models = or_data.get("data", [])
                            logger.info(f"Fetched {len(or_models)} models from OpenRouter API")
                            for m in or_models:
                                m_id = m.get("id")
                                if m_id:
                                    add_model("openrouter", m_id, m.get("name", m_id))
                except httpx.HTTPError as e:
                    logger.error(f"HTTP error fetching models from OpenRouter API: {e}")
                except Exception:
                    logger.exception("Unexpected error fetching models from OpenRouter API")

            # 3. Flixa API から取得 (Flixa専用の verify 設定を使用)
            if "flixa" in whitelist:
                try:
                    # 設定からエンドポイントを取得、なければデフォルト
                    p_cfg = None
                    if hasattr(self.config, "providers") and isinstance(self.config.providers, dict):
                        p_cfg = self.config.providers.get("flixa")
                    
                    flixa_endpoint = get_cfg_val(p_cfg, "endpoint")
                    if not flixa_endpoint:
                        flixa_endpoint = "https://api.flixa.engineer/v1/agent"

                    async with httpx.AsyncClient(timeout=10.0, verify=flixa_verify) as client:
                        flixa_response = await client.get(f"{flixa_endpoint}/models")
                        flixa_response.raise_for_status()
                        if flixa_response.status_code == 200:
                            flixa_data = flixa_response.json()
                            flixa_models = flixa_data.get("data", [])
                            logger.info(f"Fetched {len(flixa_models)} models from Flixa API")
                            for m in flixa_models:
                                m_id = m.get("id")
                                if m_id:
                                    add_model("flixa", m_id, m.get("name", m_id))
                except httpx.HTTPStatusError as e:
                    logger.debug(f"HTTP status error fetching models from Flixa API (expected if no API key): {e}")
                except httpx.RequestError as e:
                    logger.debug(f"HTTP request error fetching models from Flixa API: {e}")
                except (ValueError, TypeError) as e:
                    logger.debug(f"Data parsing error fetching models from Flixa API: {e}")
                except Exception:
                    logger.exception("Unexpected error fetching models from Flixa API")

            # 取得できたモデルがあればキャッシュを更新
            if models:
                self._cached_models = models
                self._last_fetch_time = time.time()
                return models
            else:
                if self._cached_models:
                    logger.info("Using expired cached models as fetch failed")
                    return self._cached_models
                return self._get_fallback_models(whitelist)

    def _get_fallback_models(self, whitelist: List[str]) -> List[Dict[str, str]]:
        """フォールバックモデルリストを返す"""
        fallbacks = [
            {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "name": "Claude 3.5 Sonnet (20241022)"},
            {"id": "claude-3-5-sonnet-latest", "provider": "anthropic", "name": "Claude 3.5 Sonnet (Latest)"},
            {"id": "claude-3-5-haiku-20241022", "provider": "anthropic", "name": "Claude 3.5 Haiku (20241022)"},
            {"id": "gpt-4o", "provider": "openai", "name": "GPT-4o (Fallback)"},
            {"id": "gpt-4o-2024-08-06", "provider": "openai", "name": "GPT-4o (2024-08-06)"},
            {"id": "gpt-4-turbo", "provider": "openai", "name": "GPT-4 Turbo (Fallback)"},
            {"id": "gpt-4", "provider": "openai", "name": "GPT-4 (Fallback)"},
            {"id": "gpt-3.5-turbo", "provider": "openai", "name": "GPT-3.5 Turbo (Fallback)"},
            
            # Flixa (OpenAI Compatible)
            {"id": "gpt-4o", "provider": "flixa", "name": "Flixa GPT-4o (Fallback)"},
            {"id": "gpt-4-turbo", "provider": "flixa", "name": "Flixa GPT-4 Turbo (Fallback)"},
            {"id": "gpt-4", "provider": "flixa", "name": "Flixa GPT-4 (Fallback)"},
            {"id": "gpt-3.5-turbo", "provider": "flixa", "name": "Flixa GPT-3.5 Turbo (Fallback)"},
            
            {"id": "gemini-1.5-pro", "provider": "gemini", "name": "Gemini 1.5 Pro (Fallback)"},
            {"id": "gemini-1.5-flash", "provider": "gemini", "name": "Gemini 1.5 Flash (Fallback)"}
        ]
        return [f for f in fallbacks if f["provider"] in whitelist]
