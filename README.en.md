# Quanlaidian Quote Service

> [中文版 →](README.md)

Server-side quotation service for the Quanlaidian product line. Owns the pricing algorithm, baseline data, PDF/XLSX rendering, file storage, audit logging, and approval workflow — turning every client into a thin HTTP wrapper.

**Version:** 1.0.0　**Runtime:** Python 3.10+ · FastAPI · uvicorn · SQLite

---

## Part 1 — Agent Usage Guide

> This section is written for AI agents (such as OpenClaw) that call the quotation service. It covers authentication, API endpoints, request/response schema, and error handling.

### Base URL

```
https://api.quanlaidian.com
```

During UAT the service may be reachable via a direct IP (ask the ops contact for the current host). Clients should configure the URL via the `QUOTE_API_URL` environment variable rather than hardcoding it.

### Authentication

All requests must include a Bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are issued per organisation by the server administrator (`python -m app.cli add-token --org <name>`; default expiry 180 days, `--no-expire` to override). Tokens live in the `api_token` table of `quote.db`; the server stores only `sha256(plaintext)`. A missing / wrong / revoked / expired token returns `HTTP 401`. All quote resources are scoped by `org`; cross-organisation access returns `HTTP 404`.

Token management commands:

```bash
python -m app.cli list-tokens                  # list all tokens (never prints hashes)
python -m app.cli revoke-token --id tok_xxxx   # revoke
python -m app.cli migrate-tokens-json          # one-time: import legacy data/tokens.json
```

### Idempotency (Idempotency-Key)

`POST /v1/quotes` accepts an optional `Idempotency-Key` request header. Same key + same form → same `quote_id` (retry-safe); same key + different form → `400 OUT_OF_RANGE` (client bug — key reused). Without an explicit key, the server dedups on `(org, canonical form hash)`, so repeat-submitting the same form from the same org is still idempotent.

Responses echo `X-Quote-ID` and `Idempotency-Key` headers.

---

## Resource-Oriented Quote Endpoints (Recommended)

### POST /v1/quotes — Price + Persist

Runs the pricing algorithm and writes to the `quote` table. **No files are rendered.** Use this for previews, approval-first flows, or when the client wants to defer file generation.

**Body:** see the [QuoteForm field table](#quoteform-fields) below.

**Response — HTTP 200:**

```json
{
  "request_id": "req_20260419165249_649f6de0",
  "quote_id": "q_20260419165249_649f6de0",
  "pricing_version": "small-segment-v2.3",
  "preview": {
    "brand": "海底捞火锅",
    "meal_type": "正餐",
    "stores": 30,
    "package": "正餐连锁营销旗舰版",
    "discount": 0.19,
    "totals": { "list": 478920, "final": 115119 },
    "items": [ /* … */ ]
  },
  "approval": {
    "required": false,
    "state": "not_required",
    "reasons": [],
    "decided_by": null,
    "decision_reason": null,
    "decided_at": null
  }
}
```

### GET /v1/quotes/{quote_id} — Read Persisted Quote

Returns preview, approval state, and already-rendered files.

```json
{
  "quote_id": "q_…",
  "org": "acme-sales",
  "preview": { /* same shape as above */ },
  "approval": { /* same shape as above */ },
  "renders": {
    "pdf": { "url": "…", "filename": "…", "expires_at": "…" },
    "xlsx": { "url": "…", "filename": "…", "expires_at": "…" }
  },
  "pricing_version": "small-segment-v2.3",
  "created_at": "2026-04-19T16:52:49.996645+00:00"
}
```

### POST /v1/quotes/{quote_id}/render/{format} — On-Demand Render

`format ∈ {pdf, xlsx, json}`. First call generates the file; subsequent calls reuse the URL. Pass `?force=1` to force a fresh render.

**Response — HTTP 200:**

```json
{
  "url": "https://api.quanlaidian.com/files/<file_token>/海底捞火锅-全来店-报价单-20260420.pdf",
  "filename": "海底捞火锅-全来店-报价单-20260420.pdf",
  "expires_at": "2026-04-26T16:53:08Z"
}
```

### POST /v1/quotes/{quote_id}/explain — Cost/Profit Breakdown

Internal-use endpoint — returns wholesale cost, profit, and margin per line item. **Do not expose directly to customers.**

**Response — HTTP 200:**

```json
{
  "quote_id": "q_…",
  "items": [
    {
      "name": "正餐连锁营销旗舰版",
      "category": "标准软件套餐",
      "module_category": "门店软件套餐",
      "list_price": 15120,
      "unit_price": 2872.80,
      "qty": 30,
      "subtotal": 86184.00,
      "cost_unit_price": 756.00,
      "cost_subtotal": 22680.00,
      "profit": 63504.00,
      "margin_pct": 73.7,
      "protected": false,
      "factor": 0.19
    }
  ],
  "totals": { "list": 478920, "final": 115119 },
  "pricing_info": { /* full pricing metadata */ },
  "internal_financials": { "quote_total": 115119, "cost_total": 29876, "profit_total": 85243, "profit_rate": 74.05 }
}
```

### POST /v1/quotes/{quote_id}/approvals/decide — Approval Decision

Required when `approval.required == true`.

**Body:**

```json
{
  "decision": "approve",
  "reason": "VIP customer, CEO sign-off",
  "approver": "Director Wang"
}
```

`decision` must be `"approve"` or `"reject"`. After approval, render calls succeed. After rejection, render continues to return `409` (terminal).

---

## Other Endpoints

### GET /v1/catalog

Returns the parsed product catalog as JSON. Optional query: `meal_type=轻餐|正餐`.

```json
{
  "pricing_version": "small-segment-v2.3",
  "meal_type": "正餐",
  "items": [
    { "meal_type": "正餐", "group": "门店套餐", "name": "正餐连锁营销旗舰版", "unit": "店/年", "price": 15900 }
  ]
}
```

Skill clients should fetch this at startup rather than ship their own copy of `product_catalog.md` — prevents pricing drift between skill previews and server-side reality.

### POST /v1/quote — Legacy Single-Shot (Kept for UAT Compatibility)

One call: price + persist + PDF + XLSX + JSON render, returned as `QuoteResponse`.

- Regardless of whether the client passes `成交价系数`, the request returns files directly — the service no longer enforces any approval gate. `approval.state` is always `not_required`.
- `Idempotency-Key` still honored.

```json
{
  "request_id": "req_…",
  "pricing_version": "small-segment-v2.3",
  "preview": { /* … */ },
  "files": {
    "pdf": { "url": "…", "filename": "…", "expires_at": "…" },
    "xlsx": { "url": "…", "filename": "…", "expires_at": "…" },
    "json": { "url": "…", "filename": "…", "expires_at": "…" }
  }
}
```

### GET /healthz

Health check — no auth required.

```json
{ "status": "ok", "pricing_version": "small-segment-v2.3" }
```

### GET /files/{token}/{filename}

Download a generated file by its token-scoped URL. In production nginx serves this path directly from disk (`alias data/files/`); this route is a dev-mode fallback.

---

## QuoteForm Fields

Shared by `POST /v1/quotes` and the legacy `POST /v1/quote`:

| Field | Type | Required | Constraint | Description |
|---|---|---|---|---|
| `客户品牌名称` | string | ✅ | — | Customer brand name |
| `餐饮类型` | string | ✅ | `"轻餐"` or `"正餐"` | Dining category |
| `门店数量` | integer | ✅ | 1 – 300 | Number of stores. 301+ → 422 (manual pricing). 31-300 enters large-segment tier-comparison mode — main quote uses the lower anchor's factor, response includes a tier-comparison page. See [pricing algorithm §5](docs/pricing-algorithm.md). |
| `门店套餐` | string | ✅ | — | Store package name — must match a name in [`references/product_catalog.md`](references/product_catalog.md) |
| `门店增值模块` | string[] | ❌ | — | Optional add-on modules per store |
| `总部模块` | string[] | ❌ | — | Optional HQ-level modules |
| `配送中心数量` | integer | ❌ | ≥ 0, default 0 | Number of distribution centres |
| `生产加工中心数量` | integer | ❌ | ≥ 0, default 0 | Number of production/processing centres |
| `成交价系数` | float | ❌ | 0.01 – 1.0 | Explicit deal-price coefficient. **Requires `人工改价原因`** when set |
| `人工改价原因` | string | ❌ | non-empty | Required when `成交价系数` is set (audit trail) |
| `是否启用阶梯报价` | boolean | ❌ | default `false` | Enable tiered pricing |
| `实施服务类型` | string | ❌ | — | Implementation service type |
| `实施服务人天` | integer | ❌ | ≥ 0, default 0 | Implementation service person-days |

---

## Error Responses

All errors share the same envelope:

```json
{
  "error": {
    "code": "OUT_OF_RANGE",
    "message": "specific error message",
    "field": "<optional_field_name>",
    "hint": "<optional_hint>",
    "request_id": "req_20260419165334_ac8dbe5f"
  }
}
```

| HTTP | `code` | Cause |
|---|---|---|
| 401 | — | Missing or invalid Bearer token |
| 404 | `NOT_FOUND` | Quote does not exist or does not belong to the caller's org |
| 422 | `INVALID_FORM` | Request body fails schema validation |
| 400 | `OUT_OF_RANGE` | Business-rule violation (missing manual-override reason, Idempotency-Key conflict, etc.) |
| 500 | `PRICING_FAILED` | Pricing algorithm error (missing baseline or product catalog) |
| 500 | `RENDER_FAILED` | PDF or XLSX generation error |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

---

## Thin Client (OpenClaw Skill)

The companion skill repository [`quanlaidian-quote-skills`](https://github.com/jasonshao/quanlaidian-quote-skills) provides a thin client. Configure two environment variables:

```bash
export QUOTE_API_TOKEN=<your_token>
export QUOTE_API_URL=https://api.quanlaidian.com
```

---

## Part 2 — Project Description & Architecture

### Background

The original quotation system was a "fat skill" distributed to every user's OpenClaw node: 155 KB of Python, encrypted pricing data, a decryption key, and Feishu credentials — all on every user machine. This caused:

- Feishu API calls failing randomly on user nodes
- Pricing algorithm breakage after auto-updates (dependency / baseline / algorithm version drift)
- Security exposure: pricing keys and credentials on every client machine

This service owns all sensitive logic server-side: the pricing algorithm, the pricing baseline (runtime XOR+SHA256 decoded — plaintext never touches disk), PDF/XLSX generation, file storage, SQLite persistence, audit logging, and approval workflow.

---

### Repository Layout

```
quanlaidian-quote-service/
├── pyproject.toml
├── .env.example                       # includes PRICING_BASELINE_KEY / STRICT
├── app/
│   ├── main.py                        # FastAPI entry + lifespan SQLite init
│   ├── config.py                      # Pydantic Settings (QUOTE_ prefix)
│   ├── auth.py                        # Bearer token verification
│   ├── audit.py                       # Append-only JSONL audit logger
│   ├── errors.py                      # Unified exception classes + handlers
│   ├── storage.py                     # LocalDiskStorage (returns file_token)
│   ├── cli.py                         # Token management CLI
│   ├── api/
│   │   ├── quote.py                   # POST /v1/quote (legacy)
│   │   ├── quotes.py                  # /v1/quotes/* resource endpoints
│   │   ├── catalog.py                 # GET /v1/catalog
│   │   ├── files.py                   # GET /files/{token}/{filename}
│   │   └── health.py                  # GET /healthz
│   ├── domain/
│   │   ├── schema.py                  # Pydantic request/response models
│   │   ├── pricing.py                 # Pricing algorithm (small-segment-v2.3)
│   │   ├── pricing_baseline.py        # .obf runtime decode + plaintext fallback
│   │   ├── quote_service.py           # Price/render/approval business logic (shared)
│   │   ├── render_pdf.py              # reportlab PDF
│   │   └── render_xlsx.py             # openpyxl XLSX
│   └── persistence/                   # SQLite persistence layer (Wave B0)
│       ├── db.py                      # Connection + schema initialisation
│       ├── models.py                  # Quote / QuoteRender / Approval dataclasses
│       └── quote_repo.py              # CRUD + idempotency logic
├── data/                              # Runtime state (NOT in VCS)
│   ├── quote.db                       # SQLite: quote / quote_render / approval / api_token
│   ├── pricing_baseline.json          # Plaintext baseline (optional; obf preferred)
│   ├── fonts/                         # CJK fonts for PDF rendering
│   ├── files/                         # Generated files (7-day TTL)
│   └── audit/                         # YYYY-MM-DD.jsonl audit logs
├── references/
│   ├── product_catalog.md             # Product catalog (customer-facing list prices)
│   └── pricing_baseline_v5.obf        # Obfuscated baseline (preferred in production)
├── docs/
│   └── pricing-algorithm.md           # Pricing algorithm reference
├── tests/                             # all tests green
│   ├── conftest.py
│   ├── fixtures/
│   ├── test_api.py                    # Endpoint integration tests (incl. new resources)
│   ├── test_persistence.py            # SQLite layer unit tests
│   ├── test_pricing.py
│   ├── test_render.py
│   ├── test_schema.py
│   ├── test_storage.py
│   ├── test_auth.py
│   └── test_errors.py
└── ops/
    ├── nginx.conf.example
    ├── systemd/quanlaidian-quote.service
    ├── cron/cleanup-files.sh
    ├── migrate_baseline.py            # .obf → plaintext JSON (emergency)
    ├── obfuscate_baseline.py          # plaintext JSON → .obf (re-encrypt after pricing change)
    ├── extract_baseline_from_xlsx.py  # Source-of-truth xlsx → plaintext JSON
    └── runbook.md                     # Deployment and operations guide
```

---

### Module Responsibilities

#### `app/config.py` — Settings

Pydantic `BaseSettings` reads all configuration from environment variables:

| Variable | Default | Description |
|---|---|---|
| `QUOTE_API_BASE_URL` | `https://api.quanlaidian.com` | Public base URL |
| `QUOTE_DATA_ROOT` | `data` | Root directory for files, tokens, DB, audit |
| `QUOTE_FILE_TTL_DAYS` | `7` | Days before generated files are eligible for cleanup |
| `QUOTE_LOG_LEVEL` | `INFO` | Logging verbosity |
| `PRICING_BASELINE_KEY` | — | Decryption key for the `.obf` baseline (required in prod) |
| `PRICING_BASELINE_STRICT` | `0` | Set to `1` to refuse plaintext fallback (recommended in prod) |

#### `app/domain/pricing_baseline.py` — Runtime Baseline Codec

At request time, the XOR+SHA256 obfuscated `references/pricing_baseline_v5.obf` is decoded in memory using `PRICING_BASELINE_KEY` (ported from the legacy skill). Plaintext never touches disk. Strict mode forces the obf+key path; non-strict mode prefers obf but falls back to `data/pricing_baseline.json`; with both missing the service fails to start (no silent empty-items fallback — the root cause of the previously observed Haidilao quote bug).

#### `app/domain/pricing.py` — Pricing Algorithm

Ported from the legacy `build_quotation_config.py`. Packages use a `cost × 20` standard price combined with a deep discount factor (typical SaaS high-sticker model); add-on and HQ modules use a `cost × 1.20` / `cost × 1.50` cost-plus markup that protects margin even under deep package discounts. See [`docs/pricing-algorithm.md`](docs/pricing-algorithm.md) for details.

Entry point: `build_quotation_config(form_dict, baseline, product_catalog_path) → dict`

#### `app/domain/quote_service.py` — Business Logic Layer

`price_and_persist`, `render_format`, `build_preview`, `build_breakdown`, `approval_to_state`, and helpers. Both the legacy `/v1/quote` endpoint and the resource endpoints call into this single service layer, guaranteeing behaviour parity.

#### `app/persistence/` — SQLite Persistence

Three tables:

- `quote` — one row per quoted form (deduped by `(org, form_hash)`, optional `idempotency_key`)
- `quote_render` — one row per generated file
- `approval` — up to one per quote; state machine `not_required → pending → approved | rejected`

Schema is created via `CREATE TABLE IF NOT EXISTS` in the FastAPI lifespan startup. No Alembic yet — UAT stage.

#### `app/api/quotes.py` — Resource-Oriented Routes

Five resource endpoints: create, read, on-demand render, explain, approval decision. Render returns 409 when the approval state is anything other than `approved`.

#### `app/api/quote.py` — Legacy Endpoint

`POST /v1/quote` is retained as a compound call: `price_and_persist → render(pdf) → render(xlsx) → render(json) → QuoteResponse`. Approval-required quotes return 409 immediately; clients should migrate to the resource endpoints for those flows.

#### `app/api/catalog.py` — Catalog Endpoint

`GET /v1/catalog` serves the parsed `product_catalog.md` as JSON, giving skill-side clients a single source of truth.

#### `app/auth.py` + `app/cli.py` — Token Management

`secrets.token_urlsafe(32)` generates a 256-bit random bearer; only `sha256(plaintext)` lands in the `api_token` table of `data/quote.db` (fields: `token_id / token_hash / org / created_at / expires_at / revoked_at / last_used_on`). The plaintext is printed exactly once on creation. Each request looks up the hash filtered by `revoked_at` and `expires_at`, then uses `hmac.compare_digest` for timing-safe comparison. `last_used_on` is updated at most once per token per UTC day (day-sampled via an in-process cache).

#### `app/audit.py` — Audit Logging

Each successful quote request and approval decision appends one JSON line to `data/audit/YYYY-MM-DD.jsonl`. Fields include `ts`, `request_id`, `quote_id`, `org`, `brand`, `stores`, `package`, `discount`, `final`, `pricing_version`, `status`, `duration_ms`.

---

### Request Flow

**Resource-oriented (recommended):**

```
OpenClaw agent
    │
    │ POST /v1/quotes  {QuoteForm}         → price, write quote + approval
    │ GET  /v1/quotes/{id}                 → read back
    │ POST /v1/quotes/{id}/approvals/decide → reviewer decision (if required)
    │ POST /v1/quotes/{id}/render/{format}  → on-demand render
    │
    ▼
FastAPI → auth → schema → quote_service → pricing → render → storage → audit
                                              │
                                              ▼
                                       SQLite data/quote.db
                                       (quote / quote_render / approval)
```

**Legacy (kept for backwards compatibility):**

```
POST /v1/quote → price_and_persist → render(pdf) + render(xlsx) + render(json)
               → 200 QuoteResponse (3 file URLs)
```

---

### Ops Stack

| Component | Tool |
|---|---|
| ASGI server | uvicorn |
| Reverse proxy | nginx (TLS via certbot) |
| Process manager | systemd (`ops/systemd/quanlaidian-quote.service`) |
| Persistence | SQLite (`data/quote.db`) |
| File cleanup | cron (`ops/cron/cleanup-files.sh`) |
| Baseline maintenance | `ops/extract_baseline_from_xlsx.py` → `ops/obfuscate_baseline.py` (re-encrypt on pricing change) |

See [`ops/runbook.md`](ops/runbook.md) for step-by-step first-time deployment, token provisioning, log access, rollback, and baseline rotation.

---

### Development Setup

```bash
git clone <repo>
cd quanlaidian-quote-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # fill in PRICING_BASELINE_KEY
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest tests/ -v
# all tests green
```

Issue a development token:

```bash
python -m app.cli add-token --org dev
# prints token_id + plaintext (plaintext shown only once)
# use plaintext in the client's QUOTE_API_TOKEN env var
```

Other token management commands:

```bash
python -m app.cli list-tokens
python -m app.cli revoke-token --id tok_xxxxxxxx
python -m app.cli add-token --org staging --expires-in 30d   # custom expiry
python -m app.cli add-token --org admin --no-expire          # never expires
```
