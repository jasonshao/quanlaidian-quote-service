# Changelog

本仓库的用户可感知变更记录。客户端调用 `GET /healthz` 可获取当前线上版本(`service_version`)。

版本号遵循 [SemVer](https://semver.org/lang/zh-CN/);维护流程见 [`README.md`](README.md) "发版与变更日志"章节。

## 1.1.0 (2026-04-26)

### Features

- [#15] 客户报价单支持电子发票税号捆绑;阶梯对比页改为 9 列布局(锚点价 + 上锚点价并列展示)
- [#17] 总部模块白名单:品牌联名、SCRM 默认 qty=1,不再因缺少 quantity_field 配置而失败
- [#19][#20] README/API 文档大幅重写,面向 `quanlaidian-quote-skills` 集成方
- [#21] 配置层去掉硬编码 `api.quanlaidian.com`,改用 `<your-api-host>` 占位 + `QUOTE_API_URL` 环境变量

### Changes

- 大客户段(31–300 店)启用阶梯对比报价路由;`pricing_info.route_strategy` 区分 `small-segment` / `large-segment` / `legacy`
- [#22] 阶梯对比表移除"折算单店年费"行,简化对外口径

### Fixes

- [#23] `/v1/quote` 顶层 `pricing_version` 返回**实际路由**对应版本(`small-segment-v2.3` / `large-segment-v1` / `legacy-v1`),不再恒等于全局 `PRICING_VERSION` 常量
- [#24] xlsx 水印从 `AbsoluteAnchor` 浮动图层迁移到 Excel 页眉水印,客户在普通编辑视图下双击单元格不再被图层拦截;打印 / 页面布局视图 / 导出 PDF 时水印照常显示

### Ops

- [#18] 加入 GitLab CI 模板(python docker + autodeploy)
- [#16] 隔离 worktree-local `.claude/` 配置,不再误入 git

## 1.0.0 (2026-04 初版)

初始版本——客户端瘦身、服务端独占定价/渲染/审计的架构落地。

- 报价定价算法、`pricing_baseline` 价格基线均落到本仓库
- PDF / XLSX / JSON 三格式报价单服务端渲染
- SQLite 持久化 `quote` / `quote_render` / `approval` / `api_token`
- 审计日志按日 jsonl 滚动到 `data/audit/`
- 多组织 token 鉴权(`org` 字段隔离,跨组织访问 404)
- 文件存储抽象:本地 / 阿里云 OSS 两种 backend
