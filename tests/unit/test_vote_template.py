"""vote_prompt テンプレートのレンダリングに関するユニットテスト

テンプレートの読み込みと、変数の埋め込み (レンダリング) が期待通りに行われることを検証します。
特に、テンプレート内の波括弧のエスケープと、変数内の波括弧がリテラルとして扱われることを確認します。
"""

import unittest
from pathlib import Path
import tempfile
import yaml
from hypothesis import given, strategies as st
from magi.core.template_loader import TemplateLoader

class TestVoteTemplate(unittest.TestCase):
    """vote_prompt テンプレートのレンダリングを検証するテストクラス

    TemplateLoader を介してテンプレートを読み込み、文字列フォーマットによって
    変数が正しく埋め込まれることを検証します。

    Args: None

    Returns: None

    Raises: None
    """

    @given(st.text(min_size=0, max_size=500))
    def test_vote_prompt_template_rendering(self, context_val: str) -> None:
        """vote_prompt テンプレートが正しくレンダリングされることを確認する

        Hypothesis を用いて、様々な文字列（ASCII、Unicode、波括弧を含む文字列など）が
        context 変数として与えられた場合に、テンプレート内のリテラルな波括弧が維持され、
        かつ context 内の波括弧がそのまま出力されることを検証します。

        Args:
            context_val (str): ランダムに生成されたコンテキスト文字列

        Returns:
            None

        Raises:
            None
        """
        template_content = {
            "name": "vote_prompt",
            "version": "v1",
            "schema_ref": "vote_schema.json",
            "template": "Context: {context}\nFormat: {{\n  \"vote\": \"APPROVE\"\n}}\n",
            "variables": {"context": "default context"}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            with open(tmpdir_path / "vote_prompt.yaml", "w", encoding="utf-8") as f:
                yaml.dump(template_content, f)

            loader = TemplateLoader(tmpdir_path)
            revision = loader.load("vote_prompt")

            # レンダリングをシミュレート (Agent._build_vote_prompt と同じロジック)
            variables = revision.variables or {}
            variables = {**variables, "context": context_val}
            rendered = revision.template.format(**variables)

            # 期待される出力を検証
            expected_prefix = "Context: "
            expected_suffix = '\nFormat: {\n  "vote": "APPROVE"\n}\n'

            # 1. プレフィックスとサフィックスが正しいこと
            self.assertTrue(rendered.startswith(expected_prefix))
            self.assertTrue(rendered.endswith(expected_suffix))

            # 2. 生成された context_val がそのまま含まれていること
            extracted_context = rendered[len(expected_prefix) : -len(expected_suffix)]
            self.assertEqual(extracted_context, context_val)

if __name__ == "__main__":
    unittest.main()
