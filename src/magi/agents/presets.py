"""3賢者の人格プリセット定義と解決ロジック"""

from typing import Dict, Optional


BUILTIN_PRESETS: Dict[str, Dict[str, str]] = {
    "arch": {
        "melchior": (
            "あなたはシステムアーキテクトです。"
            "大局的な設計判断と長期的な技術的影響を重視し、"
            "スケーラビリティ・保守性・整合性の観点から分析してください。"
        ),
        "balthasar": (
            "あなたはリードエンジニアです。"
            "実装の現実性、品質、チームへの影響を重視し、"
            "技術的負債とレビュー容易性の観点から評価してください。"
        ),
        "casper": (
            "あなたはクリエイターです。"
            "革新性、ユーザー体験、新しい可能性を重視し、"
            "プロダクト価値と独創性の観点から提案してください。"
        ),
    },
}


def resolve_preset_prompts(
    preset_name: Optional[str],
    config_presets: Optional[Dict[str, Dict[str, str]]],
) -> Optional[Dict[str, str]]:
    """プリセット名を解決してペルソナプロンプト辞書を返す"""
    merged: Dict[str, Dict[str, str]] = {
        **BUILTIN_PRESETS,
        **(config_presets or {}),
    }
    name = preset_name or "default"

    if name in merged:
        return merged[name]
    if name == "default":
        return None

    available = ", ".join(sorted(set(merged.keys()) | {"default"}))
    raise ValueError(f"Unknown preset: '{name}'. Available: {available}")
