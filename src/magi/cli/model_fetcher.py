import sys
from typing import List
import httpx


def _fetch_openai(api_key: str, timeout: float) -> List[str]:
    """
    OpenAIから利用可能なモデルの一覧を取得します。

    Args:
        api_key: OpenAI APIキー
        timeout: タイムアウト秒数

    Returns:
        利用可能なモデルのIDのリスト
    """
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    response = httpx.get(url, headers=headers, timeout=timeout)
    _ = response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        return []

    return [
        str(m["id"])
        for m in data.get("data", [])
        if isinstance(m, dict)
        and isinstance(m.get("id"), str)
        and str(m["id"]).startswith("gpt-")
    ]


def _fetch_anthropic(api_key: str, timeout: float) -> List[str]:
    """
    Anthropicから利用可能なモデルの一覧を取得します。

    Args:
        api_key: Anthropic APIキー
        timeout: タイムアウト秒数

    Returns:
        利用可能なモデルのIDのリスト
    """
    url = "https://api.anthropic.com/v1/models"
    params = {"limit": 1000}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    response = httpx.get(url, headers=headers, params=params, timeout=timeout)
    _ = response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        return []

    return [
        str(m["id"])
        for m in data.get("data", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    ]


def _fetch_google(api_key: str, provider_id: str, timeout: float) -> List[str]:
    """
    Googleから利用可能なモデルの一覧を取得します。

    Args:
        api_key: APIキー
        provider_id: 'google' ('antigravity' は別関数で処理)
        timeout: タイムアウト秒数

    Returns:
        利用可能なモデルのIDのリスト
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    params = {"key": api_key}
    headers = {}

    response = httpx.get(url, headers=headers, params=params, timeout=timeout)
    _ = response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        return []

    models: List[str] = []
    for m in data.get("models", []):
        if not isinstance(m, dict):
            continue

        # generateContent がサポートされているモデルのみを抽出
        supported_methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in supported_methods:
            continue

        name = m.get("name")
        if isinstance(name, str):
            if name.startswith("models/"):
                models.append(name[len("models/") :])
            else:
                models.append(name)

    return models


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

    try:
        if provider_id == "openai":
            return _fetch_openai(api_key, timeout)
        elif provider_id == "anthropic":
            return _fetch_anthropic(api_key, timeout)
        elif provider_id == "google":
            return _fetch_google(api_key, provider_id, timeout)
        elif provider_id == "antigravity":
            # Antigravityの場合は AntigravityAuthProvider.get_available_models を使用してください
            print(
                "Warning: fetch_available_models should not be used for antigravity. "
                "Use AntigravityAuthProvider.get_available_models instead.",
                file=sys.stderr,
            )
            return []
        else:
            print(f"Warning: Unknown provider ID: {provider_id}", file=sys.stderr)
            return []

    except (httpx.RequestError, httpx.HTTPStatusError, Exception) as e:
        if provider_id in ("google", "antigravity"):
            print(
                f"Warning: Failed to fetch models for {provider_id} (error hidden to protect secrets)",
                file=sys.stderr,
            )
        else:
            print(
                f"Warning: Failed to fetch models for {provider_id}: {e}",
                file=sys.stderr,
            )
        return []
