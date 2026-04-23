#!/usr/bin/env python3
"""
catalog_descriptions.py — 报价单模板用的描述文本加载器。

从 `references/product_catalog.md` 抽取：
- 套餐说明（SKU → 多行正文），给报价单 K 列用
- 模块说明（模块名 → 单行说明），沿用现有表格『说明』列
- 权益类正文（整段字符串），给报价单页脚用

设计原则：
- 加载失败（节点缺失或文件不存在）返回空 dict / 空字符串，不抛异常 —
  调用方（渲染器）在缺失时静默留空，避免因文本缺失阻塞出单。
- 解析按 markdown 小标题+分段定位，不严格校验结构，对后续微调容错。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict


_DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / 'references' / 'product_catalog.md'
)


def _read_catalog(path: Path | None = None) -> str:
    p = Path(path) if path is not None else _DEFAULT_CATALOG_PATH
    if not p.exists():
        return ''
    try:
        return p.read_text(encoding='utf-8')
    except OSError:
        return ''


def load_package_descriptions(path: Path | None = None) -> Dict[str, str]:
    """解析所有 `### 1.1 套餐说明` 小节下的 `**套餐名称**` 段落。

    Returns dict `{套餐名称: '①…\n②…\n③…'}`.
    """
    text = _read_catalog(path)
    if not text:
        return {}

    result: Dict[str, str] = {}

    # Scope: find all sections titled "套餐说明" (轻餐 + 正餐 each has one).
    # The section ends at the next heading of depth ≥ ## or ###.
    for section_match in re.finditer(
        r'###\s*1\.1\s*套餐说明.*?(?=\n###\s|\n##\s|\Z)',
        text, re.DOTALL
    ):
        section = section_match.group(0)
        # Find each bolded SKU name followed by body lines.
        # Stop at the next `**`, any `#` heading, `---` line, or end of section.
        for sku_match in re.finditer(
            r'\*\*([^*\n]+)\*\*\n(.+?)(?=\n\*\*|\n#{2,}\s|\n---|\Z)',
            section, re.DOTALL
        ):
            name = sku_match.group(1).strip()
            body = sku_match.group(2).strip()
            # Collapse blank lines, keep line breaks for bullet structure
            body = re.sub(r'\n\s*\n', '\n', body).strip()
            if name and body:
                result[name] = body

    return result


def load_module_descriptions(path: Path | None = None) -> Dict[str, str]:
    """从 `### 2 门店增值模块` / `### 3 总部模块` markdown 表格提取 `{模块名: 说明}`.

    解析规则：识别带『说明』列的 markdown 表，取首列作为 key、末列作为 value。
    跳过表头与分隔行。
    """
    text = _read_catalog(path)
    if not text:
        return {}

    result: Dict[str, str] = {}

    # Find markdown tables with a "说明" column
    for table_match in re.finditer(
        r'\|[^\n]*模块名称[^\n]*说明[^\n]*\|\n\|[-:\s|]+\|\n((?:\|[^\n]+\|\n?)+)',
        text
    ):
        rows = table_match.group(1).strip().split('\n')
        for row in rows:
            cells = [c.strip() for c in row.strip('|').split('|')]
            if len(cells) < 2:
                continue
            name = cells[0]
            desc = cells[-1]
            if name and desc:
                result[name] = desc

    return result


def load_benefits_text(path: Path | None = None) -> str:
    """抽取 `## 三、权益类` 整节正文（不含节标题），返回原始 markdown 字符串。

    渲染器按需将 `###` 小标题和 `*` / `-` 列表转成对应样式。
    """
    text = _read_catalog(path)
    if not text:
        return ''

    m = re.search(
        r'##\s*三、权益类[^\n]*\n+(.+?)(?=\n##\s|\Z)',
        text, re.DOTALL
    )
    if not m:
        return ''
    body = m.group(1).strip()
    # Drop HTML comments that might be in the doc
    body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL).strip()
    return body
