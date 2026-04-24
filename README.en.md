# Quanlaidian Quote Service

> [中文版 →](README.md)

Server-side quotation service for the Quanlaidian product line. Owns the pricing algorithm, baseline data, PDF/XLSX rendering, file storage, and audit logging — turning every client into a thin HTTP wrapper.

**Version:** 1.0.0　**Runtime:** Python 3.10+ · FastAPI · uvicorn · SQLite

---

## Part 1 — HTTP API Reference

> This section documents the public HTTP API exposed by this service, primarily consumed by the companion skill repository [`quanlaidian-quote-skills`](https://github.com/WoSai/quanlaidian-quote-skills). The skill repo wraps authentication, form assembly, and download-link rendering — it is the recommended client. This section doubles as the contract for any direct integrators.

### Base URL

```
https://<your-api-host>
```

The actual host is provided by the ops contact (during UAT the service may be reachable via a direct IP). The skill reads it from the `QUOTE_API_URL` environment variable rather than hardcoding it.

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

---

## Business Endpoint

### POST /v1/quote — Price + Render PDF/XLSX/JSON

The single public business endpoint. One call does everything: price → persist → render PDF/XLSX/JSON, returned as a `QuoteResponse` containing preview + three download URLs.

Idempotent on `(org, canonical form)`: replaying the same form from the same org returns the same `quote_id` without creating duplicate DB rows.

**Body:** see the [QuoteForm field table](#quoteform-fields) below.

**Response — HTTP 200:**

```json
{
  "request_id": "req_…",
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
  "files": {
    "pdf":  { "url": "…", "filename": "…", "expires_at": "…" },
    "xlsx": { "url": "…", "filename": "…", "expires_at": "…" },
    "json": { "url": "…", "filename": "…", "expires_at": "…" }
  }
}
```

---

## Operational Endpoints

### GET /healthz

Health check — no auth required.

```json
{ "status": "ok", "pricing_version": "small-segment-v2.3" }
```

### GET /files/{token}/{filename}

Download a generated file by its token-scoped URL — **active only when `QUOTE_STORAGE_BACKEND=local`**. In production nginx serves this path directly from disk (`alias data/files/`); this route is a dev-mode fallback. Not called directly by clients. When the OSS backend is enabled, `POST /v1/quote`'s `files[*].url` returns OSS pre-signed URLs directly (optionally rewritten to a CDN host via `QUOTE_OSS_PUBLIC_BASE_URL`) and this route is unused — see [File Storage Backends](#appstoragepy--file-storage-backends).

---

## QuoteForm Fields

Request body for `POST /v1/quote`:

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
| 422 | `INVALID_FORM` | Request body fails schema validation |
| 400 | `OUT_OF_RANGE` | Business-rule violation (e.g. `成交价系数` given without `人工改价原因`) |
| 500 | `PRICING_FAILED` | Pricing algorithm error (missing baseline or product catalog) |
| 500 | `RENDER_FAILED` | PDF or XLSX generation error |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

---

## Companion Skill Repository

[`quanlaidian-quote-skills`](https://github.com/WoSai/quanlaidian-quote-skills) is the recommended client for this service. Implemented against the Python 3 standard library with zero dependencies, it wraps authentication, form submission, and download-link rendering. Integration needs just two environment variables:

```bash
export QUOTE_API_TOKEN=<your_token>       # request from this service's administrator
export QUOTE_API_URL=https://<your-api-host>/v1/quote
```

See the skill repo's own README for install, usage, and auto-update details.

---

## Part 2 — Project Description & Architecture

### Background

The original quotation system was a "fat skill" distributed to every user's OpenClaw node: 155 KB of Python, encrypted pricing data, a decryption key, and Feishu credentials — all on every user machine. This caused:

- Feishu API calls failing randomly on user nodes
- Pricing algorithm breakage after auto-updates (dependency / baseline / algorithm version drift)
- Security exposure: pricing keys and credentials on every client machine

This service owns all sensitive logic server-side: the pricing algorithm, the pricing baseline (runtime XOR+SHA256 decoded — plaintext never touches disk), PDF/XLSX generation, file storage, SQLite persistence, and audit logging.

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
│   ├── storage.py                     # LocalDiskStorage / OssStorage (returns file_token or OSS signed URL)
│   ├── cli.py                         # Token management CLI
│   ├── api/
│   │   ├── quote.py                   # POST /v1/quote
│   │   ├── files.py                   # GET /files/{token}/{filename}
│   │   └── health.py                  # GET /healthz
│   ├── domain/
│   │   ├── schema.py                  # Pydantic request/response models
│   │   ├── pricing.py                 # Pricing algorithm (small-segment-v2.3)
│   │   ├── pricing_baseline.py        # .obf runtime decode + plaintext fallback
│   │   ├── quote_service.py           # Price/render business logic
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
│   ├── files/                         # Locally generated files (local backend only, 7-day TTL)
│   └── audit/                         # YYYY-MM-DD.jsonl audit logs
├── references/
│   ├── product_catalog.md             # Product catalog (customer-facing list prices)
│   └── pricing_baseline_v5.obf        # Obfuscated baseline (preferred in production)
├── docs/
│   └── pricing-algorithm.md           # Pricing algorithm reference
├── tests/                             # all tests green
│   ├── conftest.py
│   ├── fixtures/
│   ├── test_api.py                    # Endpoint integration tests
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
| `QUOTE_API_BASE_URL` | `https://<your-api-host>` | Public base URL (ask the administrator for the actual host) |
| `QUOTE_DATA_ROOT` | `data` | Root directory for files, tokens, DB, audit |
| `QUOTE_FILE_TTL_DAYS` | `7` | Generated-file lifetime (cleanup window for local disk, signed-URL expiry for OSS) |
| `QUOTE_LOG_LEVEL` | `INFO` | Logging verbosity |
| `QUOTE_STORAGE_BACKEND` | `local` | File storage backend: `local` or `oss` (Aliyun OSS) |
| `QUOTE_OSS_ENDPOINT` | `oss-cn-hangzhou.aliyuncs.com` | OSS endpoint |
| `QUOTE_OSS_BUCKET` | `private-wosai-statics` | OSS bucket name |
| `QUOTE_OSS_PREFIX` | `quanlaidian-quote` | OSS object-key prefix |
| `QUOTE_OSS_PUBLIC_BASE_URL` | `https://private-resource.shouqianba.com` | Host override for signed URLs (typically a CDN domain) |
| `QUOTE_OSS_ACCESS_KEY_ID` | — | OSS access key ID (required when backend is `oss`) |
| `QUOTE_OSS_ACCESS_KEY_SECRET` | — | OSS access key secret (required when backend is `oss`) |
| `PRICING_BASELINE_KEY` | — | Decryption key for the `.obf` baseline (required in prod) |
| `PRICING_BASELINE_STRICT` | `0` | Set to `1` to refuse plaintext fallback (recommended in prod) |

#### `app/storage.py` — File Storage Backends

PDF / XLSX / JSON files produced by `POST /v1/quote` are persisted through a `Storage` abstraction. `QUOTE_STORAGE_BACKEND` selects the implementation:

- **`local` (default)** — `LocalDiskStorage`: files land at `data/files/<file_token>/<filename>`; response URLs point back at this service's `GET /files/{token}/{filename}`. In production nginx typically serves these directly via `alias data/files/`, and `ops/cron/cleanup-files.sh` deletes files older than `QUOTE_FILE_TTL_DAYS`.
- **`oss`** — `OssStorage` (Aliyun OSS, `oss2` SDK): objects are uploaded under `<prefix>/<token>/<filename>`; response URLs are `bucket.sign_url`-generated pre-signed GETs (validity = `QUOTE_FILE_TTL_DAYS`). Setting `QUOTE_OSS_PUBLIC_BASE_URL` rewrites the host to a CDN or custom domain while preserving the signature. With the OSS backend, `GET /files/...` is no longer in the request path.

Both backends persist the locator (`file_token` / `object_key`) on `quote_render.file_token`; `render_to_file_ref` dereferences it per backend type when building the response.

#### `app/domain/pricing_baseline.py` — Runtime Baseline Codec

At request time, the XOR+SHA256 obfuscated `references/pricing_baseline_v5.obf` is decoded in memory using `PRICING_BASELINE_KEY` (ported from the legacy skill). Plaintext never touches disk. Strict mode forces the obf+key path; non-strict mode prefers obf but falls back to `data/pricing_baseline.json`; with both missing the service fails to start (no silent empty-items fallback — the root cause of the previously observed Haidilao quote bug).

#### `app/domain/pricing.py` — Pricing Algorithm

Ported from the legacy `build_quotation_config.py`. Packages use a `cost × 20` standard price combined with a deep discount factor (typical SaaS high-sticker model); add-on and HQ modules use a `cost × 1.20` / `cost × 1.50` cost-plus markup that protects margin even under deep package discounts. See [`docs/pricing-algorithm.md`](docs/pricing-algorithm.md) for details.

Entry point: `build_quotation_config(form_dict, baseline, product_catalog_path) → dict`

#### `app/domain/quote_service.py` — Business Logic Layer

`price_and_persist`, `render_format`, `build_preview`, `render_to_file_ref`, and related helpers. `POST /v1/quote` is composed entirely from these functions.

#### `app/persistence/` — SQLite Persistence

Three tables:

- `quote` — one row per quoted form (deduped by `(org, form_hash)`)
- `quote_render` — one row per generated file
- `approval` — up to one per quote; always `state = not_required` (approval flow was retired 2026-04-20; the table is retained for audit trail continuity)

Schema is created via `CREATE TABLE IF NOT EXISTS` in the FastAPI lifespan startup. No Alembic yet — UAT stage.

#### `app/api/quote.py` — Business Endpoint

`POST /v1/quote` — the service's single public business endpoint. A compound call: `price_and_persist → render(pdf) → render(xlsx) → render(json) → QuoteResponse`.

#### `app/auth.py` + `app/cli.py` — Token Management

`secrets.token_urlsafe(32)` generates a 256-bit random bearer; only `sha256(plaintext)` lands in the `api_token` table of `data/quote.db` (fields: `token_id / token_hash / org / created_at / expires_at / revoked_at / last_used_on`). The plaintext is printed exactly once on creation. Each request looks up the hash filtered by `revoked_at` and `expires_at`, then uses `hmac.compare_digest` for timing-safe comparison. `last_used_on` is updated at most once per token per UTC day (day-sampled via an in-process cache).

#### `app/audit.py` — Audit Logging

Each successful quote request appends one JSON line to `data/audit/YYYY-MM-DD.jsonl`. Fields include `ts`, `request_id`, `quote_id`, `org`, `token_id`, `brand`, `stores`, `package`, `discount`, `final`, `pricing_version`, `status`, `duration_ms`.

---

### Request Flow

```
quanlaidian-quote-skills
    │
    │ POST /v1/quote  {QuoteForm}
    │
    ▼
FastAPI → auth → schema → quote_service → pricing → render(pdf/xlsx/json) → storage → audit
                                              │
                                              ▼
                                       SQLite data/quote.db
                                       (quote / quote_render / approval)
```

The response `QuoteResponse` contains the preview plus three file URLs (pdf/xlsx/json). URLs are issued by the `storage` backend: under `local` they point at this service's `/files/...`; under `oss` they are OSS pre-signed URLs (optionally rewritten to a CDN host via `QUOTE_OSS_PUBLIC_BASE_URL`). Both carry a `QUOTE_FILE_TTL_DAYS` TTL.

---

### Ops Stack

| Component | Tool |
|---|---|
| ASGI server | uvicorn |
| Reverse proxy | nginx (TLS via certbot) |
| Process manager | systemd (`ops/systemd/quanlaidian-quote.service`) |
| Persistence | SQLite (`data/quote.db`) |
| File storage | Local disk (`local` backend) or Aliyun OSS (`oss` backend, `oss2` SDK) |
| Local file cleanup | cron (`ops/cron/cleanup-files.sh`; OSS objects are expired via bucket lifecycle rules) |
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
