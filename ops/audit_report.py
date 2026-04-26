#!/usr/bin/env python3
"""
全来店报价服务 — 每日调用统计报告
每日凌晨 6:00 定时运行，分析过去 24 小时的 API 调用数据。

用法（手动）:
    python ops/audit_report.py
    python ops/audit_report.py --hours 48

生产环境 cron 配置: 见 ops/cron/crontab.example
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 数据根目录：优先读取环境变量，与 app/config.py 保持一致
DATA_ROOT = Path(os.environ.get("QUOTE_DATA_ROOT", "data"))
AUDIT_DIR = DATA_ROOT / "audit"
REPORT_DIR = DATA_ROOT / "reports"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(ts_str: str) -> datetime | None:
    """解析 ISO 格式 UTC 时间字符串。"""
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def read_audit_records(hours: int = 24) -> list[dict]:
    """读取过去 N 小时内所有审计日志记录。"""
    cutoff = utc_now() - timedelta(hours=hours)
    records = []

    if not AUDIT_DIR.exists():
        return records

    # 读取最近 N 天的日志文件（避免跨文件边界漏数据）
    days_to_check = hours // 24 + 2
    today = utc_now().date()

    for i in range(days_to_check):
        day = today - timedelta(days=i)
        log_file = AUDIT_DIR / f"{day.isoformat()}.jsonl"
        if not log_file.exists():
            continue
        try:
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = parse_ts(rec.get("ts", ""))
                    if ts is None:
                        continue
                    # 仅保留 cutoff 之后的记录
                    if ts >= cutoff:
                        records.append(rec)
        except Exception:
            continue

    return records


def compute_store_bucket(stores: int) -> str:
    if stores <= 5:
        return "1-5店"
    elif stores <= 10:
        return "6-10店"
    elif stores <= 30:
        return "11-30店"
    elif stores <= 50:
        return "31-50店"
    elif stores <= 100:
        return "51-100店"
    elif stores <= 200:
        return "101-200店"
    elif stores <= 300:
        return "201-300店"
    else:
        return "301+店"


def generate_report(records: list[dict], hours: int = 24) -> str:
    """生成 Markdown 格式统计报告。"""
    now = utc_now()
    cutoff = now - timedelta(hours=hours)
    total = len(records)

    # --- 基本统计 ---
    orgs = set(r.get("org", "") for r in records if r.get("org"))
    brands = set(r.get("brand", "") for r in records if r.get("brand"))
    tokens = set(r.get("token_id", "") for r in records if r.get("token_id"))

    durations = [r["duration_ms"] for r in records if isinstance(r.get("duration_ms"), (int, float))]
    avg_duration = sum(durations) / len(durations) if durations else 0
    p95_duration = sorted(durations)[int(len(durations) * 0.95)] if len(durations) >= 20 else None

    finals = [r["final"] for r in records if isinstance(r.get("final"), (int, float))]
    avg_final = sum(finals) / len(finals) if finals else 0
    total_volume = sum(finals)

    factors = [r["discount"] for r in records if isinstance(r.get("discount"), (int, float))]
    avg_factor = sum(factors) / len(factors) if factors else 0

    # --- 分维度统计 ---
    by_org = defaultdict(int)
    by_brand = defaultdict(int)
    by_package = defaultdict(int)
    by_meal_type = defaultdict(int)
    by_route = defaultdict(int)
    by_pricing_version = defaultdict(int)
    by_store_bucket = defaultdict(int)

    for r in records:
        orgs_key = r.get("org", "unknown")
        brands_key = r.get("brand", "unknown")
        packages_key = r.get("package", "unknown")
        meal_type_key = r.get("meal_type", "未知")
        route_key = r.get("route_strategy", "unknown")
        version_key = r.get("pricing_version", "unknown")
        stores = r.get("stores", 0) or r.get("effective_stores", 0) or 0
        stores_bucket = compute_store_bucket(stores) if stores else "未知"

        by_org[orgs_key] += 1
        by_brand[brands_key] += 1
        by_package[packages_key] += 1
        by_meal_type[meal_type_key] += 1
        by_route[route_key] += 1
        by_pricing_version[version_key] += 1
        by_store_bucket[stores_bucket] += 1

    # --- 排序取 top ---
    top_orgs = sorted(by_org.items(), key=lambda x: -x[1])[:10]
    top_brands = sorted(by_brand.items(), key=lambda x: -x[1])[:10]
    top_packages = sorted(by_package.items(), key=lambda x: -x[1])[:10]

    # --- 生成 Markdown ---
    lines = []
    lines.append("# 全来店报价服务 · 每日调用报告")
    lines.append("")
    lines.append(f"**统计周期**: {cutoff.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')} (UTC+0)")
    lines.append(f"**生成时间**: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+0)")
    lines.append(f"**脚本版本**: v1.0.0")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 一、总览
    lines.append("## 一、总量概览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 调用次数 | **{total}** 次 |")
    lines.append(f"| 活跃组织数 | **{len(orgs)}** 个 |")
    lines.append(f"| 活跃品牌数 | **{len(brands)}** 个 |")
    lines.append(f"| 活跃 token 数 | **{len(tokens)}** 个 |")
    lines.append(f"| 成交总额 | **{total_volume:,}** 元 |")
    lines.append(f"| 平均单笔金额 | **{avg_final:,.0f}** 元 |")
    lines.append(f"| 平均成交价系数 | **{avg_factor:.4f}** ({avg_factor*100:.1f}%) |")
    lines.append(f"| 平均响应耗时 | **{avg_duration:.0f}** ms |")
    if p95_duration is not None:
        lines.append(f"| P95 响应耗时 | **{p95_duration:.0f}** ms |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 二、按餐饮类型
    lines.append("## 二、按餐饮类型")
    lines.append("")
    if by_meal_type:
        lines.append("| 餐饮类型 | 调用次数 | 占比 |")
        lines.append("|----------|---------|------|")
        for k, v in sorted(by_meal_type.items(), key=lambda x: -x[1]):
            pct = v / total * 100
            lines.append(f"| {k} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 三、按路由策略
    lines.append("## 三、按报价策略")
    lines.append("")
    route_labels = {
        "small-segment": "小段（1–30 店）",
        "large-segment": "大段阶梯（31–300 店）",
        "legacy": "旧版/非标",
        "unsupported": "不支持（301+ 店）",
    }
    if by_route:
        lines.append("| 策略 | 调用次数 | 占比 |")
        lines.append("|------|---------|------|")
        for k, v in sorted(by_route.items(), key=lambda x: -x[1]):
            pct = v / total * 100
            label = route_labels.get(k, k)
            lines.append(f"| {label} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 四、按门店规模
    lines.append("## 四、按门店规模")
    lines.append("")
    bucket_order = ["1-5店","6-10店","11-30店","31-50店","51-100店","101-200店","201-300店","301+店","未知"]
    if by_store_bucket:
        lines.append("| 规模档位 | 调用次数 | 占比 |")
        lines.append("|----------|---------|------|")
        for bucket in bucket_order:
            v = by_store_bucket.get(bucket, 0)
            if v:
                pct = v / total * 100
                lines.append(f"| {bucket} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 五、按套餐
    lines.append("## 五、套餐分布（Top 10）")
    lines.append("")
    if top_packages:
        lines.append("| 套餐 | 调用次数 | 占比 |")
        lines.append("|------|---------|------|")
        for k, v in top_packages:
            pct = v / total * 100
            lines.append(f"| {k} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 六、按组织
    lines.append("## 六、调用方分布（Top 10 组织）")
    lines.append("")
    if top_orgs:
        lines.append("| 组织 | 调用次数 | 占比 |")
        lines.append("|------|---------|------|")
        for k, v in top_orgs:
            pct = v / total * 100
            lines.append(f"| {k} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 七、按品牌
    lines.append("## 七、品牌分布（Top 10）")
    lines.append("")
    if top_brands:
        lines.append("| 品牌 | 调用次数 |")
        lines.append("|------|---------|")
        for k, v in top_brands:
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 八、按算法版本
    lines.append("## 八、算法版本分布")
    lines.append("")
    version_labels = {
        "small-segment-v1": "小段 v1",
        "small-segment-v2.3": "小段 v2.3",
        "large-segment-v1": "大段 v1",
    }
    if by_pricing_version:
        lines.append("| 算法版本 | 调用次数 | 占比 |")
        lines.append("|----------|---------|------|")
        for k, v in sorted(by_pricing_version.items(), key=lambda x: -x[1]):
            pct = v / total * 100
            label = version_labels.get(k, k)
            lines.append(f"| {label} | {v} | {pct:.1f}% |")
    else:
        lines.append("_暂无数据_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 九、趋势对比（如果有历史数据）
    lines.append("## 九、说明")
    lines.append("")
    lines.append("- 统计口径：`POST /v1/quote` 成功调用（HTTP 200），不含失败请求")
    lines.append("- 数据来源：`data/audit/{YYYY-MM-DD}.jsonl`")
    lines.append("- 成交价系数 = 实际付款 / 标准价，数值越小折扣越深")
    lines.append("- 若需历史对比，建议将每日报告存入 `data/reports/` 目录后对比")
    lines.append("")

    return "\n".join(lines)


def save_report(content: str, report_dir: Path) -> Path:
    """将报告保存到 reports/ 目录。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    today = utc_now().strftime("%Y-%m-%d")
    filename = f"audit-report-{today}.md"
    path = report_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="全来店报价服务每日调用统计")
    parser.add_argument("--hours", type=int, default=24, help="统计过去多少小时（默认 24）")
    parser.add_argument("--output", choices=["console", "file", "both"], default="both",
                        help="输出方式：console（仅打印）/ file（仅存文件）/ both（两者）")
    args = parser.parse_args()

    records = read_audit_records(hours=args.hours)

    print(f"[audit_report] 读取到 {len(records)} 条记录（过去 {args.hours}h）", file=sys.stderr)

    report = generate_report(records, hours=args.hours)

    if args.output in ("console", "both"):
        print(report)

    if args.output in ("file", "both"):
        path = save_report(report, REPORT_DIR)
        print(f"[audit_report] 报告已保存: {path}", file=sys.stderr)

    # 退出码：0=有数据，1=无数据（避免 cron 误报）
    if not records:
        sys.exit(1)


if __name__ == "__main__":
    main()
