# 全来店报价服务

> [English version →](README.en.md)

全来店产品线的服务端报价系统：独占定价算法、价格基线、PDF/XLSX 渲染、文件存储和审计日志，把客户端缩成一段 HTTP 包装。

**版本：** 1.0.0　**运行环境：** Python 3.10+ · FastAPI · uvicorn

---

## 第一部分 — Agent 调用指南

> 这一节写给调用本服务的 AI Agent（如 OpenClaw）。涵盖鉴权、API 端点、请求/响应结构和错误处理。

### Base URL

```
https://api.quanlaidian.com
```

### 鉴权

所有请求必须在 `Authorization` 头中携带 Bearer token：

```
Authorization: Bearer <token>
```

Token 由服务端管理员按组织发放（`python -m app.cli add-token`）。缺失或错误返回 `HTTP 401`。

---

### POST /v1/quote

生成一份报价单。返回 JSON 摘要 + PDF / XLSX / JSON 配置三份文件的限时下载 URL。

#### 请求

**请求头：**

| Header | 值 |
|---|---|
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <token>` |

**请求体（JSON）—— 全部字段：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `客户品牌名称` | string | ✅ | — | 客户品牌名称 |
| `餐饮类型` | string | ✅ | `"轻餐"` 或 `"正餐"` | 餐饮类型 |
| `门店数量` | integer | ✅ | 1 – 30 | 门店数量 |
| `门店套餐` | string | ✅ | — | 套餐名，必须与 [`references/product_catalog.md`](references/product_catalog.md) 一致，如 `"轻餐连锁营销旗舰版"` / `"正餐连锁营销旗舰版"` |
| `门店增值模块` | string[] | ❌ | — | 可选门店增值模块 |
| `总部模块` | string[] | ❌ | — | 可选总部模块 |
| `配送中心数量` | integer | ❌ | ≥ 0，默认 0 | 配送中心数量 |
| `生产加工中心数量` | integer | ❌ | ≥ 0，默认 0 | 生产加工中心数量 |
| `成交价系数` | float | ❌ | 0.01 – 1.0 | 显式成交价系数（覆盖自动推荐折扣）。**显式提供时 `人工改价原因` 必填**，否则返回 `400 OUT_OF_RANGE` |
| `人工改价原因` | string | ❌ | 非空 | 显式提供 `成交价系数` 时必填，用于审计留痕 |
| `是否启用阶梯报价` | boolean | ❌ | 默认 `false` | 启用阶梯报价 |
| `实施服务类型` | string | ❌ | — | 实施服务类型 |
| `实施服务人天` | integer | ❌ | ≥ 0，默认 0 | 实施服务人天 |

**最小示例：**

```json
{
  "客户品牌名称": "示例品牌",
  "餐饮类型": "轻餐",
  "门店数量": 5,
  "门店套餐": "轻餐连锁营销旗舰版"
}
```

**完整示例：**

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

#### 响应 — HTTP 200

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

**字段说明：**
- `prices` 是以元（CNY）为单位的整数，例如 `408000` = ¥408,000。
- `discount` 是最终成交价系数，例如 `0.85` = 85%。
- 文件 URL **有效期 7 天**，请尽快下载并交付给客户。
- `pricing_version` 标识使用的基线数据版本，请在客户沟通中保留以供审计追溯。

#### 错误响应

所有错误共用一个信封：

```json
{
  "error": {
    "code": "<ERROR_CODE>",
    "message": "可读的错误描述",
    "field": "<相关字段名>",
    "hint": "<可选提示>",
    "request_id": "req_20260419143022_a1b2c3d4"
  }
}
```

| HTTP | `code` | 触发原因 |
|---|---|---|
| 401 | — | 缺失或错误的 Bearer token |
| 422 | `INVALID_FORM` | 请求体不符合 schema（缺必填字段、值越界等） |
| 400 | `OUT_OF_RANGE` | 业务规则越界（如门店数量 > 30、缺人工改价原因等） |
| 500 | `PRICING_FAILED` | 定价算法错误（如基线或产品目录缺失） |
| 500 | `RENDER_FAILED` | PDF 或 XLSX 生成错误 |
| 500 | `INTERNAL_ERROR` | 未预期的服务端错误 |

---

### GET /healthz

健康检查 — 无需鉴权。

**响应：**
```json
{
  "status": "ok",
  "pricing_version": "small-segment-v2.3"
}
```

---

### GET /files/{token}/{filename}

按 token 限定的 URL 下载已生成的文件。生产环境由 nginx 直接从磁盘提供（`alias data/files/`），此路由仅作为开发环境兜底。

---

### 薄客户端（OpenClaw 技能）

配套技能仓库 [`quanlaidian-quote-skills`](https://github.com/jasonshao/quanlaidian-quote-skills) 提供现成的薄客户端（`scripts/quote.py`，45 行，零额外依赖）。配置两个环境变量即可调用：

```bash
export QUOTE_API_TOKEN=<your_token>
export QUOTE_API_URL=https://api.quanlaidian.com
python3 scripts/quote.py --form form_submission.json
```

脚本会打印 JSON 响应和三个下载 URL。

---

## 第二部分 — 项目说明与架构

### 背景

旧版报价系统是分发到每台用户 OpenClaw 节点的"胖技能"：155 KB Python + 加密价格数据 + 解密 key + 飞书凭据，全部在每台用户机器上。带来的问题：

- 飞书 API 在用户节点偶发失败
- 自动升级后定价算法被破坏（依赖 / 基线 / 算法版本漂移）
- 安全暴露：定价 key 和凭据散落在所有客户端

本服务是该重构的服务端那一半。所有敏感逻辑收归服务端：定价算法、价格基线、PDF/XLSX 生成、文件存储、审计日志。客户端缩成 45 行 HTTP 包装。

---

### 仓库结构

```
quanlaidian-quote-service/
├── pyproject.toml              # 项目元数据与依赖
├── .env.example                # 环境变量模板
├── .gitignore
├── app/
│   ├── main.py                 # FastAPI 入口装配 + 中间件
│   ├── config.py               # Pydantic Settings（前缀 QUOTE_）
│   ├── auth.py                 # Bearer token 校验（sha256 + hmac）
│   ├── audit.py                # 追加式 JSONL 审计日志
│   ├── errors.py               # 统一异常类 + 处理器
│   ├── storage.py              # 存储 Protocol + LocalDiskStorage
│   ├── cli.py                  # Token 管理 CLI
│   ├── api/
│   │   ├── quote.py            # POST /v1/quote 路由
│   │   ├── files.py            # GET /files/{token}/{filename}（开发兜底）
│   │   └── health.py           # GET /healthz
│   └── domain/
│       ├── schema.py           # Pydantic 请求/响应模型
│       ├── pricing.py          # 定价算法（移植自 build_quotation_config.py）
│       ├── pricing_baseline.py # 加载明文 pricing_baseline.json
│       ├── render_pdf.py       # PDF 生成（reportlab，移植自 generate_quotation.py）
│       └── render_xlsx.py      # XLSX 生成（openpyxl，移植自 generate_quotation.py）
├── data/
│   ├── pricing_baseline.json   # 价格基线数据 — 不入版本控制，手工部署
│   ├── tokens.json             # SHA-256 哈希后的 token 仓库
│   ├── fonts/                  # reportlab 用的 CJK 字体（不入 VCS）
│   ├── files/                  # 生成的输出文件（7 天 TTL，不入 VCS）
│   └── audit/                  # YYYY-MM-DD.jsonl 审计日志（不入 VCS）
├── references/
│   └── product_catalog.md      # 产品目录（定价算法读取）
├── tests/
│   ├── conftest.py             # 测试 fixture（TestClient、临时 data_root、测试 token）
│   ├── fixtures/               # 表单 JSON 示例
│   ├── test_schema.py
│   ├── test_storage.py
│   ├── test_auth.py
│   ├── test_errors.py
│   ├── test_pricing.py
│   ├── test_render.py
│   └── test_api.py             # 46 个集成测试 — 全部通过
└── ops/
    ├── nginx.conf.example      # 反向代理配置（TLS、文件服务）
    ├── systemd/
    │   └── quanlaidian-quote.service
    ├── cron/
    │   └── cleanup-files.sh    # 删除 7 天前的旧文件
    ├── migrate_baseline.py     # 解密 .obf 基线 → 明文 JSON
    └── runbook.md              # 部署与运维手册
```

---

### 模块职责

#### `app/config.py` — Settings

Pydantic `BaseSettings` 从环境变量读取所有配置，前缀 `QUOTE_`，并加载 `.env` 文件：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QUOTE_API_BASE_URL` | `https://api.quanlaidian.com` | 公开 base URL（用于拼装文件下载 URL）|
| `QUOTE_DATA_ROOT` | `data` | 文件、token、审计的根目录 |
| `QUOTE_FILE_TTL_DAYS` | `7` | 生成文件的清理过期天数 |
| `QUOTE_LOG_LEVEL` | `INFO` | 日志级别 |

#### `app/auth.py` + `app/cli.py` — Token 管理

Token 永不以明文存储。CLI 生成一个 `secrets.token_urlsafe(32)`，把它的 `sha256` hex 摘要存入 `data/tokens.json`，明文只打印一次：

```bash
python -m app.cli add-token --org "acme-sales"
# → Token for acme-sales: qlq_Xr9...  （仅显示一次，请妥善保存）
```

每次请求 `auth.py` 对 Bearer token 取 hash，用 `hmac.compare_digest` 做时序安全的对比。原始 token 不会落盘。

#### `app/errors.py` — 统一错误模型

三个自定义异常类（`OutOfRangeError`、`PricingError`、`RenderError`）通过 FastAPI 异常处理器映射为结构化 JSON。每个错误响应都带 `request_id`、`code`、`message`，可选 `field` 和 `hint`。catch-all 处理器保证不会泄漏 Python traceback 给客户端。

#### `app/storage.py` — 文件存储

`LocalDiskStorage` 把每个输出文件保存到一个随机 32 字节 URL-safe token 子目录下：

```
data/files/<token>/<filename>
```

公开 URL 是 `{api_base_url}/files/<token>/<filename>`。生产环境 nginx 通过 `alias` 直接服务这个路径，绕开 FastAPI 的文件 IO。`expires_at` 时间戳是 `now + file_ttl_days`，实际删除由 cron 任务负责。

#### `app/audit.py` — 审计日志

每条成功的报价请求向 `data/audit/YYYY-MM-DD.jsonl` 追加一行 JSON。字段：`ts`、`request_id`、`org`、`brand`、`stores`、`package`、`discount`、`final`、`pricing_version`、`status`、`duration_ms`。文件名按日期天然轮转，无需 logrotate。

#### `app/domain/schema.py` — Pydantic 模型

请求：`QuoteForm` — 13 字段，含校验：`门店数量 ∈ [1, 30]`、`成交价系数 ∈ [0.01, 1.0]`、`成交价系数` 显式提供时跨字段要求 `人工改价原因`。

响应：`QuoteResponse` → `preview: QuotePreview` + `files: dict[str, FileRef]` + `pricing_version`。

错误：`ErrorResponse` → `error: ErrorDetail`。

#### `app/domain/pricing.py` — 定价算法

从遗留 `build_quotation_config.py`（963 行）逐行移植。改动只有：用 Pydantic 模型字段访问代替 dict 下标，用明文 JSON 基线代替混淆的 `.obf` 文件，业务规则失败抛 `PricingError` / `OutOfRangeError`。

入口：`build_quotation_config(form_dict, baseline, product_catalog_path) → dict`

返回的 `dict` 是完整的报价配置 — 同一份结构既给 PDF 和 XLSX 渲染器消费，也作为 `.json` 下载保存。

#### `app/domain/render_pdf.py` + `app/domain/render_xlsx.py` — 文件渲染

两个模块都从遗留 `generate_quotation.py`（1,735 行）按输出格式拆分。入口：

- `render_pdf(config: dict, fonts_dir: Path) → bytes` — 用 reportlab，返回 PDF 字节流
- `render_xlsx(config: dict) → bytes` — 用 openpyxl，通过 `io.BytesIO` 返回 XLSX 字节流

CJK 字符所需的字体在 `render_pdf` 内部注册。字体从 `data/fonts/` 加载（不入 VCS，需单独部署）。

#### `app/api/quote.py` — 路由处理

`POST /v1/quote` 在一次请求中编排完整流水线：

1. 解析并校验 `QuoteForm`（Pydantic，失败自动抛 `INVALID_FORM`）
2. 通过 `Depends(verify_token(...))` 鉴权
3. 生成 `request_id`
4. 从磁盘加载定价基线和产品目录
5. 跑 `build_quotation_config` → config dict
6. 渲染 PDF 和 XLSX
7. 通过 `LocalDiskStorage` 保存全部三份文件（PDF / XLSX / JSON）
8. 从 config 构建 `QuotePreview`
9. 写审计日志
10. 返回 `QuoteResponse`

---

### 请求流水线

```
OpenClaw agent
    │
    │  POST /v1/quote
    │  Authorization: Bearer <token>
    │  {QuoteForm JSON}
    ▼
nginx (TLS 终结)
    │
    ▼
FastAPI app (uvicorn, 127.0.0.1:8000)
    │
    ├─ auth.py: 校验 Bearer token (sha256 + hmac)
    ├─ schema.py: 校验 QuoteForm
    ├─ pricing.py: 构建报价配置 (baseline + product_catalog)
    ├─ render_pdf.py: 生成 PDF 字节流
    ├─ render_xlsx.py: 生成 XLSX 字节流
    ├─ storage.py: 把 PDF + XLSX + JSON 存到 data/files/<token>/
    ├─ audit.py: 追加到 data/audit/YYYY-MM-DD.jsonl
    └─ 返回 QuoteResponse (preview + 3 个文件 URL)

    │ GET /files/<token>/<filename>
    ▼
nginx (直接服务 data/files/，7 天过期头)
```

---

### 运维栈

| 组件 | 工具 |
|---|---|
| WSGI 服务器 | uvicorn (2 workers) |
| 反向代理 | nginx（TLS 用 certbot，文件服务用 `alias`）|
| 进程管理 | systemd（`ops/systemd/quanlaidian-quote.service`）|
| 文件清理 | cron（`ops/cron/cleanup-files.sh`，`find -mtime +7`）|
| 基线迁移 | `ops/migrate_baseline.py`（解密 `.obf` → 明文 JSON）|

详细的首次部署、token 发放、日志查看、回滚流程见 [`ops/runbook.md`](ops/runbook.md)。

---

### 开发环境

```bash
git clone <repo>
cd quanlaidian-quote-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # 按需修改
cp data/pricing_baseline.example.json data/pricing_baseline.json  # 填入真实数据
uvicorn app.main:app --reload
```

跑测试：

```bash
pytest tests/ -v
# 46 个测试全部通过
```

发放开发 token：

```bash
python -m app.cli add-token --org dev
# 打印明文 token — 用作客户端的 QUOTE_API_TOKEN 环境变量
```
