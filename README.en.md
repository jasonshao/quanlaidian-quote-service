# Quanlaidian Quote Service

> [中文版 →](README.md)

Server-side quotation service for the Quanlaidian product line. Owns the pricing algorithm, baseline data, PDF/XLSX rendering, file storage, and audit logging — turning every client into a thin HTTP wrapper.

**Version:** 1.0.0　**Runtime:** Python 3.10+ · FastAPI · uvicorn

---

## Part 1 — Agent Usage Guide

> This section is written for AI agents (such as OpenClaw) that call the quotation service. It covers authentication, the API endpoint, request/response schema, and error handling.

### Base URL

```
https://api.quanlaidian.com
```

### Authentication

All requests must include a Bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are issued per organisation by the server administrator (see `python -m app.cli add-token`). A missing or incorrect token returns `HTTP 401`.

---

### POST /v1/quote

Generate a quotation. Returns a JSON preview and time-limited download URLs for the PDF, XLSX, and JSON config files.

#### Request

**Headers:**

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <token>` |

**Body — all fields (JSON):**

| Field | Type | Required | Constraint | Description |
|---|---|---|---|---|
| `客户品牌名称` | string | ✅ | — | Customer brand name |
| `餐饮类型` | string | ✅ | `"轻餐"` or `"正餐"` | Dining category |
| `门店数量` | integer | ✅ | 1 – 30 | Number of stores |
| `门店套餐` | string | ✅ | — | Store package name — must match a name in [`references/product_catalog.md`](references/product_catalog.md), e.g. `"轻餐连锁营销旗舰版"` or `"正餐连锁营销旗舰版"` |
| `门店增值模块` | string[] | ❌ | — | Optional add-on modules per store |
| `总部模块` | string[] | ❌ | — | Optional HQ-level modules |
| `配送中心数量` | integer | ❌ | ≥ 0, default 0 | Number of distribution centres |
| `生产加工中心数量` | integer | ❌ | ≥ 0, default 0 | Number of production/processing centres |
| `成交价系数` | float | ❌ | 0.01 – 1.0 | Explicit deal-price coefficient (overrides computed discount). **If set, `人工改价原因` is required** — otherwise the request returns `400 OUT_OF_RANGE`. |
| `人工改价原因` | string | ❌ | non-empty | Required when `成交价系数` is provided (audit trail for manual override) |
| `是否启用阶梯报价` | boolean | ❌ | default `false` | Enable tiered pricing |
| `实施服务类型` | string | ❌ | — | Implementation service type |
| `实施服务人天` | integer | ❌ | ≥ 0, default 0 | Implementation service person-days |

**Minimal example:**

```json
{
  "客户品牌名称": "示例品牌",
  "餐饮类型": "轻餐",
  "门店数量": 5,
  "门店套餐": "轻餐连锁营销旗舰版"
}
```

**Full example:**

```json
{
  "客户品牌名称": "示例品牌",
  "餐饮类型": "正餐",
  "门店数量": 10,
  "门店套餐": "正餐连锁营销旗舰版",
  "门店增值模块": ["厨房KDS"],
  "总部模块": ["配送中心"],
  "配送中心数量": 1,
  "生产加工中心数量": 0,
  "成交价系数": 0.85,
  "人工改价原因": "总部战略客户，CEO 特批",
  "是否启用阶梯报价": false,
  "实施服务类型": "标准实施",
  "实施服务人天": 5
}
```

#### Response — HTTP 200

```json
{
  "request_id": "req_20260419143022_a1b2c3d4",
  "pricing_version": "small-segment-v2.3",
  "preview": {
    "brand": "示例品牌",
    "meal_type": "正餐",
    "stores": 10,
    "package": "正餐连锁营销旗舰版",
    "discount": 0.85,
    "totals": {
      "list": 480000,
      "final": 408000
    },
    "items": [
      {
        "name": "正餐连锁营销旗舰版",
        "qty": 10,
        "list": 39800,
        "final": 33830
      }
    ]
  },
  "files": {
    "pdf": {
      "url": "https://api.quanlaidian.com/files/<token>/示例品牌-全来店-报价单-20260419.pdf",
      "filename": "示例品牌-全来店-报价单-20260419.pdf",
      "expires_at": "2026-04-26T14:30:22Z"
    },
    "xlsx": {
      "url": "https://api.quanlaidian.com/files/<token>/示例品牌-全来店-报价单-20260419.xlsx",
      "filename": "示例品牌-全来店-报价单-20260419.xlsx",
      "expires_at": "2026-04-26T14:30:22Z"
    },
    "json": {
      "url": "https://api.quanlaidian.com/files/<token>/示例品牌-全来店-报价配置-20260419.json",
      "filename": "示例品牌-全来店-报价配置-20260419.json",
      "expires_at": "2026-04-26T14:30:22Z"
    }
  }
}
```

**Field notes:**
- `prices` are integers in 元 (CNY), e.g. `408000` = ¥408,000.
- `discount` is the final deal-price coefficient, e.g. `0.85` = 85%.
- File URLs are valid for **7 days**. Download them promptly and deliver to the customer.
- `pricing_version` identifies the baseline data version used; include it in customer communications for audit traceability.

#### Error Responses

All errors share the same envelope:

```json
{
  "error": {
    "code": "<ERROR_CODE>",
    "message": "Human-readable description",
    "field": "<field_name_if_applicable>",
    "hint": "<optional_hint>",
    "request_id": "req_20260419143022_a1b2c3d4"
  }
}
```

| HTTP | `code` | Cause |
|---|---|---|
| 401 | — | Missing or invalid Bearer token |
| 422 | `INVALID_FORM` | Request body fails schema validation (e.g. missing required field, value out of range) |
| 400 | `OUT_OF_RANGE` | Business-logic range violation (e.g. 门店数量 > 30) |
| 500 | `PRICING_FAILED` | Pricing algorithm error (e.g. missing baseline or product catalog) |
| 500 | `RENDER_FAILED` | PDF or XLSX generation error |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

---

### GET /healthz

Health check — no authentication required.

**Response:**
```json
{
  "status": "ok",
  "pricing_version": "small-segment-v2.3"
}
```

---

### GET /files/{token}/{filename}

Download a generated file by its token-scoped URL. In production nginx serves this path directly from disk (`alias data/files/`). This route is a dev-mode fallback only.

---

### Thin Client (OpenClaw Skill)

The companion skill `quanlaidian-quotation-skill` provides a ready-made thin client (`scripts/quote.py`, 45 lines, zero extra dependencies). Configure two environment variables and invoke:

```bash
export QUOTE_API_TOKEN=<your_token>
export QUOTE_API_URL=https://api.quanlaidian.com
python3 scripts/quote.py --form form_submission.json
```

The script prints the JSON response and the three download URLs.

---

## Part 2 — Project Description & Architecture

### Background

The original quotation system was a "fat skill" distributed to every user's OpenClaw node: 155 KB of Python, encrypted pricing data, a decryption key, and Feishu credentials — all on every user machine. This caused:

- Feishu API calls failing randomly on user nodes
- Pricing algorithm breakage after auto-updates (dependency / baseline / algorithm version drift)
- Security exposure: pricing keys and credentials on every client machine

This service is the server-side half of the refactoring. It owns all sensitive logic: the pricing algorithm, the pricing baseline, PDF/XLSX generation, file storage, and audit logging. Clients become a 45-line HTTP wrapper.

---

### Repository Layout

```
quanlaidian-quote-service/
├── pyproject.toml              # Project metadata and dependencies
├── .env.example                # Environment variable template
├── .gitignore
├── app/
│   ├── main.py                 # FastAPI app assembly + middleware
│   ├── config.py               # Pydantic Settings (env prefix: QUOTE_)
│   ├── auth.py                 # Bearer token verification (sha256 + hmac)
│   ├── audit.py                # Append-only JSONL audit logger
│   ├── errors.py               # Unified exception classes + handlers
│   ├── storage.py              # Storage protocol + LocalDiskStorage
│   ├── cli.py                  # Token management CLI
│   ├── api/
│   │   ├── quote.py            # POST /v1/quote route handler
│   │   ├── files.py            # GET /files/{token}/{filename} (dev fallback)
│   │   └── health.py           # GET /healthz
│   └── domain/
│       ├── schema.py           # Pydantic request/response models
│       ├── pricing.py          # Pricing algorithm (ported from build_quotation_config.py)
│       ├── pricing_baseline.py # Load plaintext pricing_baseline.json
│       ├── render_pdf.py       # PDF generation (reportlab, ported from generate_quotation.py)
│       └── render_xlsx.py      # XLSX generation (openpyxl, ported from generate_quotation.py)
├── data/
│   ├── pricing_baseline.json   # Pricing data — NOT in VCS, deploy manually
│   ├── tokens.json             # SHA-256 hashed token store
│   ├── fonts/                  # CJK fonts for reportlab (NOT in VCS)
│   ├── files/                  # Generated output files (7-day TTL, NOT in VCS)
│   └── audit/                  # YYYY-MM-DD.jsonl audit logs (NOT in VCS)
├── references/
│   └── product_catalog.md      # Product catalogue (read by pricing algorithm)
├── tests/
│   ├── conftest.py             # Test fixtures (TestClient, temp data_root, test tokens)
│   ├── fixtures/               # Example form JSON inputs
│   ├── test_schema.py
│   ├── test_storage.py
│   ├── test_auth.py
│   ├── test_errors.py
│   ├── test_pricing.py
│   ├── test_render.py
│   └── test_api.py             # 44 integration tests — all passing
└── ops/
    ├── nginx.conf.example      # Reverse proxy config (TLS, file serving)
    ├── systemd/
    │   └── quanlaidian-quote.service
    ├── cron/
    │   └── cleanup-files.sh    # Delete files older than 7 days
    ├── migrate_baseline.py     # Decrypt .obf baseline → plaintext JSON
    └── runbook.md              # Deployment and operations guide
```

---

### Module Responsibilities

#### `app/config.py` — Settings

Pydantic `BaseSettings` reads all configuration from environment variables with the `QUOTE_` prefix:

| Variable | Default | Description |
|---|---|---|
| `QUOTE_API_BASE_URL` | `https://api.quanlaidian.com` | Public base URL (used to build file download URLs) |
| `QUOTE_DATA_ROOT` | `data` | Root directory for files, tokens, audit logs |
| `QUOTE_FILE_TTL_DAYS` | `7` | Days before generated files are eligible for cleanup |
| `QUOTE_LOG_LEVEL` | `INFO` | Logging verbosity |

#### `app/auth.py` + `app/cli.py` — Token Management

Tokens are never stored in plaintext. The CLI generates a `secrets.token_urlsafe(32)` value, stores its `sha256` hex digest in `data/tokens.json`, and prints the plaintext token once:

```bash
python -m app.cli add-token --org "acme-sales"
# → Token for acme-sales: qlq_Xr9...  (shown once, store it safely)
```

On each request, `auth.py` hashes the presented bearer token and uses `hmac.compare_digest` for timing-safe comparison against all stored hashes. No raw tokens ever touch disk.

#### `app/errors.py` — Unified Error Model

Three custom exception classes (`OutOfRangeError`, `PricingError`, `RenderError`) map cleanly to structured JSON responses via FastAPI exception handlers. Every error response carries `request_id`, `code`, `message`, and optionally `field` and `hint`. The catch-all handler ensures no Python tracebacks leak to clients.

#### `app/storage.py` — File Storage

`LocalDiskStorage` saves each output file under a random 32-byte URL-safe token subdirectory:

```
data/files/<token>/<filename>
```

The public URL is `{api_base_url}/files/<token>/<filename>`. nginx serves this path directly in production (`alias`), bypassing FastAPI for file I/O. The `expires_at` timestamp is `now + file_ttl_days`; actual deletion is handled by the cron job.

#### `app/audit.py` — Audit Logging

Each successful quote request appends one JSON line to `data/audit/YYYY-MM-DD.jsonl`. Fields: `ts`, `request_id`, `org`, `brand`, `stores`, `package`, `discount`, `final`, `pricing_version`, `status`, `duration_ms`. The file is rotated daily by the filename date; no log rotation daemon needed.

#### `app/domain/schema.py` — Pydantic Models

Request: `QuoteForm` — 12 fields, with validators: `门店数量` ∈ [1, 30], `成交价系数` ∈ [0.01, 1.0].

Response: `QuoteResponse` → `preview: QuotePreview` + `files: dict[str, FileRef]` + `pricing_version`.

Error: `ErrorResponse` → `error: ErrorDetail`.

#### `app/domain/pricing.py` — Pricing Algorithm

Ported line-for-line from the legacy `build_quotation_config.py` (963 lines). The only changes: Pydantic model field access instead of dict subscript, plaintext JSON baseline instead of obfuscated `.obf` files, and `PricingError` / `OutOfRangeError` raised on business-logic failures.

Entry point: `build_quotation_config(form_dict, baseline, product_catalog_path) → dict`

The returned `dict` is the full quotation configuration — the same structure consumed by the PDF and XLSX renderers, and saved as the `.json` download.

#### `app/domain/render_pdf.py` + `app/domain/render_xlsx.py` — File Rendering

Both modules are ported from the legacy `generate_quotation.py` (1,735 lines), split by output format. Entry points:

- `render_pdf(config: dict, fonts_dir: Path) → bytes` — uses reportlab; returns raw PDF bytes
- `render_xlsx(config: dict) → bytes` — uses openpyxl; returns XLSX bytes via `io.BytesIO`

Font registration for CJK characters is handled inside `render_pdf`. Fonts are loaded from `data/fonts/` (not in VCS; deploy separately).

#### `app/api/quote.py` — Route Handler

The `POST /v1/quote` handler orchestrates the full pipeline in one request:

1. Parse and validate `QuoteForm` (Pydantic, auto-raises `INVALID_FORM` on failure)
2. Authenticate caller via `Depends(verify_token(...))`
3. Generate `request_id`
4. Load pricing baseline and product catalog from disk
5. Run `build_quotation_config` → config dict
6. Render PDF and XLSX
7. Save all three files (PDF, XLSX, JSON) via `LocalDiskStorage`
8. Build `QuotePreview` from config
9. Write audit log
10. Return `QuoteResponse`

---

### Request Flow Diagram

```
OpenClaw agent
    │
    │  POST /v1/quote
    │  Authorization: Bearer <token>
    │  {QuoteForm JSON}
    ▼
nginx (TLS termination)
    │
    ▼
FastAPI app (uvicorn, 127.0.0.1:8000)
    │
    ├─ auth.py: verify Bearer token (sha256 + hmac)
    ├─ schema.py: validate QuoteForm
    ├─ pricing.py: build quotation config (baseline + product_catalog)
    ├─ render_pdf.py: generate PDF bytes
    ├─ render_xlsx.py: generate XLSX bytes
    ├─ storage.py: save PDF + XLSX + JSON to data/files/<token>/
    ├─ audit.py: append to data/audit/YYYY-MM-DD.jsonl
    └─ return QuoteResponse (preview + 3 file URLs)

    │ GET /files/<token>/<filename>
    ▼
nginx (serves data/files/ directly, 7-day expiry header)
```

---

### Ops Stack

| Component | Tool |
|---|---|
| WSGI server | uvicorn (2 workers) |
| Reverse proxy | nginx (TLS via certbot, file serving via `alias`) |
| Process manager | systemd (`ops/systemd/quanlaidian-quote.service`) |
| File cleanup | cron (`ops/cron/cleanup-files.sh`, `find -mtime +7`) |
| Baseline migration | `ops/migrate_baseline.py` (decrypt `.obf` → plaintext JSON) |

See `ops/runbook.md` for step-by-step first-time deployment, token provisioning, log access, and rollback procedures.

---

### Development Setup

```bash
git clone <repo>
cd quanlaidian-quote-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit as needed
cp data/pricing_baseline.example.json data/pricing_baseline.json  # populate real data
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest tests/ -v
# 44 tests, all green
```

Issue a development token:

```bash
python -m app.cli add-token --org dev
# prints plaintext token — use in QUOTE_API_TOKEN env var on the client
```
