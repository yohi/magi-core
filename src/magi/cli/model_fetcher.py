import sys
from typing import List, Optional, Any
import httpx


def fetch_available_models(provider_id: str, api_key: str) -> List[str]:
    """
    指定されたプロバイダーから利用可能なモデルの一覧を取得します。

    Args:
        provider_id: プロバイダーのID ('openai', 'anthropic', 'google' など)
        api_key: APIキー

    Returns:
        利用可能なモデルのIDのリスト
    """
    timeout = 10.0
    models: List[str] = []

    try:
        if provider_id == "openai":
            url = "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            response = httpx.get(url, headers=headers, timeout=timeout)
            _ = response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                models = [
                    str(m["id"])
                    for m in data.get("data", [])
                    if isinstance(m, dict)
                    and isinstance(m.get("id"), str)
                    and str(m["id"]).startswith("gpt-")
                ]

        elif provider_id == "anthropic":
            url = "https://api.anthropic.com/v1/models"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            response = httpx.get(url, headers=headers, timeout=timeout)
            _ = response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                models = [
                    str(m["id"])
                    for m in data.get("data", [])
                    if isinstance(m, dict) and isinstance(m.get("id"), str)
                ]

        elif provider_id == "google":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )
            response = httpx.get(url, timeout=timeout)
            _ = response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                for m in data.get("models", []):
                    if isinstance(m, dict):
                        name = m.get("name")
                        if isinstance(name, str):
                            if name.startswith("models/"):
                                models.append(name[len("models/") :])
                            else:
                                models.append(name)

        return models

    except (httpx.RequestError, httpx.HTTPStatusError, Exception) as e:
        print(
            f"Warning: Failed to fetch models for {provider_id}: {e}", file=sys.stderr
        )
        return []


# Keep Optional to satisfy the user request for the import
_: Optional[Any] = None
