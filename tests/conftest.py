import hashlib
import json
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _isolate_baseline_env(monkeypatch):
    """Keep pricing-baseline env vars out of the test process.

    A developer with the real PRICING_BASELINE_KEY exported shouldn't silently
    change test behavior, and PRICING_BASELINE_STRICT=1 in the shell would
    break tests that exercise plaintext-baseline paths.
    """
    monkeypatch.delenv("PRICING_BASELINE_KEY", raising=False)
    monkeypatch.delenv("PRICING_BASELINE_STRICT", raising=False)


@pytest.fixture
def test_data_root(tmp_path):
    """Create a temporary data root with required structure."""
    (tmp_path / "files").mkdir()
    (tmp_path / "audit").mkdir()
    (tmp_path / "fonts").mkdir()
    # Empty baseline (tests work without real pricing data)
    (tmp_path / "pricing_baseline.json").write_text('{"items": []}', encoding="utf-8")
    # Copy product catalog
    src = Path("/Users/sqb/ai/quanlaidian-quotation-skill/references/product_catalog.md")
    if src.exists():
        # Also copy to references/ dir that the API expects
        refs = tmp_path.parent / "references"
        refs.mkdir(exist_ok=True)
        shutil.copy(src, refs / "product_catalog.md")
    return tmp_path

@pytest.fixture
def test_token(test_data_root):
    """Create a valid test token and return the plaintext."""
    plaintext = "test-integration-token-12345"
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    tokens = {
        token_hash: {
            "org": "test-org",
            "created_at": "2026-01-01T00:00:00Z",
            "rate_limit_per_min": 60,
        }
    }
    (test_data_root / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
    return plaintext

@pytest.fixture
def api_client(test_data_root, test_token, monkeypatch):
    """Create a TestClient with overridden settings."""
    from app.config import Settings
    import app.config as config_module

    # Build new settings pointing at temp data root
    new_settings = Settings(
        api_base_url="http://testserver",
        data_root=test_data_root,
        file_ttl_days=7,
        log_level="WARNING",
    )

    # Patch the global settings object in all modules that imported it
    monkeypatch.setattr(config_module, "settings", new_settings)
    monkeypatch.setattr("app.api.quote.settings", new_settings)
    monkeypatch.setattr("app.api.health.settings", new_settings, raising=False)

    # Override product catalog path lookup
    product_catalog = Path("/Users/sqb/ai/quanlaidian-quotation-skill/references/product_catalog.md")
    monkeypatch.setattr("app.api.quote._get_product_catalog_path", lambda: product_catalog)

    from app.main import app
    from app.auth import verify_token, TokenInfo

    # Override the auth dependency to use the test tokens file
    tokens_path = test_data_root / "tokens.json"
    app.dependency_overrides[verify_token(new_settings.data_root / "tokens.json")] = verify_token(tokens_path)

    client = TestClient(app, raise_server_exceptions=False)
    yield client, test_token

    # Clean up dependency overrides after test
    app.dependency_overrides.clear()

@pytest.fixture
def sample_form():
    return {
        "客户品牌名称": "集成测试品牌",
        "餐饮类型": "轻餐",
        "门店数量": 5,
        "门店套餐": "轻餐连锁营销基础版",
        "门店增值模块": [],
        "总部模块": [],
        "是否启用阶梯报价": False,
        "实施服务类型": "",
        "实施服务人天": 0,
    }
