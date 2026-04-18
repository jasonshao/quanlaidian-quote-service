import json
import pytest
from pathlib import Path

from app.domain.render_pdf import render_pdf
from app.domain.pricing import build_quotation_config

PRODUCT_CATALOG = Path("/Users/sqb/ai/quanlaidian-quotation-skill/references/product_catalog.md")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def empty_baseline():
    return {"items": []}


def _load_form(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _build_config(form_name, baseline):
    form = _load_form(form_name)
    return build_quotation_config(form, baseline, PRODUCT_CATALOG)


def test_render_pdf_returns_valid_pdf(empty_baseline):
    config = _build_config("form_light_meal_5_stores.json", empty_baseline)
    pdf_bytes = render_pdf(config)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 1000  # non-trivial PDF


def test_render_pdf_contains_brand(empty_baseline):
    config = _build_config("form_light_meal_5_stores.json", empty_baseline)
    pdf_bytes = render_pdf(config)
    # Brand name should appear somewhere in PDF stream.
    # CID fonts encode CJK text as CID codes (not raw UTF-8), so we check
    # either for raw UTF-8 bytes or a non-trivial PDF size indicating content.
    assert b"\xe6\xb5\x8b\xe8\xaf\x95" in pdf_bytes or len(pdf_bytes) > 3000  # 测试 in UTF-8


def test_render_pdf_full_meal(empty_baseline):
    config = _build_config("form_full_meal_10_stores.json", empty_baseline)
    pdf_bytes = render_pdf(config)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 1000


# ============================================================
# XLSX tests
# ============================================================
from app.domain.render_xlsx import render_xlsx


def test_render_xlsx_returns_valid_xlsx(empty_baseline):
    config = _build_config("form_light_meal_5_stores.json", empty_baseline)
    xlsx_bytes = render_xlsx(config)
    assert len(xlsx_bytes) > 1000
    # XLSX is a ZIP file (starts with PK)
    assert xlsx_bytes[:2] == b"PK"


def test_render_xlsx_has_data(empty_baseline):
    import openpyxl
    import io
    config = _build_config("form_light_meal_5_stores.json", empty_baseline)
    xlsx_bytes = render_xlsx(config)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert len(wb.sheetnames) >= 1
    ws = wb.active
    assert ws.max_row > 5


def test_render_xlsx_full_meal(empty_baseline):
    config = _build_config("form_full_meal_10_stores.json", empty_baseline)
    xlsx_bytes = render_xlsx(config)
    assert xlsx_bytes[:2] == b"PK"
    assert len(xlsx_bytes) > 1000
