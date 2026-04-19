# 定价算法说明

当前算法版本：`small-segment-v1`，核心逻辑在 [`app/domain/pricing.py`](../app/domain/pricing.py)。

## 1. 标准价计算

各商品分组的加价规则不同：

| 分组 | 标准价公式 |
|------|-----------|
| 门店套餐 | `底价 × 20`（底价占标准价 5%） |
| 门店增值模块 | `底价 × 1.10`（取整到 10 元） |
| 总部模块 | `底价 × 1.20`（取整到 10 元） |
| 实施服务 | `底价`（不加价） |
| 受保护商品（商管接口） | `底价`，且成交价系数固定为 1.0，不可打折 |

代码：`compute_standard_price_by_group()` in `app/domain/pricing.py`。

## 2. 成交价系数推荐

系统根据门店数量自动推荐成交价系数（即实付/标准价的比值），公式为连续线性递减：

```
系数 = 起步系数 − DISCOUNT_SLOPE_PER_STORE × (门店数 − 1)
```

- `DISCOUNT_SLOPE_PER_STORE = 0.05 / 19`（每增加 1 店的降幅，待 50+ 历史样本后回归校准）
- 起步锚点：轻餐 1800 元/店/年 → 系数 ≈ 0.237；正餐 3000 元/店/年 → 系数 ≈ 0.270

轻餐示例：

| 门店数 | 推荐系数 | 每店年费（元） |
|--------|---------|-------------|
| 1 | 0.2368 | 1,800 |
| 10 | 0.2132 | 1,620 |
| 20 | 0.1868 | 1,420 |
| 30 | 0.1605 | 1,220 |

实际商品单价 = 标准价 × 系数。代码：`recommend_base_deal_price_factor_smooth()`。

## 3. 折扣带宽约束

为防止极端折扣，系数会被限制在推荐值附近的带宽内（静态）：

- 轻餐 ±0.02
- 正餐 ±0.015

下界夹到 `max(0.01, ...)`，上界夹到 `min(1.0, ...)`。超出带宽的系数会被自动截断，截断记入 `pricing_info.auto_adjustments` 的 `bounded_clamp` 条目。

代码：`small_segment_bounds()`。

## 4. 历史样本修正

当 `factor_source == "auto"` 时，系统可利用历史成交数据对推荐系数做加权修正：

1. **过滤**：排除特殊审批单、赠品单、异常改价单、数据不完整、非标准套餐、跨桶、跨餐饮类型、缺失日期/系数等
2. **时间衰减权重**：12 个月窗口线性衰减，最低 0.1
3. **Winsorize**：裁剪 10–90 百分位外的离群值
4. **混合上限**（样本数分档）：

   | 有效样本数 | 历史权重上限 |
   |---|---|
   | < 6 | 0.00（不启用历史修正） |
   | 6–12 | 0.15 |
   | > 12 | 0.25 |

5. **最终系数**：`推荐系数 × (1 − cap) + 历史加权中位数 × cap`，随后仍需通过 §3 的带宽截断。

代码：`apply_history_adjustment()`。

## 5. 31 店及以上

当前实现在入口校验阶段直接拒绝，抛 `OutOfRangeError`：

```
message: "31店及以上暂不受理，请转人工定价"
hint:    "门店数量需在 1–30 之间"
```

代码：`recommend_base_deal_price_factor_smooth()` 与 `validate_form()`。大客户定价需人工评估后用 legacy 通道。

## 6. 商品单价计算（非套餐项的毛利保护）

`_compute_quote_unit_price()` 按模块分类分别处理：

| 模块分类 | 商品单价公式 | 说明 |
|---|---|---|
| 门店软件套餐 | `标准价 × 成交价系数` | 走成交价系数折扣 |
| 门店增值模块 | `min(底价 × 1.20, 标准价)` | 成本加成毛利保护，但永远不高于标准价 |
| 总部模块 | `min(底价 × 1.50, 标准价)` | 成本加成毛利保护，但永远不高于标准价 |
| 实施服务 / 其他 | `底价` | 不加价 |
| 受保护商品 | `底价` | 硬保护，不可改价 |

`min(…, 标准价)` 兜底是在回归修复中加入的：未配置基线或基线被覆盖为目录价的情况下，避免成交价系数高于 1 的反转场景。

## 7. pricing_info 字段说明

报价配置的 `pricing_info` 字段记录完整定价过程：

| 字段 | 含义 |
|------|------|
| `algorithm_version` | 算法版本（当前 `small-segment-v1`） |
| `route_strategy` | `small-segment` / `legacy` / `unsupported` |
| `route_reason` | 路由选择原因 |
| `base_factor` | 推荐基础系数 |
| `bounded_range` | 允许的系数范围 `[low, high]` |
| `final_factor` | 最终采用的系数 |
| `deal_price_factor_source` | 来源：`auto` / `deal_price_factor` / `成交价系数` / `折扣(兼容转换)` |
| `auto_adjustments` | 自动调整记录（历史修正、带宽截断、受保护商品绕过等） |
| `history_sample_count` | 有效历史样本数 |
| `history_weight` | 历史数据实际混合权重 |
| `history_anchor` | 历史加权中位数 |
| `history_window_months` | 历史窗口（月） |
| `history_filtered_reason_summary` | 历史样本过滤原因统计 |
| `legacy_factor` | 旧算法推荐系数（对照用） |
| `new_vs_legacy_factor_delta` | 新旧算法差值 |
| `approval_required` | 是否需要审批 |
| `approval_reason` | 触发审批的原因列表 |
| `manual_override_audit` | 人工改价审计记录 |
| `protected_item_bypass` | 是否存在受保护商品绕过 |
| `small_segment_enabled` | 是否启用小段路由 |

## 8. 基线加载与模糊解码

报价必须加载价格基线（底价数据）。基线文件有两种形式：

- **混淆形式**（生产推荐）：`references/pricing_baseline_v5.obf`，由 `PRICING_BASELINE_KEY` 解密，运行时解码到内存，不落盘明文。
- **明文形式**：`data/pricing_baseline.json`，仅用于开发/测试或应急回退（gitignored）。

优先级：
1. `PRICING_BASELINE_STRICT=1` 时，强制走 obf+密钥路径，否则启动失败。
2. 非 strict 模式下：优先用 obf+密钥；否则回退到明文；两者均缺失则抛错（不再静默 fallback 到空 items）。

代码：`load_baseline()` in `app/domain/pricing_baseline.py`。
