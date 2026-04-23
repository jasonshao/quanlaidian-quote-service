# 全来店报价服务

> [English version →](README.en.md)

全来店产品线的服务端报价系统：独占定价算法、价格基线、PDF/XLSX 渲染、文件存储和审计日志，把客户端缩成一段 HTTP 包装。

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

Token 由服务端管理员按组织发放（`python -m app.cli add-token --org <name>`，默认 180 天过期，`--no-expire` 可覆盖）。Token 存储在 `quote.db` 的 `api_token` 表中，服务端仅保存 `sha256(plaintext)`。缺失 / 错误 / 吊销 / 过期均返回 `HTTP 401`。所有 quote 资源按 `org` 隔离，跨组织访问返回 `HTTP 404`。

Token 运维命令：

```bash
python -m app.cli list-tokens                  # 列出所有 token（不打印 hash）
python -m app.cli revoke-token --id tok_xxxx   # 吊销
python -m app.cli migrate-tokens-json          # 一次性：把旧 data/tokens.json 迁入 api_token 表
```

---

## 业务接口

### POST /v1/quote — 算价 + 渲染 PDF/XLSX/JSON

唯一对外的报价接口。一次调用里完成：定价 → 持久化 → 生成 PDF/XLSX/JSON 三份文件，返回 preview + 三个下载链接。

同 `(org, 规范化 form)` 幂等：重复提交同一份表单，服务端返回同一 `quote_id`，不会产生重复 DB 行。

**请求体：** 参见下方 [QuoteForm 字段表](#quoteform-字段)。

**响应片段 — HTTP 200：**

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

## 运维接口

### GET /healthz

健康检查 — 无需鉴权。

```json
{ "status": "ok", "pricing_version": "small-segment-v2.3" }
```

### GET /files/{token}/{filename}

按 token 限定的 URL 下载已生成的文件。生产环境由 nginx 直接从磁盘提供（`alias data/files/`），此路由仅作为开发环境兜底。不是销售/客户端直接调用的接口，通常由 `POST /v1/quote` 响应里的 `files[*].url` 引导访问。

---

## QuoteForm 字段

`POST /v1/quote` 请求体字段：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `客户品牌名称` | string | ✅ | — | 客户品牌名称 |
| `餐饮类型` | string | ✅ | `"轻餐"` 或 `"正餐"` | 餐饮类型 |
| `门店数量` | integer | ✅ | 1 – 300 | 门店数量(301+ 直接 422 走人工定价;31-300 进入大客户段,主报价按下锚点生成 + 阶梯对比页,详见 [定价算法 §5](docs/pricing-algorithm.md)) |
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
    "code": "OUT_OF_RANGE",
    "message": "具体错误说明",
    "field": "<相关字段，可选>",
    "hint": "<提示，可选>",
    "request_id": "req_20260419165334_ac8dbe5f"
  }
}
```

| HTTP | `code` | 触发原因 |
|---|---|---|
| 401 | — | 缺失或错误的 Bearer token |
| 422 | `INVALID_FORM` | 请求体不符合 schema（缺必填字段、值越界等）|
| 400 | `OUT_OF_RANGE` | 业务规则越界（如提供 `成交价系数` 但缺 `人工改价原因`）|
| 500 | `PRICING_FAILED` | 定价算法错误（如基线或产品目录缺失）|
| 500 | `RENDER_FAILED` | PDF 或 XLSX 生成错误 |
| 500 | `INTERNAL_ERROR` | 未预期的服务端错误 |

---

## 薄客户端（OpenClaw 技能）

配套技能仓库 [`quanlaidian-quote-skills`](https://github.com/jasonshao/quanlaidian-quote-skills) 提供薄客户端。配置两个环境变量即可调用：

```bash
export QUOTE_API_TOKEN=<your_token>
export QUOTE_API_URL=https://<your-api-host>
```

---

## 第二部分 — 项目说明与架构

### 背景

旧版报价系统是分发到每台用户 OpenClaw 节点的"胖技能"：155 KB Python + 加密价格数据 + 解密 key + 飞书凭据，全部在每台用户机器上。带来的问题：

- 飞书 API 在用户节点偶发失败
- 自动升级后定价算法被破坏（依赖 / 基线 / 算法版本漂移）
- 安全暴露：定价 key 和凭据散落在所有客户端

本服务是该重构的服务端那一半。所有敏感逻辑收归服务端：定价算法、价格基线（运行时 XOR+SHA256 混淆解码，明文不落盘）、PDF/XLSX 生成、文件存储、SQLite 持久化、审计日志。

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
│   │   ├── quote.py                   # POST /v1/quote
│   │   ├── files.py                   # GET /files/{token}/{filename}
│   │   └── health.py                  # GET /healthz
│   ├── domain/
│   │   ├── schema.py                  # Pydantic 请求/响应模型
│   │   ├── pricing.py                 # 定价算法（small-segment-v2.3）
│   │   ├── pricing_baseline.py        # .obf 运行时解码 + 明文回退
│   │   ├── quote_service.py           # 算价/渲染业务逻辑
│   │   ├── render_pdf.py              # reportlab PDF
│   │   └── render_xlsx.py             # openpyxl XLSX
│   └── persistence/                   # SQLite 持久层（B0）
│       ├── db.py                      # 连接 + schema 初始化
│       ├── models.py                  # Quote / QuoteRender / Approval 数据类
│       └── quote_repo.py              # CRUD + 幂等逻辑
├── data/                              # 运行时状态（不入 VCS）
│   ├── quote.db                       # SQLite: quote / quote_render / approval / api_token
│   ├── pricing_baseline.json          # 明文基线（可选，obf 作为首选）
│   ├── fonts/                         # CJK 字体（PDF 渲染用）
│   ├── files/                         # 生成的文件（7 天 TTL）
│   └── audit/                         # YYYY-MM-DD.jsonl 审计
├── references/
│   ├── product_catalog.md             # 产品目录（对客标价）
│   └── pricing_baseline_v5.obf        # 混淆基线（生产首选）
├── docs/
│   └── pricing-algorithm.md           # 定价算法说明（审计参考）
├── tests/                             # 所有测试全绿
│   ├── conftest.py
│   ├── fixtures/
│   ├── test_api.py                    # 端点集成测试
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
| `QUOTE_API_BASE_URL` | `https://<your-api-host>` | 公开 base URL（请向管理员获取实际地址） |
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

`price_and_persist`、`render_format`、`build_preview`、`render_to_file_ref` 等函数。`POST /v1/quote` 端点由这些函数组合而成。

#### `app/persistence/` — SQLite 持久层

三张表：

- `quote`：每次定价一行（按 `org + form_hash` 去重）
- `quote_render`：每次文件生成一行
- `approval`：每个 quote ≤ 1 行，固定 `state = not_required`（审批流 2026-04-20 业务下线后，此表保留只为审计留痕）

`CREATE TABLE IF NOT EXISTS` 方式在 FastAPI lifespan 启动时初始化。UAT 阶段未用 Alembic。

#### `app/api/quote.py` — 业务端点

`POST /v1/quote` — 服务对外暴露的唯一业务端点。内部是一次 compound call：`price_and_persist → render(pdf) → render(xlsx) → render(json) → QuoteResponse`。

#### `app/auth.py` + `app/cli.py` — Token

`secrets.token_urlsafe(32)` 生成 256-bit 随机 token,只存 `sha256(plaintext)` 到 `data/quote.db` 的 `api_token` 表(字段:`token_id / token_hash / org / created_at / expires_at / revoked_at / last_used_on`)。明文仅创建时打印一次。每次请求在表中按 hash 查活跃行(过滤 `revoked_at` 和 `expires_at`)并用 `hmac.compare_digest` 做常数时间比对。日粒度更新 `last_used_on`(进程内缓存去重,每 token/每 UTC 日最多一次写)。

#### `app/audit.py` — 审计日志

每条成功的报价请求追加一行 JSON 到 `data/audit/YYYY-MM-DD.jsonl`。字段：`ts`、`request_id`、`quote_id`、`org`、`token_id`、`brand`、`stores`、`package`、`discount`、`final`、`pricing_version`、`status`、`duration_ms`。

---

### 请求流水线

```
OpenClaw agent
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

响应 `QuoteResponse` 含 preview + 3 个文件 URL（pdf/xlsx/json），URL 由 `storage` 发放，带 7 天 TTL，到期由 cron 清理。

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
# 全部测试绿
```

发放开发 token：

```bash
python -m app.cli add-token --org dev
# 打印 token_id + 明文（明文只显示一次）
# 明文作为客户端的 QUOTE_API_TOKEN 环境变量
```

其他 token 管理命令：

```bash
python -m app.cli list-tokens
python -m app.cli revoke-token --id tok_xxxxxxxx
python -m app.cli add-token --org staging --expires-in 30d   # 自定义过期
python -m app.cli add-token --org admin --no-expire          # 永不过期
```
