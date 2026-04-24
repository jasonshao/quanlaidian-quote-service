#!/usr/bin/env python3
"""
Pricing algorithm — ported from build_quotation_config.py with minimal changes.

Changes from original:
1. Removed `from scripts.pricing_baseline_codec import load_baseline_from_files`
2. `load_pricing_baseline()` removed (caller provides baseline dict)
3. `load_product_catalog()` requires explicit `path` parameter
4. Module-level path constants removed (ROOT_DIR, REFERENCES_DIR, etc.)
5. `build_quotation_config()` signature changed to accept baseline & product_catalog_path
6. `raise ValueError` for 31+ stores replaced with OutOfRangeError
7. `main()` / argparse removed
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.domain.pricing_baseline import PRICING_VERSION
from app.errors import OutOfRangeError

SMALL_SEGMENT_MAX_STORES = 30
LARGE_SEGMENT_MAX_STORES = 300
DEFAULT_SMALL_SEGMENT_ENABLED = True
HISTORY_WINDOW_MONTHS = 12
SMALL_SEGMENT_START_UNIT_PRICE = {
    "轻餐": 1800,
    "正餐": 3000,
}

# 大客户段(31-300 店)锚点折扣因子 — 业务经验值。
# 由业务/商务定期 review;调整后重新部署。
# 锚点之间不做插值:非锚点请求 → resolve_tier_window 返回"夹住"的上下两档。
LARGE_SEGMENT_ANCHORS: dict[str, list[tuple[int, float]]] = {
    "轻餐": [(50, 0.15), (100, 0.13), (200, 0.12), (300, 0.11)],
    "正餐": [(50, 0.18), (100, 0.16), (200, 0.14), (300, 0.13)],
}

PROTECTED_PRODUCT_NAMES = {
    "商管接口",
}

# 总部模块两类：
# - QUANTITY_FIELDS：数量必须由前端字段显式给出且 > 0（中央配送、生产加工中心
#   通常按"建几个"卖）。
# - DEFAULT_QTY_ONE：每勾选一次默认数量=1（按号/品牌为单位售卖，前端不再额外
#   询问数量）。新增同类商品时把名字加进对应集合即可，无需改 schema。
HQ_MODULE_QUANTITY_FIELDS = {
    "配送中心": "配送中心数量",
    "生产加工": "生产加工中心数量",
}
HQ_MODULE_DEFAULT_QTY_ONE = {
    "商家小程序号",
    "商家小程序号-品牌点位",
    "企业微信SCRM",
}


def is_protected_product(product_name):
    return any(keyword in str(product_name) for keyword in PROTECTED_PRODUCT_NAMES)


def as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def now_dt():
    return datetime.now()


def parse_date_maybe(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    patterns = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y%m%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]
    for p in patterns:
        try:
            return datetime.strptime(text, p)
        except ValueError:
            continue
    return None


def parse_money(value):
    text = str(value).strip().replace(",", "")
    if text == "赠送":
        return "赠送"
    return int(float(text))


def round_factor(value):
    return float(Decimal(str(value)).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP))


def round_to_10(value):
    d = Decimal(str(value))
    return int((d / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10"))


def round_money(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_markdown_table(lines):
    table_lines = [line.strip() for line in lines if line.strip()]
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def load_product_catalog(path: Path):
    meal_type = None
    group = None
    table_lines = []
    products = []

    def flush_table():
        nonlocal table_lines, products, meal_type, group
        if not table_lines:
            return
        for row in parse_markdown_table(table_lines):
            name_key = next(
                (key for key in row.keys() if key in {"套餐名称", "模块名称", "设备名称", "服务名称"}),
                None,
            )
            price_key = next((key for key in row.keys() if "标准售价" in key), None)
            if name_key is None or price_key is None or "单位" not in row:
                continue
            products.append({
                "meal_type": meal_type,
                "group": group,
                "name": row[name_key],
                "unit": row["单位"],
                "price": parse_money(row[price_key]),
            })
        table_lines = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## 一、轻餐产品线"):
            flush_table()
            meal_type = "轻餐"
            group = None
            continue
        if line.startswith("## 二、正餐产品线"):
            flush_table()
            meal_type = "正餐"
            group = None
            continue
        if line.startswith("## 三、硬件设备"):
            flush_table()
            meal_type = "通用"
            group = "硬件设备"
            continue
        if line.startswith("## 四、实施服务"):
            flush_table()
            meal_type = "通用"
            group = "实施服务"
            continue
        if line.startswith("### 1. 门店套餐"):
            flush_table()
            group = "门店套餐"
            continue
        if line.startswith("### 2. 门店增值模块"):
            flush_table()
            group = "门店增值模块"
            continue
        if line.startswith("### 3. 总部模块"):
            flush_table()
            group = "总部模块"
            continue
        if line.startswith("|"):
            table_lines.append(line)
            continue
        if table_lines:
            flush_table()

    flush_table()
    return products


def build_pricing_baseline_index(baseline):
    exact = {}
    by_name = {}
    for item in baseline.get("items", []):
        meal_type = item.get("meal_type")
        group = item.get("group")
        name = item.get("name")
        cost_price = item.get("cost_price")
        if meal_type is None or group is None or name is None or cost_price is None:
            continue
        exact[(str(meal_type), str(group), str(name))] = float(cost_price)
        by_name.setdefault(str(name), float(cost_price))
    return {"exact": exact, "by_name": by_name}


def classify_catalog_group(group):
    return group


def compute_standard_price_by_group(group, product_name, cost_price):
    if group == "门店套餐":
        # SaaS 高牌价 + 深折模型：标准价 = 底价 × 20（= 底价 / 0.05），
        # 由 deal_price_factor（≈0.19–0.27）砸到实际成交价。实际毛利约 75%。
        # 起步系数 start_factor_map 里的 7600/11120 也是按这个 20 倍基数定的，
        # 两边必须同步调整，不要单独改这里。
        return int(round(float(cost_price) / 0.05))
    if group == "门店增值模块":
        if product_name == "商管接口":
            return int(round(float(cost_price)))
        return round_to_10(float(cost_price) * 1.10)
    if group == "总部模块":
        return round_to_10(float(cost_price) * 1.20)
    if group == "实施服务":
        return int(round(float(cost_price)))
    return int(round(float(cost_price)))


def resolve_product_pricing(product, quote_meal_type, baseline_index):
    group = classify_catalog_group(product["group"])
    name = product["name"]

    cost_price = baseline_index["exact"].get((quote_meal_type, group, name))
    if cost_price is None:
        cost_price = baseline_index["by_name"].get(name)

    if cost_price is None:
        # 缺失时回退旧目录价格，保证不中断
        fallback = product["price"]
        return int(fallback), int(fallback), "catalog_fallback"

    standard_price = compute_standard_price_by_group(group, name, cost_price)
    return int(standard_price), float(cost_price), "baseline_v5"


def _small_segment_bucket(store_count):
    if 1 <= store_count <= 10:
        return "small-1-10"
    if 11 <= store_count <= 30:
        return "small-11-30"
    if 31 <= store_count <= 100:
        return "large-31-100"
    if 101 <= store_count <= 300:
        return "large-101-300"
    return None


def recommend_base_deal_price_factor_smooth(store_count, meal_type):
    """Return the discount factor for `store_count` of `meal_type`.

    Two regimes:
    - 1-30 (small segment): piecewise-linear smooth curve, slope -0.05/19.
    - {50, 100, 200, 300} (large segment anchors): table lookup.

    31+ non-anchor values (e.g. 56, 150) are NOT directly priced — the caller
    must first resolve the tier window via `resolve_tier_window(n)` and feed
    the anchor endpoints into this function. A non-anchor value in 31-300
    raises ValueError (defensive); > 300 raises OutOfRangeError.
    """
    # 新起步锚点：
    # 轻餐 1 店 1800，正餐 1 店 3000
    start_factor_map = {
        "轻餐": SMALL_SEGMENT_START_UNIT_PRICE["轻餐"] / 7600,
        "正餐": SMALL_SEGMENT_START_UNIT_PRICE["正餐"] / 11120,
    }
    start_factor = start_factor_map[meal_type]
    # 1-30: 沿用原有斜率,每跨 19 店总下降 0.05
    if store_count <= 20:
        return start_factor - 0.05 * (store_count - 1) / 19
    if store_count <= 30:
        step = 0.05 / 19
        factor_at_20 = start_factor - 0.05
        return factor_at_20 - step * (store_count - 20)
    # 大段超限
    if store_count > LARGE_SEGMENT_MAX_STORES:
        raise OutOfRangeError(
            field="门店数量",
            message="301店及以上暂不受理，请转人工定价",
            hint="门店数量需在 1–300 之间",
        )
    # 31-300: 只接受锚点值
    for anchor_count, anchor_factor in LARGE_SEGMENT_ANCHORS[meal_type]:
        if store_count == anchor_count:
            return anchor_factor
    raise ValueError(
        f"非锚点门店数 {store_count},请先调用 resolve_tier_window() 取锚点"
    )


def resolve_tier_window(store_count: int) -> list[int]:
    """Return the [lower, upper] anchor pair that covers `store_count` in the
    large-segment (31-300) range. Boundary rule: left-closed, right-open,
    except the final segment which is right-closed.

    - 30 ≤ n < 50  → [30, 50]   (30 is the small-segment endpoint used as
                                 the lower reference, not itself an anchor
                                 in LARGE_SEGMENT_ANCHORS)
    - 50 ≤ n < 100 → [50, 100]
    - 100 ≤ n < 200 → [100, 200]
    - 200 ≤ n ≤ 300 → [200, 300]
    - n < 30: ValueError (that's small-segment single-point territory)
    - n > 300: OutOfRangeError
    """
    if store_count > LARGE_SEGMENT_MAX_STORES:
        raise OutOfRangeError(
            field="门店数量",
            message="301店及以上暂不受理，请转人工定价",
            hint="门店数量需在 1–300 之间",
        )
    if store_count < 30:
        raise ValueError(
            f"门店数 {store_count} 属于小段(1-30)单点报价,不应调用 resolve_tier_window"
        )
    if 30 <= store_count < 50:
        return [30, 50]
    if 50 <= store_count < 100:
        return [50, 100]
    if 100 <= store_count < 200:
        return [100, 200]
    # 200 ≤ store_count ≤ 300
    return [200, 300]


def small_segment_bounds(store_count, meal_type):
    center = recommend_base_deal_price_factor_smooth(store_count, meal_type)
    bandwidth = 0.02 if meal_type == "轻餐" else 0.015
    low = max(0.01, center - bandwidth)
    high = min(1.0, center + bandwidth)
    return round(low, 6), round(high, 6)


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def weighted_median(values, weights):
    if not values:
        return None
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return pairs[len(pairs) // 2][0]
    acc = 0.0
    half = total_w / 2
    for value, weight in pairs:
        acc += weight
        if acc >= half:
            return value
    return pairs[-1][0]


def get_history_samples(form):
    samples = form.get("history_samples")
    if samples is None:
        samples = form.get("历史样本")
    if samples is None:
        return []
    if not isinstance(samples, list):
        raise ValueError("history_samples/历史样本 必须是数组")
    return samples


def extract_sample_factor(sample):
    if sample.get("deal_price_factor") is not None:
        return float(sample["deal_price_factor"])
    if sample.get("成交价系数") is not None:
        return float(sample["成交价系数"])
    if sample.get("折扣") is not None:
        return 1 - float(sample["折扣"])
    return None


def should_filter_history_sample(sample, meal_type, sample_bucket):
    if as_bool(sample.get("special_approval") or sample.get("特殊审批单"), False):
        return "special_approval"
    if as_bool(sample.get("is_gift") or sample.get("赠送单"), False):
        return "gift"
    if as_bool(sample.get("abnormal_manual_override") or sample.get("人工异常改价单"), False):
        return "abnormal_manual_override"
    if as_bool(sample.get("incomplete") or sample.get("数据不完整"), False):
        return "incomplete_data"
    if as_bool(sample.get("non_standard_package") or sample.get("非标准套餐"), False):
        return "non_standard_package"
    if sample.get("meal_type") and str(sample.get("meal_type")) != meal_type:
        return "cross_meal_type"

    sc = sample.get("store_count") or sample.get("门店数量")
    if sc is None:
        return "missing_store_count"
    sc = int(sc)
    if sc <= 0:
        return "invalid_store_count"
    if sc > LARGE_SEGMENT_MAX_STORES:
        return "out_of_supported_range"

    bucket = _small_segment_bucket(sc)
    if sample_bucket and bucket != sample_bucket:
        return "cross_bucket"

    dt = parse_date_maybe(
        sample.get("date")
        or sample.get("deal_date")
        or sample.get("quote_date")
        or sample.get("成交日期")
    )
    if dt is None:
        return "missing_date"
    days = (now_dt().date() - dt.date()).days
    if days < 0:
        return "future_date"

    factor = extract_sample_factor(sample)
    if factor is None:
        return "missing_factor"
    if not 0 < factor <= 1:
        return "invalid_factor"
    return None


def time_decay_weight(sample):
    dt = parse_date_maybe(
        sample.get("date")
        or sample.get("deal_date")
        or sample.get("quote_date")
        or sample.get("成交日期")
    )
    if dt is None:
        return 0.0
    age_days = (now_dt().date() - dt.date()).days
    # 12 个月线性衰减，保留最小权重避免完全失声
    window_days = HISTORY_WINDOW_MONTHS * 30.44  # 平均月长，避免 31 天偏置
    base = max(0.1, 1 - age_days / window_days)
    return round(base, 6)


def summarize_reasons(reason_list):
    counter = {}
    for reason in reason_list:
        counter[reason] = counter.get(reason, 0) + 1
    return [{"reason": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: x[0])]


def history_weight_cap(sample_count):
    if sample_count < 6:
        return 0.0
    if sample_count <= 12:
        return 0.15
    return 0.25


def apply_history_adjustment(form, meal_type, sample_bucket, base_factor):
    raw_samples = get_history_samples(form)
    if not raw_samples:
        return {
            "final_factor": round(base_factor, 6),
            "history_sample_count": 0,
            "history_weight": 0.0,
            "history_anchor": None,
            "history_filtered_reason_summary": [],
        }

    accepted = []
    filtered_reasons = []
    for sample in raw_samples:
        reason = should_filter_history_sample(sample, meal_type, sample_bucket)
        if reason is not None:
            filtered_reasons.append(reason)
            continue
        accepted.append(sample)

    sample_count = len(accepted)
    cap = history_weight_cap(sample_count)
    if cap == 0.0:
        return {
            "final_factor": round_factor(base_factor),
            "history_sample_count": sample_count,
            "history_weight": 0.0,
            "history_anchor": None,
            "history_filtered_reason_summary": summarize_reasons(filtered_reasons),
        }

    factors = [extract_sample_factor(s) for s in accepted]
    factors_sorted = sorted(factors)
    lo = percentile(factors_sorted, 0.1)
    hi = percentile(factors_sorted, 0.9)
    # 轻量 winsorize，降低极端低价/高价噪声影响
    winsorized = [min(hi, max(lo, f)) for f in factors]
    weights = [time_decay_weight(s) for s in accepted]
    anchor = weighted_median(winsorized, weights)

    final = base_factor * (1 - cap) + anchor * cap
    return {
        "final_factor": round_factor(final),
        "history_sample_count": sample_count,
        "history_weight": round(cap, 6),
        "history_anchor": round(anchor, 6),
        "history_filtered_reason_summary": summarize_reasons(filtered_reasons),
    }


def build_product_index(products):
    index = {}
    for product in products:
        index.setdefault(product["name"], []).append(product)
    return index


def _normalize_manual_reason(form):
    return str(
        form.get("人工改价原因")
        or form.get("manual_override_reason")
        or form.get("manual_override_reason_text")
        or ""
    ).strip()


def _extract_deal_price_factor_input(form):
    if form.get("deal_price_factor") is not None:
        return float(form["deal_price_factor"]), "deal_price_factor"
    if form.get("成交价系数") is not None:
        return float(form["成交价系数"]), "成交价系数"
    if form.get("折扣") is not None:
        # 兼容旧字段语义：折扣是减免比例，转换为成交价系数
        return 1 - float(form["折扣"]), "折扣(兼容转换)"
    return None, None


def normalize_deal_price_factor(form, route_strategy):
    store_count = int(form["门店数量"])
    meal_type = form["餐饮类型"]
    recommended_factor = recommend_base_deal_price_factor_smooth(store_count, meal_type)
    provided_factor, source = _extract_deal_price_factor_input(form)

    if route_strategy == "small-segment":
        if provided_factor is None:
            rounded_factor = round_factor(recommended_factor)
            return rounded_factor, rounded_factor, "auto"
        reason = _normalize_manual_reason(form)
        if not reason:
            raise ValueError("人工改价必须填写原因")
        if not 0 < provided_factor <= 1:
            raise ValueError("成交价系数必须在 (0, 1] 区间")
        return round_factor(recommended_factor), round_factor(float(provided_factor)), source

    if provided_factor is None:
        rounded_factor = round_factor(recommended_factor)
        return rounded_factor, rounded_factor, "auto-legacy"
    reason = _normalize_manual_reason(form)
    if not reason:
        raise ValueError("人工改价必须填写原因")
    if not 0 < provided_factor <= 1:
        raise ValueError("成交价系数必须在 (0, 1] 区间")
    return round_factor(recommended_factor), round_factor(float(provided_factor)), source


def lookup_product(index, name, meal_type=None, group=None):
    candidates = index.get(name, [])
    if group is not None:
        candidates = [item for item in candidates if item["group"] == group]
    if meal_type is not None:
        candidates = [item for item in candidates if item["meal_type"] in {meal_type, "通用"}]
    if not candidates:
        raise ValueError(f"未找到匹配产品: {name}")
    return candidates[0]


def determine_route_strategy(form):
    store_count = int(form["门店数量"])
    small_segment_enabled = as_bool(form.get("small_segment_enabled"), default=DEFAULT_SMALL_SEGMENT_ENABLED)
    if store_count > LARGE_SEGMENT_MAX_STORES:
        return "unsupported", "store_count_gt_300"
    if store_count > SMALL_SEGMENT_MAX_STORES:
        # 31-300: 大客户段,强制走阶梯对比
        return "large-segment", "store_count_31_to_300_tiered"
    if not small_segment_enabled:
        return "legacy", "small_segment_enabled=false"

    non_standard_flags = [
        "多年合同特殊政策",
        "续约增购特价",
        "区域价差",
        "渠道价差",
        "硬件报价",
        "特殊审批商品",
        "特殊商务条款",
        "复杂联购组合",
        "跨餐饮类型混合套餐",
    ]
    for flag in non_standard_flags:
        if bool(form.get(flag)):
            return "legacy", f"non_standard_flag:{flag}"
    return "small-segment", "store_count_le_30_standard_scope"


def validate_form(form, product_index, route_strategy):
    required = ["客户品牌名称", "餐饮类型", "门店数量", "门店套餐"]
    missing = [key for key in required if form.get(key) in (None, "", [])]
    if missing:
        raise ValueError(f"缺少必填字段: {', '.join(missing)}")

    meal_type = form["餐饮类型"]
    if meal_type not in {"轻餐", "正餐"}:
        raise ValueError("餐饮类型必须为轻餐或正餐")

    if int(form["门店数量"]) <= 0:
        raise ValueError("门店数量必须大于 0")
    if int(form["门店数量"]) > LARGE_SEGMENT_MAX_STORES:
        raise OutOfRangeError(
            field="门店数量",
            message="301店及以上暂不受理，请转人工定价",
            hint="门店数量需在 1–300 之间",
        )

    recommended_factor, chosen_factor, factor_source = normalize_deal_price_factor(form, route_strategy)

    package = lookup_product(product_index, form["门店套餐"], meal_type=meal_type, group="门店套餐")
    if package["meal_type"] != meal_type:
        raise ValueError("餐饮类型与门店套餐不匹配")

    module_names = form.get("门店增值模块", [])
    for module_name in module_names:
        module = lookup_product(product_index, module_name, meal_type=meal_type, group="门店增值模块")
        if module["meal_type"] != meal_type:
            raise ValueError("餐饮类型与门店增值模块不匹配")

    protected_overrides = form.get("保护类商品改价", {}) or {}
    if not isinstance(protected_overrides, dict):
        raise ValueError("保护类商品改价字段必须为对象")
    for item_name in protected_overrides.keys():
        if is_protected_product(item_name):
            raise ValueError("保护类商品不允许人工改价")

    headquarter_modules = form.get("总部模块", [])
    if headquarter_modules:
        for module_name in headquarter_modules:
            quantity_field = HQ_MODULE_QUANTITY_FIELDS.get(module_name)
            if quantity_field is not None:
                if quantity_field not in form:
                    raise ValueError(f"勾选总部模块后必须填写 {quantity_field}")
                if int(form.get(quantity_field, 0)) <= 0:
                    raise ValueError(f"勾选总部模块后 {quantity_field} 必须大于 0")
            elif module_name not in HQ_MODULE_DEFAULT_QTY_ONE:
                raise ValueError(f"总部模块不支持: {module_name}")
            lookup_product(product_index, module_name, meal_type=meal_type, group="总部模块")
    for field in ("配送中心数量", "生产加工中心数量"):
        if field in form and int(form[field]) < 0:
            raise ValueError(f"{field} 必须大于等于 0")

    implementation_type = (form.get("实施服务类型") or "").strip()
    implementation_days = int(form.get("实施服务人天", 0) or 0)
    if implementation_type and implementation_days <= 0:
        raise ValueError("选择实施服务后必须填写实施服务人天")
    if implementation_days > 0 and not implementation_type:
        raise ValueError("填写实施服务人天时必须选择实施服务类型")

    return {
        "recommended_factor": recommended_factor,
        "deal_price_factor": chosen_factor,
        "factor_source": factor_source,
    }


def _compute_quote_unit_price(module_category, standard_price, cost_price, deal_price_factor, protected):
    # 分组定价逻辑：
    # - 套餐走标准价 × 成交价系数（可打折），走折扣池
    # - 增值/总部模块是"成本加成"毛利保护：成交价 = 底价 × 固定倍数，
    #   不随 deal_price_factor 联动（深度折扣不能把这两类砸穿毛利）
    # - 受保护商品（商管接口）硬等于底价，不允许打折
    # 这里的 1.20 / 1.50 会超过 compute_standard_price_by_group 算出来的
    # "标准价"（1.10 / 1.20），所以报价单上会出现"商品单价 > 标准价"的情况。
    # 这是业务刻意：增值/总部定位为"卖给大连锁，深折被套餐吸收，这两类反而
    # 加价走"。resolve_product_pricing 的 catalog_fallback 分支在基线缺项时
    # 会让 cost_price = 目录标价，在此路径下会产出 120%-150% 目录标价的报价
    # —— 出事时能定位到是基线漏收商品，不是算法问题。
    if protected:
        return round_money(cost_price)
    if module_category == "门店软件套餐":
        return round_money(Decimal(str(standard_price)) * Decimal(str(deal_price_factor)))
    if module_category == "门店增值模块":
        return round_money(Decimal(str(cost_price)) * Decimal("1.20"))
    if module_category == "总部模块":
        return round_money(Decimal(str(cost_price)) * Decimal("1.50"))
    return round_money(cost_price)


def build_quote_item(product, standard_price, cost_price, quantity, deal_price_factor, category, module_category, description="", sub_items=None):
    protected = is_protected_product(product["name"])
    quote_unit_price = _compute_quote_unit_price(
        module_category=module_category,
        standard_price=standard_price,
        cost_price=cost_price,
        deal_price_factor=deal_price_factor,
        protected=protected,
    )
    cost_unit_price = round_money(cost_price)
    subtotal = round_money(Decimal(str(quote_unit_price)) * Decimal(str(quantity)))
    cost_subtotal = round_money(Decimal(str(cost_unit_price)) * Decimal(str(quantity)))
    profit = round_money(Decimal(str(subtotal)) - Decimal(str(cost_subtotal)))
    margin = 0.0
    if subtotal > 0:
        margin = round_money((Decimal(str(profit)) / Decimal(str(subtotal))) * Decimal("100"))
    item_factor = 1.0 if protected else deal_price_factor
    if standard_price not in (None, "赠送", 0):
        item_factor = round_factor(Decimal(str(quote_unit_price)) / Decimal(str(standard_price)))
    return {
        "商品分类": category,
        "商品名称": product["name"],
        "单位": product["unit"],
        "标准价": standard_price,
        "成交价系数": item_factor,
        "deal_price_factor": item_factor,
        # 兼容旧渲染字段，语义为折扣减免比例
        "折扣": round_factor(1 - item_factor),
        "数量": quantity,
        "模块分类": module_category,
        "protected_item_bypass": protected,
        "商品单价": quote_unit_price,
        "报价小计": subtotal,
        "成本单价": cost_unit_price,
        "成本小计": cost_subtotal,
        "利润": profit,
        "利润率": margin,
        "功能说明": description,
        "子项": list(sub_items) if sub_items else [],
    }


def build_internal_financials(items):
    quote_total = Decimal("0.00")
    cost_total = Decimal("0.00")
    profit_total = Decimal("0.00")
    for item in items:
        quote_total += Decimal(str(item.get("报价小计", 0) or 0))
        cost_total += Decimal(str(item.get("成本小计", 0) or 0))
        profit_total += Decimal(str(item.get("利润", 0) or 0))
    profit_rate = Decimal("0.00")
    if quote_total > 0:
        profit_rate = (profit_total / quote_total) * Decimal("100")
    return {
        "quote_total": round_money(quote_total),
        "cost_total": round_money(cost_total),
        "profit_total": round_money(profit_total),
        "profit_rate": round_money(profit_rate),
    }


def default_terms():
    return [
        "以上报价金额均为含税金额，税率为6%",
        "报价有效期为30个工作日，自报价单生成之日起",
        "具体折扣金额按签订合同（或销售订单）时具体数量确定价格",
        "涉及短信、小程序授权、外卖平台接口调用等第三方机构收费部分，需单独计费",
        "如需要三方代仓对接，需要一事一议",
    ]


def build_tier_config(enabled, meal_type, store_count):
    """Return tier comparison table entries.

    - store_count >= 31 (large segment): ALWAYS return the 2-anchor window
      that brackets store_count, regardless of `enabled`. This is the core
      "31+ 强制阶梯" behavior.
    - store_count <= 30 (small segment): return [10,20,30] if `enabled`,
      else empty.
    """
    if store_count >= 31:
        candidates = resolve_tier_window(store_count)
    elif enabled:
        candidates = [10, 20, 30]
    else:
        return []
    tiers = []
    for count in candidates:
        factor = round_factor(recommend_base_deal_price_factor_smooth(count, meal_type))
        tiers.append({
            "标签": f"{count}店方案",
            "门店数": count,
            "成交价系数": factor,
            "deal_price_factor": factor,
        })
    return tiers


def legacy_factor(store_count, meal_type):
    return round_factor(recommend_base_deal_price_factor_smooth(store_count, meal_type))


def build_manual_override_audit(form, recommended_factor, final_factor, bounded_range, factor_source):
    reason = _normalize_manual_reason(form)
    is_manual = factor_source not in {"auto", "auto-legacy"}
    if not is_manual:
        return {
            "manual_override": False,
            "manual_override_reason": None,
            "manual_override_before_factor": None,
            "manual_override_after_factor": None,
            "manual_override_operator": None,
            "manual_override_time": None,
            "manual_override_outside_band": False,
        }
    operator = (
        form.get("operator")
        or form.get("操作人")
        or form.get("sales_name")
        or form.get("销售")
        or "unknown"
    )
    op_time = (
        form.get("manual_override_time")
        or form.get("操作时间")
        or form.get("override_time")
        or now_dt().strftime("%Y-%m-%d %H:%M:%S")
    )
    out_of_band = False
    if bounded_range:
        out_of_band = final_factor < bounded_range[0] or final_factor > bounded_range[1]
    return {
        "manual_override": True,
        "manual_override_reason": reason,
        "manual_override_before_factor": round_factor(recommended_factor),
        "manual_override_after_factor": round_factor(final_factor),
        "manual_override_operator": str(operator),
        "manual_override_time": str(op_time),
        "manual_override_outside_band": out_of_band,
    }


def build_approval_decision(
    route_strategy,
    base_factor,
    final_factor,
    history_sample_count,
    manual_override,
    protected_item_bypass,
):
    # 业务上不设审批流程：无论是否人工改价系数、历史样本多少，都直接出报价。
    # 保留函数签名与调用点以便未来按需恢复。
    return {"approval_required": False, "approval_reason": []}


def build_quotation_config(form: dict, baseline: dict, product_catalog_path: Path, quote_date=None, descriptions: dict | None = None) -> dict:
    from app.domain.product_descriptions import (
        get_annotation_block,
        get_description,
        get_package_contents,
    )

    products = load_product_catalog(product_catalog_path)
    baseline_index = build_pricing_baseline_index(baseline)
    product_index = build_product_index(products)
    meal_type = form["餐饮类型"]
    requested_store_count = int(form["门店数量"])

    # 大客户段(31-300):把请求门店数替换成"下锚点"。主报价 items 按下锚点
    # 的门店数 + 因子生成;原始请求值保留在 original_requested_store_count
    # 里(审计用),阶梯对比表则使用 requested_store_count 决定窗口
    # (resolve_tier_window),展示 [下锚点, 上锚点] 两档。
    route_strategy, route_reason = determine_route_strategy(form)
    if route_strategy == "large-segment":
        tier_window = resolve_tier_window(requested_store_count)
        effective_store_count = tier_window[0]
        form = dict(form)
        form["门店数量"] = effective_store_count
    else:
        effective_store_count = requested_store_count
    store_count = effective_store_count

    normalized = validate_form(form, product_index, route_strategy)
    deal_price_factor = normalized["deal_price_factor"]
    recommended_factor = normalized["recommended_factor"]
    sample_bucket = _small_segment_bucket(store_count) if route_strategy == "small-segment" else None
    history_meta = {
        "history_sample_count": 0,
        "history_weight": 0.0,
        "history_anchor": None,
        "history_filtered_reason_summary": [],
    }

    if route_strategy == "small-segment":
        base_for_history = deal_price_factor
        # 仅在自动推荐时启用历史拟合，人工改价保持显式输入优先
        if normalized["factor_source"] == "auto":
            history_adjusted = apply_history_adjustment(
                form=form,
                meal_type=meal_type,
                sample_bucket=sample_bucket,
                base_factor=base_for_history,
            )
            deal_price_factor = history_adjusted["final_factor"]
            history_meta = {
                "history_sample_count": history_adjusted["history_sample_count"],
                "history_weight": history_adjusted["history_weight"],
                "history_anchor": history_adjusted["history_anchor"],
                "history_filtered_reason_summary": history_adjusted["history_filtered_reason_summary"],
            }
        else:
            history_meta = {
                "history_sample_count": 0,
                "history_weight": 0.0,
                "history_anchor": None,
                "history_filtered_reason_summary": [{"reason": "manual_override_skip_history", "count": 1}],
            }

    auto_adjustments = []
    if route_strategy == "small-segment" and history_meta["history_weight"] > 0:
        auto_adjustments.append({
            "name": "history_adjustment",
            "weight": history_meta["history_weight"],
            "anchor": history_meta["history_anchor"],
        })

    bounded_range = None
    if route_strategy == "small-segment":
        lower, upper = small_segment_bounds(store_count, meal_type)
        pre_bound_factor = deal_price_factor
        bounded_factor = min(upper, max(lower, deal_price_factor))
        deal_price_factor = round_factor(bounded_factor)
        bounded_range = [lower, upper]
        if round_factor(pre_bound_factor) != round_factor(deal_price_factor):
            auto_adjustments.append({
                "name": "bounded_clamp",
                "before": round_factor(pre_bound_factor),
                "after": round_factor(deal_price_factor),
                "range": bounded_range,
            })

    quote_date = quote_date or datetime.now().strftime("%Y年%m月%d日")
    items = []

    def _desc_for(product):
        return get_description(descriptions, product.get("meal_type", meal_type), product["name"])

    package = lookup_product(product_index, form["门店套餐"], meal_type=meal_type, group="门店套餐")
    package_standard_price, package_cost_price, _ = resolve_product_pricing(package, meal_type, baseline_index)
    package_subs = get_package_contents(descriptions, package.get("meal_type", meal_type), package["name"])
    # When sub-rows carry their own 功能说明, clear the package's combined
    # description so the parent row stays uncluttered.
    package_desc = "" if package_subs else _desc_for(package)
    items.append(build_quote_item(
        package, package_standard_price, package_cost_price, store_count, deal_price_factor,
        "标准软件套餐", "门店软件套餐",
        description=package_desc, sub_items=package_subs,
    ))

    for module_name in form.get("门店增值模块", []):
        module = lookup_product(product_index, module_name, meal_type=meal_type, group="门店增值模块")
        category = "保护类商品" if is_protected_product(module["name"]) else "增值模块"
        standard_price, cost_price, _ = resolve_product_pricing(module, meal_type, baseline_index)
        items.append(build_quote_item(module, standard_price, cost_price, store_count, deal_price_factor, category, "门店增值模块", description=_desc_for(module)))

    for module_name in form.get("总部模块", []):
        quantity_field = HQ_MODULE_QUANTITY_FIELDS.get(module_name)
        if quantity_field is not None:
            quantity = int(form.get(quantity_field, 0))
            if quantity <= 0:
                continue
        elif module_name in HQ_MODULE_DEFAULT_QTY_ONE:
            quantity = 1
        else:
            raise ValueError(f"总部模块不支持: {module_name}")
        module = lookup_product(product_index, module_name, meal_type=meal_type, group="总部模块")
        category = "保护类商品" if is_protected_product(module["name"]) else "总部模块"
        standard_price, cost_price, _ = resolve_product_pricing(module, meal_type, baseline_index)
        items.append(build_quote_item(module, standard_price, cost_price, quantity, deal_price_factor, category, "总部模块", description=_desc_for(module)))

    implementation_type = form.get("实施服务类型")
    implementation_days = int(form.get("实施服务人天", 0) or 0)
    if implementation_type and implementation_days > 0:
        service = lookup_product(product_index, implementation_type, group="实施服务")
        standard_price, cost_price, _ = resolve_product_pricing(service, meal_type, baseline_index)
        items.append(build_quote_item(service, standard_price, cost_price, implementation_days, 1.0, "实施服务", "实施服务", description=_desc_for(service)))

    protected_bypass_count = sum(1 for item in items if item.get("protected_item_bypass"))
    if protected_bypass_count > 0:
        auto_adjustments.append({
            "name": "protected_item_bypass",
            "count": protected_bypass_count,
        })

    manual_audit = build_manual_override_audit(
        form=form,
        recommended_factor=recommended_factor,
        final_factor=deal_price_factor,
        bounded_range=bounded_range,
        factor_source=normalized["factor_source"],
    )
    approval = build_approval_decision(
        route_strategy=route_strategy,
        base_factor=recommended_factor,
        final_factor=deal_price_factor,
        history_sample_count=history_meta["history_sample_count"],
        manual_override=manual_audit["manual_override"],
        protected_item_bypass=protected_bypass_count > 0,
    )
    legacy_recommendation = legacy_factor(store_count, meal_type)

    config = {
        "客户信息": {
            "公司名称": form["客户品牌名称"],
        },
        "报价日期": quote_date,
        "报价有效期": "30个工作日",
        "餐饮类型": meal_type,
        "门店数量": store_count,
        "报价项目": items,
        "internal_financials": build_internal_financials(items),
        "条款": default_terms(),
        "pricing_info": {
            "scope_match": route_strategy == "small-segment",
            "route_strategy": route_strategy,
            "route_reason": route_reason,
            "algorithm_version": (
                PRICING_VERSION if route_strategy == "small-segment"
                else ("large-segment-v1" if route_strategy == "large-segment" else "legacy-v1")
            ),
            "sample_bucket": sample_bucket,
            "base_factor": round_factor(recommended_factor),
            "auto_adjustments": auto_adjustments,
            "bounded_range": bounded_range,
            "final_factor": round_factor(deal_price_factor),
            "deal_price_factor_source": normalized["factor_source"],
            "small_segment_enabled": as_bool(
                form.get("small_segment_enabled"),
                default=DEFAULT_SMALL_SEGMENT_ENABLED,
            ),
            "protected_item_bypass": protected_bypass_count > 0,
            "history_sample_count": history_meta["history_sample_count"],
            "history_weight": history_meta["history_weight"],
            "history_anchor": history_meta["history_anchor"],
            "history_window_months": HISTORY_WINDOW_MONTHS,
            "history_filtered_reason_summary": history_meta["history_filtered_reason_summary"],
            "legacy_factor": legacy_recommendation,
            "new_vs_legacy_factor_delta": round_factor(deal_price_factor - legacy_recommendation),
            "approval_required": approval["approval_required"],
            "approval_reason": approval["approval_reason"],
            "manual_override_reason": manual_audit["manual_override_reason"],
            "manual_override_audit": {
                "enabled": manual_audit["manual_override"],
                "before_factor": manual_audit["manual_override_before_factor"],
                "after_factor": manual_audit["manual_override_after_factor"],
                "operator": manual_audit["manual_override_operator"],
                "time": manual_audit["manual_override_time"],
                "outside_band": manual_audit["manual_override_outside_band"],
            },
        },
    }

    annotation = get_annotation_block(descriptions, "权益类自助充值模块")
    if annotation:
        config["附加说明"] = [annotation]

    tiers = build_tier_config(form.get("是否启用阶梯报价"), meal_type, requested_store_count)
    if tiers:
        config["阶梯配置"] = tiers
    if route_strategy == "large-segment":
        config["original_requested_store_count"] = requested_store_count
        config["pricing_info"]["original_requested_store_count"] = requested_store_count
        config["pricing_info"]["effective_store_count"] = effective_store_count
    return config
