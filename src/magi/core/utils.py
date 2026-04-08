"""
共通ユーティリティ関数
"""

from typing import Tuple, Optional

def normalize_model_name(model_name: str, target_provider: Optional[str] = None) -> Tuple[Optional[str], str]:
    """モデル名からプロバイダプレフィックスを剥離し、プロバイダIDを推測する。

    Args:
        model_name: プレフィックスを含む可能性のあるモデル名
        target_provider: 既知のターゲットプロバイダ(OpenRouter等の場合は剥離ルールが変わる)

    Returns:
        Tuple[Optional[str], str]: (推測されたプロバイダID, プレフィックス剥離後のモデル名)
    """
    if not model_name:
        return target_provider, model_name

    # OpenRouter の場合は openrouter/ プレフィックスのみを剥離し、その後のプロバイダプレフィックスは維持する
    if model_name.startswith("openrouter/"):
        return "openrouter", model_name[len("openrouter/"):]

    # 既にターゲットが openrouter と判明している場合は、これ以上の剥離は行わない
    if target_provider == "openrouter":
        return "openrouter", model_name

    # 各プロバイダ固有のプレフィックス剥離
    if model_name.startswith("anthropic/"):
        return "anthropic", model_name[len("anthropic/"):]
    if model_name.startswith("openai/"):
        return "openai", model_name[len("openai/"):]
    if model_name.startswith("google/"):
        return "gemini", model_name[len("google/"):]
    if model_name.startswith("gemini/"):
        return "gemini", model_name[len("gemini/"):]

    return target_provider, model_name
