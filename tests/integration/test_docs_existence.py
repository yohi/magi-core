import os
from pathlib import Path

def test_migration_guide_exists():
    """Verify that the configuration migration guide exists."""
    doc_path = Path("docs/configuration_migration.md")
    assert doc_path.exists(), f"Documentation file {doc_path} not found"
    
    content = doc_path.read_text(encoding="utf-8")
    assert "# 設定移行ガイド" in content or "# Configuration Migration Guide" in content
    assert "MagiSettings" in content
    assert "MAGI_API_KEY" in content

def test_production_guide_exists():
    """Verify that the production operation guide exists."""
    doc_path = Path("docs/production_guide.md")
    assert doc_path.exists(), f"Documentation file {doc_path} not found"
    
    content = doc_path.read_text(encoding="utf-8")
    assert "# 本番運用ガイド" in content or "# Production Operation Guide" in content
    assert "production_mode" in content
    assert "plugin_public_key_path" in content
    assert "監査ログ" in content or "Audit Log" in content
