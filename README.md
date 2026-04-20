# 全来店报价服务

> [English version →](README.en.md)

全来店产品线的服务端报价系统：独占定价算法、价格基线、PDF/XLSX 渲染、文件存储、审计日志和审批工作流，把客户端缩成一段 HTTP 包装。

**版本：** 1.0.0　**运行环境：** Python 3.10+ · FastAPI · uvicorn · SQLite

---

## 第一部分 — Agent 调用指南

> 这一节写给调用本服务的 AI Agent（如 OpenClaw）。涵盖鉴权、API 端点、请求/响应结构和错误处理。

### Base URL

```
https://api.quanlaidian.com
```

UAT 阶段可能会通过 IP 直连（见运维方提供的实际地址）。客户端以 `QUOTE_API_URL` 环境变量配置，避免硬编码。

### 鉴权

所有请求必须在 `Authorization` 头中携带 Bearer token：

```
Authorization: Bearer <token>
```

Token 由服务端管理员按组织发放（`python -m app.cli add-token`）。缺失或错误返回 `HTTP 401`。所有 quote 资源按 `org` 隔离，跨组织访问返回 `HTTP 404`。

### 幂等（Idempotency-Key）

`POST /v1/quotes` 支持可选的 `Idempotency-Key` 请求头。相同 key + 相同 form → 返回同一 `quote_id`，供客户端做重试安全；相同 key + 不同 form → `400 OUT_OF_RANGE`（客户端 bug，key 被复用）。不显式提供 key 时，服务端以 `(org, form 规范化哈希)` 去重，同组织重复提交同 form 仍然幂等。

响应头会回显 `X-Quote-ID` 和 `Idempotency-Key`。

---

## 报价资源接口（推荐）

### POST /v1/quotes — 算价+持久化

只跑定价算法并写入 `quote` 表，**不生成文件**。用于预览、需要审批前置、或客户端希望按需生成文件的场景。

**请求体：** 参见下方 [QuoteForm 字段表](#quoteform-字段)。

**响应 — HTTP 200：**

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

### GET /v1/quotes/{quote_id} — 读回已持久化的报价

包含 preview、approval 状态和已生成的文件列表。

**响应片段：**

```json
{
  "quote_id": "q_…",
  "org": "acme-sales",
  "preview": { /* 同上 */ },
  "approval": { /* 同上 */ },
  "renders": {
    "pdf": { "url": "…", "filename": "…", "expires_at": "…" },
    "xlsx": { "url": "…", "filename": "…", "expires_at": "…" }
  },
  "pricing_version": "small-segment-v2.3",
  "created_at": "2026-04-19T16:52:49.996645+00:00"
}
```

### POST /v1/quotes/{quote_id}/render/{format} — 按需渲染

`format ∈ {pdf, xlsx, json}`。首次调用生成文件，之后调用复用上次的 URL；带 `?force=1` 强制重新渲染。如果该报价 `approval.state` 为 `pending` 或 `rejected`，返回 `409 APPROVAL_PENDING`。

**响应 — HTTP 200：**

```json
{
  "url": "https://api.quanlaidian.com/files/<file_token>/海底捞火锅-全来店-报价单-20260420.pdf",
  "filename": "海底捞火锅-全来店-报价单-20260420.pdf",
  "expires_at": "2026-04-26T16:53:08Z"
}
```

### POST /v1/quotes/{quote_id}/explain — 成本/利润明细

内部口径接口 — 返回每个商品的底价、利润、毛利率。**谨慎向客户透出**。

**响应 — HTTP 200：**

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
  "pricing_info": { /* 完整定价元数据 */ },
  "internal_financials": { "quote_total": 115119, "cost_total": 29876, "profit_total": 85243, "profit_rate": 74.05 }
}
```

### POST /v1/quotes/{quote_id}/approvals/decide — 审批决策

当 `approval.required` 为 true 时需要主管决策。

**请求体：**

```json
{
  "decision": "approve",
  "reason": "VIP 客户 CEO 特批",
  "approver": "总监王五"
}
```

`decision` 必须是 `"approve"` 或 `"reject"`。决策后 `render` 端点放行（approve）或继续返回 `409`（reject，终态）。

---

## 其他接口

### GET /v1/catalog

获取产品目录 JSON。可选 query：`meal_type=轻餐|正餐`。

**响应：**

```json
{
  "pricing_version": "small-segment-v2.3",
  "meal_type": "正餐",
  "items": [
    { "meal_type": "正餐", "group": "门店套餐", "name": "正餐连锁营销旗舰版", "unit": "店/年", "price": 15900 }
  ]
}
```

skill 端推荐启动时从这里拉，**不要**自己维护一份 `product_catalog.md` 副本 — 避免服务端调价与客户端预览漂移。

### POST /v1/quote — Legacy 单次报价（保留兼容 UAT 客户端）

一次调用里完成 算价+持久化+PDF+XLSX+JSON 渲染，返回 `QuoteResponse`。

- 需要审批的报价（factor 偏离推荐值过多、人工改价缺足够历史样本等）直接返回 `409 APPROVAL_PENDING`，客户端必须切到资源接口并走 `decide` 流程。
- 仍然支持 `Idempotency-Key`。

**响应片段：**

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

健康检查 — 无需鉴权。

```json
{ "status": "ok", "pricing_version": "small-segment-v2.3" }
```

### GET /files/{token}/{filename}

按 token 限定的 URL 下载已生成的文件。生产环境由 nginx 直接从磁盘提供（`alias data/files/`），此路由仅作为开发环境兜底。

---

## QuoteForm 字段

所有报价接口（`POST /v1/quotes` 和 legacy `POST /v1/quote`）共用：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `客户品牌名称` | string | ✅ | — | 客户品牌名称 |
| `餐饮类型` | string | ✅ | `"轻餐"` 或 `"正餐"` | 餐饮类型 |
| `门店数量` | integer | ✅ | 1 – 30 | 门店数量（31+ 直接 422，走人工定价）|
| `门店套餐` | string | ✅ | — | 套餐名，必须与 [`references/product_catalog.md`](references/product_catalog.md) 一致 |
| `门店增值模块` | string[] | ❌ | — | 可选门店增值模块 |
| `总部模块` | string[] | ❌ | — | 可选总部模块 |
| `配送中心数量` | integer | ❌ | ≥ 0，默认 0 | 配送中心数量 |
| `生产加工中心数量` | integer | ❌ | ≥ 0，默认 0 | 生产加工中心数量 |
| `成交价系数` | float | ❌ | 0.01 – 1.0 | 显式成交价系数。**显式提供时 `人工改价原因` 必填** |
| `人工改价原因` | string | ❌ | 非空 | 显式成交价系数时必填，用于审计留痕 |
| `是否启用阶梯报价` | boolean | ❌ | 默认 `false` | 启用阶梯报价 |
| `实施服务类型` | string | ❌ | — | 实施服务类型 |
| `实施服务人天` | integer | ❌ | ≥ 0，默认 0 | 实施服务人天 |

---

## 错误响应

所有错误共用一个信封：

```json
{
  "error": {
    "code": "APPROVAL_PENDING",
    "message": "quote q_… 需要审批后才能渲染/下发",
    "field": "<相关字段，可选>",
    "hint": "<提示，可选>",
    "request_id": "req_20260419165334_ac8dbe5f",
    "quote_id": "q_…",                        // 仅 APPROVAL_PENDING
    "approval_reasons": [ "…" ]                // 仅 APPROVAL_PENDING
  }
}
```

| HTTP | `code` | 触发原因 |
|---|---|---|
| 401 | — | 缺失或错误的 Bearer token |
| 404 | `NOT_FOUND` | quote 不存在或不属于当前 org |
| 409 | `APPROVAL_PENDING` | quote 需要审批，且当前 `state` 不是 `approved` |
| 422 | `INVALID_FORM` | 请求体不符合 schema（缺必填字段、值越界等）|
| 400 | `OUT_OF_RANGE` | 业务规则越界（缺人工改价原因、Idempotency-Key 冲突等）|
| 500 | `PRICING_FAILED` | 定价算法错误（如基线或产品目录缺失）|
| 500 | `RENDER_FAILED` | PDF 或 XLSX 生成错误 |
| 500 | `INTERNAL_ERROR` | 未预期的服务端错误 |

---

## 薄客户端（OpenClaw 技能）

配套技能仓库 [`quanlaidian-quote-skills`](https://github.com/jasonshao/quanlaidian-quote-skills) 提供薄客户端。配置两个环境变量即可调用：

```bash
export QUOTE_API_TOKEN=<your_token>
export QUOTE_API_URL=https://api.quanlaidian.com
```

---

## 第二部分 — 项目说明与架构

### 背景

旧版报价系统是分发到每台用户 OpenClaw 节点的"胖技能"：155 KB Python + 加密价格数据 + 解密 key + 飞书凭据，全部在每台用户机器上。带来的问题：

- 飞书 API 在用户节点偶发失败
- 自动升级后定价算法被破坏（依赖 / 基线 / 算法版本漂移）
- 安全暴露：定价 key 和凭据散落在所有客户端

本服务是该重构的服务端那一半。所有敏感逻辑收归服务端：定价算法、价格基线（运行时 XOR+SHA256 混淆解码，明文不落盘）、PDF/XLSX 生成、文件存储、SQLite 持久化、审计日志、审批工作流。

---

### 仓库结构

```
quanlaidian-quote-service/
├── pyproject.toml
├── .env.example                       # 含 PRICING_BASELINE_KEY / STRICT
├── app/
│   ├── main.py                        # FastAPI 入口 + lifespan 初始化 SQLite
│   ├── config.py                      # Pydantic Settings（前缀 QUOTE_）
│   ├── auth.py                        # Bearer token 校验
│   ├── audit.py                       # 追加式 JSONL 审计
│   ├── errors.py                      # 统一异常类 + 处理器
│   ├── storage.py                     # LocalDiskStorage（返回 file_token）
│   ├── cli.py                         # Token 管理 CLI
│   ├── api/
│   │   ├── quote.py                   # POST /v1/quote (legacy)
│   │   ├── quotes.py                  # /v1/quotes/* 资源端点
│   │   ├── catalog.py                 # GET /v1/catalog
│   │   ├── files.py                   # GET /files/{token}/{filename}
│   │   └── health.py                  # GET /healthz
│   ├── domain/
│   │   ├── schema.py                  # Pydantic 请求/响应模型
│   │   ├── pricing.py                 # 定价算法（small-segment-v2.3）
│   │   ├── pricing_baseline.py        # .obf 运行时解码 + 明文回退
│   │   ├── quote_service.py           # 算价/渲染/审批业务逻辑（legacy + 资源端点共享）
│   │   ├── render_pdf.py              # reportlab PDF
│   │   └── render_xlsx.py             # openpyxl XLSX
│   └── persistence/                   # SQLite 持久层（B0）
│       ├── db.py                      # 连接 + schema 初始化
│       ├── models.py                  # Quote / QuoteRender / Approval 数据类
│       └── quote_repo.py              # CRUD + 幂等逻辑
├── data/                              # 运行时状态（不入 VCS）
│   ├── quote.db                       # SQLite: quote / quote_render / approval
│   ├── pricing_baseline.json          # 明文基线（可选，obf 作为首选）
│   ├── tokens.json                    # SHA-256 哈希 token
│   ├── fonts/                         # CJK 字体（PDF 渲染用）
│   ├── files/                         # 生成的文件（7 天 TTL）
│   └── audit/                         # YYYY-MM-DD.jsonl 审计
├── references/
│   ├── product_catalog.md             # 产品目录（对客标价）
│   └── pricing_baseline_v5.obf        # 混淆基线（生产首选）
├── docs/
│   └── pricing-algorithm.md           # 定价算法说明（审计参考）
├── tests/                             # 77 个测试全绿
│   ├── conftest.py
│   ├── fixtures/
│   ├── test_api.py                    # 端点集成测试（含新资源端点）
│   ├── test_persistence.py            # SQLite 单元测试
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
    ├── migrate_baseline.py            # .obf → 明文 JSON（应急）
    ├── obfuscate_baseline.py          # 明文 JSON → .obf（调价后重加密）
    ├── extract_baseline_from_xlsx.py  # 底价 xlsx → 明文 JSON
    └── runbook.md                     # 部署运维手册
```

---

### 模块职责

#### `app/config.py` — Settings

Pydantic `BaseSettings` 从环境变量读取配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QUOTE_API_BASE_URL` | `https://api.quanlaidian.com` | 公开 base URL |
| `QUOTE_DATA_ROOT` | `data` | 文件、token、DB、审计的根目录 |
| `QUOTE_FILE_TTL_DAYS` | `7` | 生成文件的过期天数 |
| `QUOTE_LOG_LEVEL` | `INFO` | 日志级别 |
| `PRICING_BASELINE_KEY` | — | `.obf` 基线解密密钥（生产必填）|
| `PRICING_BASELINE_STRICT` | `0` | 设为 `1` 时拒绝明文回退，只走 obf+key（生产推荐）|

#### `app/domain/pricing_baseline.py` — 基线运行时解码

运行时用 `PRICING_BASELINE_KEY` 解密 `references/pricing_baseline_v5.obf`（XOR+SHA256 混淆，从 legacy 移植），明文不落盘。strict 模式强制走 obf+key；非 strict 时优先 obf，回退到 `data/pricing_baseline.json`，二者都缺直接启动失败（不再静默 fallback 到空 items — 旧版海底捞 bug 的根因）。

#### `app/domain/pricing.py` — 定价算法

从 legacy `build_quotation_config.py` 移植。套餐 `cost × 20` 作标准价 + 成交价系数深折的 SaaS 定价模型；增值模块 `cost × 1.20`、总部模块 `cost × 1.50` 走成本加成毛利保护。详细算法见 [`docs/pricing-algorithm.md`](docs/pricing-algorithm.md)。

入口：`build_quotation_config(form_dict, baseline, product_catalog_path) → dict`

#### `app/domain/quote_service.py` — 业务逻辑层

`price_and_persist`、`render_format`、`build_preview`、`build_breakdown`、`approval_to_state` 等函数。legacy `/v1/quote` 端点和资源端点共享同一套业务函数，保证行为一致。

#### `app/persistence/` — SQLite 持久层

三张表：

- `quote`：每次定价一行（按 `org + form_hash` 去重，可选 `idempotency_key`）
- `quote_render`：每次文件生成一行
- `approval`：每个 quote ≤ 1 行，状态机 `not_required → pending → approved | rejected`

`CREATE TABLE IF NOT EXISTS` 方式在 FastAPI lifespan 启动时初始化。UAT 阶段未用 Alembic。

#### `app/api/quotes.py` — 资源端点路由

五个资源端点：创建、读取、按需渲染、明细、审批决策。审批未通过时 render 返回 409。

#### `app/api/quote.py` — Legacy 端点

`POST /v1/quote` 仍在，但现在只是 compound call：`price_and_persist → render(pdf) → render(xlsx) → render(json) → QuoteResponse`。遇审批需要直接 409，鼓励客户端切到资源接口。

#### `app/api/catalog.py` — 产品目录端点

`GET /v1/catalog` 暴露 `product_catalog.md` 的解析结果，作为 skill 端的单一真实源。

#### `app/auth.py` + `app/cli.py` — Token

`secrets.token_urlsafe(32)` 生成原始 token，只存 `sha256` 哈希到 `data/tokens.json`，明文仅创建时打印一次。每次请求 `hmac.compare_digest` 比对，时序安全。

#### `app/audit.py` — 审计日志

每条成功的报价请求、审批决策追加一行 JSON 到 `data/audit/YYYY-MM-DD.jsonl`。字段：`ts`、`request_id`、`quote_id`、`org`、`brand`、`stores`、`package`、`discount`、`final`、`pricing_version`、`status`、`duration_ms`。

---

### 请求流水线

**资源化新路径**（推荐）：

```
OpenClaw agent
    │
    │ POST /v1/quotes  {QuoteForm}         → 算价，写入 quote + approval 表
    │ GET  /v1/quotes/{id}                 → 读回
    │ POST /v1/quotes/{id}/approvals/decide → 主管审批（如需要）
    │ POST /v1/quotes/{id}/render/{format}  → 按需渲染
    │
    ▼
FastAPI → auth → schema → quote_service → pricing → render → storage → audit
                                              │
                                              ▼
                                       SQLite data/quote.db
                                       (quote / quote_render / approval)
```

**Legacy 路径**（向下兼容）：

```
POST /v1/quote → price_and_persist → render(pdf) + render(xlsx) + render(json)
               → 若 approval.pending: 409 APPROVAL_PENDING
               → 否则 200 QuoteResponse (3 个文件 URL)
```

---

### 运维栈

| 组件 | 工具 |
|---|---|
| WSGI 服务器 | uvicorn |
| 反向代理 | nginx（TLS 用 certbot）|
| 进程管理 | systemd（`ops/systemd/quanlaidian-quote.service`）|
| 持久化 | SQLite（`data/quote.db`）|
| 文件清理 | cron（`ops/cron/cleanup-files.sh`）|
| 基线维护 | `ops/extract_baseline_from_xlsx.py` → `ops/obfuscate_baseline.py`（调价后重加密）|

详细的首次部署、token 发放、日志查看、回滚、基线轮换见 [`ops/runbook.md`](ops/runbook.md)。

---

### 开发环境

```bash
git clone <repo>
cd quanlaidian-quote-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # 填入 PRICING_BASELINE_KEY
uvicorn app.main:app --reload
```

跑测试：

```bash
pytest tests/ -v
# 77 个测试全部通过
```

发放开发 token：

```bash
python -m app.cli add-token --org dev
# 打印明文 token — 用作客户端的 QUOTE_API_TOKEN 环境变量
```
