import unittest
from pathlib import Path
import tempfile
import yaml
from magi.core.template_loader import TemplateLoader

class TestVoteTemplate(unittest.TestCase):
    def test_vote_prompt_template_rendering(self):
        """vote_prompt テンプレートが正しくレンダリングされ、波括弧が適切に処理されることを確認"""
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
            context_val = "Special {braces} context"
            variables = revision.variables or {}
            variables = {**variables, "context": context_val}
            rendered = revision.template.format(**variables)
            
            expected = 'Context: Special {braces} context\nFormat: {\n  "vote": "APPROVE"\n}\n'
            self.assertEqual(rendered, expected)

if __name__ == "__main__":
    unittest.main()
