#!/usr/bin/env python3
"""
XLSX quotation generator — ported from generate_quotation.py (XLSX portion).

Changes from original:
1. Returns bytes from BytesIO instead of writing to file
2. Shared helpers imported from render_pdf.py
3. main() / argparse removed
4. Tiered sheet addition controlled by render_xlsx() entry point
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from app.domain.render_pdf import (
    fmt_money,
    get_deal_price_factor,
    get_item_unit_price,
    get_item_subtotal,
    get_item_cost_unit_price,
    get_item_cost_subtotal,
    get_tier_unit_price,
    number_to_chinese,
    gen_quote_number,
    calc_actual_price,
    fmt_pct,
)


def _xl_header_style(cell):
    """Excel 表头单元格样式"""
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.font = Font(name='微软雅黑', bold=True, color='FFFFFF', size=10)
    cell.fill = PatternFill('solid', fgColor='FFB300')
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

def _xl_title_style(cell, size=16):
    """Excel 标题单元格样式"""
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.font = Font(name='微软雅黑', bold=True, size=size, color='CC8800')
    cell.alignment = Alignment(horizontal='center', vertical='center')

def _xl_subtitle_style(cell):
    """Excel 副标题单元格样式"""
    from openpyxl.styles import Font, Alignment
    cell.font = Font(name='微软雅黑', size=11, color='555555')
    cell.alignment = Alignment(horizontal='center', vertical='center')

def _xl_info_label_style(cell):
    """Excel 客户信息标签样式"""
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.font = Font(name='微软雅黑', bold=True, size=10, color='CC8800')
    cell.fill = PatternFill('solid', fgColor='FFFBF0')
    cell.alignment = Alignment(horizontal='left', vertical='center')

def _xl_info_value_style(cell):
    """Excel 客户信息值样式"""
    from openpyxl.styles import Font, Alignment
    cell.font = Font(name='微软雅黑', size=10)
    cell.alignment = Alignment(horizontal='left', vertical='center')

def _xl_data_style(cell, align='center', bold=False, bg=None, num_format=None):
    """Excel 数据单元格样式"""
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.font = Font(name='微软雅黑', bold=bold, size=10)
    cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=True)
    if bg:
        cell.fill = PatternFill('solid', fgColor=bg)
    if num_format:
        cell.number_format = num_format

def _xl_total_style(cell, align='right'):
    """Excel 合计行样式"""
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.font = Font(name='微软雅黑', bold=True, size=10)
    cell.fill = PatternFill('solid', fgColor='FFF5D6')
    cell.alignment = Alignment(horizontal=align, vertical='center')

def _xl_apply_border(ws, min_row, min_col, max_row, max_col):
    """为 Excel 单元格区域应用细边框"""
    from openpyxl.styles import Border, Side
    thin = Side(style='thin', color='D0D5DD')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for row in ws.iter_rows(min_row=min_row, min_col=min_col,
                             max_row=max_row, max_col=max_col):
        for cell in row:
            cell.border = border

def _xl_write_item_table(ws, items, start_row, sheet_name='', compute_values=False):
    """
    向 worksheet 写入报价明细表。
    列：A=序号, B=商品分类, C=商品名称, D=单位, E=数量, F=商品单价, G=小计
    compute_values=True 时直接写计算后的数值（兼容性更好），
    否则写 Excel 公式（便于手动调整）。
    返回: (最后数据行号, 合计行号)
    """
    from openpyxl.styles import Font, PatternFill, Alignment

    # 表头
    headers = ['序号', '商品分类', '商品名称', '单位', '数量', '商品单价', '小计']
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=h)
        _xl_header_style(cell)
    ws.row_dimensions[start_row].height = 22

    data_start = start_row + 1
    current_row = data_start

    for idx, item in enumerate(items, 1):
        qty = item.get('数量', 1)
        unit_price_d = get_item_unit_price(item)
        subtotal_d = get_item_subtotal(item)
        is_gift = (unit_price_d == '赠送' or subtotal_d == '赠送')

        # 交替行背景
        bg = 'F5F7FA' if idx % 2 == 0 else None

        # A: 序号
        c = ws.cell(row=current_row, column=1, value=idx)
        _xl_data_style(c, align='center', bg=bg)

        # B: 商品分类
        c = ws.cell(row=current_row, column=2, value=item.get('商品分类', ''))
        _xl_data_style(c, align='left', bg=bg)

        # C: 商品名称
        c = ws.cell(row=current_row, column=3, value=item.get('商品名称', ''))
        _xl_data_style(c, align='left', bg=bg)

        # D: 单位
        c = ws.cell(row=current_row, column=4, value=item.get('单位', ''))
        _xl_data_style(c, align='center', bg=bg)

        # E: 数量
        c = ws.cell(row=current_row, column=5, value=int(qty))
        _xl_data_style(c, align='center', bg=bg)

        # F: 商品单价
        if is_gift:
            c = ws.cell(row=current_row, column=6, value='赠送')
            _xl_data_style(c, align='center', bg=bg)
        else:
            c = ws.cell(row=current_row, column=6, value=float(unit_price_d))
            _xl_data_style(c, align='right', bg=bg, num_format='#,##0.00')

        # G: 小计
        if is_gift:
            c = ws.cell(row=current_row, column=7, value='赠送')
            _xl_data_style(c, align='center', bg=bg)
        else:
            c = ws.cell(row=current_row, column=7, value=float(subtotal_d))
            _xl_data_style(c, align='right', bg=bg, num_format='#,##0.00')

        ws.row_dimensions[current_row].height = 18
        current_row += 1

    last_data_row = current_row - 1

    # 合计行
    total_row = current_row
    ws.merge_cells(start_row=total_row, start_column=1,
                   end_row=total_row, end_column=5)
    c = ws.cell(row=total_row, column=1, value='合计')
    _xl_total_style(c, align='center')

    ws.cell(row=total_row, column=6, value='')
    _xl_total_style(ws.cell(row=total_row, column=6))

    # 合计公式：SUM忽略文本（赠送）
    c = ws.cell(row=total_row, column=7,
                value=f'=SUM(G{data_start}:G{last_data_row})')
    _xl_total_style(c, align='right')
    c.number_format = '#,##0.00'

    ws.row_dimensions[total_row].height = 20

    # 应用边框（含表头）
    _xl_apply_border(ws, start_row, 1, total_row, 7)

    return last_data_row, total_row


def _xl_set_col_widths(ws):
    """设置标准列宽"""
    widths = {
        'A': 7,   # 序号
        'B': 16,  # 商品分类
        'C': 28,  # 商品名称
        'D': 10,  # 单位
        'E': 8,   # 数量
        'F': 14,  # 商品单价
        'G': 16,  # 小计
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


# ============================================================
# 标准模板（≤50店）— Excel
# ============================================================
def _generate_xlsx_standard(data):
    """生成标准单页 Excel 报价单（≤50店）"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = '报价单'
    ws.sheet_view.showGridLines = False

    _xl_set_col_widths(ws)

    # ── 标题区（行1-2） ──
    ws.merge_cells('A1:G1')
    c = ws.cell(row=1, column=1, value='"全来店"产品报价单')
    _xl_title_style(c, size=16)
    ws.row_dimensions[1].height = 36

    ws.merge_cells('A2:G2')
    c = ws.cell(row=2, column=1, value='上海收钱吧互联网科技股份有限公司')
    _xl_subtitle_style(c)
    ws.row_dimensions[2].height = 24

    # ── 空行 ──
    ws.row_dimensions[3].height = 6

    # ── 客户信息区（行4-7） ──
    client = data.get('客户信息', {})
    quote_no = data.get('报价编号', gen_quote_number())
    quote_date = data.get('报价日期', datetime.now().strftime('%Y年%m月%d日'))
    validity = data.get('报价有效期', '30个工作日')

    info_rows = [
        (f'致：{client.get("公司名称", "")}',   f'报价编号：{quote_no}'),
        (f'联系人：{client.get("联系人", "")}',  f'报价日期：{quote_date}'),
        (f'地址：{client.get("地址", "")}',       f'有效期：{validity}'),
        (f'电话：{client.get("电话", "")}',       ''),
    ]

    for i, (left, right) in enumerate(info_rows):
        row_num = 4 + i
        ws.merge_cells(start_row=row_num, start_column=1,
                       end_row=row_num, end_column=4)
        c = ws.cell(row=row_num, column=1, value=left)
        _xl_info_value_style(c)

        ws.merge_cells(start_row=row_num, start_column=5,
                       end_row=row_num, end_column=7)
        c = ws.cell(row=row_num, column=5, value=right)
        _xl_info_value_style(c)
        ws.row_dimensions[row_num].height = 18

    # ── 空行 ──
    ws.row_dimensions[8].height = 8

    # ── 报价明细表（从行9开始） ──
    items = data.get('报价项目', [])
    header_row = 9
    _, total_row = _xl_write_item_table(ws, items, header_row)

    # ── 金额大写（合计行下方） ──
    notes_row = total_row + 2
    ws.merge_cells(start_row=notes_row, start_column=1,
                   end_row=notes_row, end_column=7)
    total_val = Decimal('0')
    for item in items:
        subtotal = get_item_subtotal(item)
        if subtotal != '赠送':
            total_val += subtotal

    chinese_amt = number_to_chinese(float(total_val))
    c = ws.cell(row=notes_row, column=1,
                value=f'合计金额（大写）：{chinese_amt}')
    c.font = Font(name='微软雅黑', size=10, bold=True)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[notes_row].height = 20

    # ── 备注条款 ──
    terms = data.get('条款', [
        '以上报价金额均为含税金额，税率为6%；',
        '报价有效期为30个工作日，自报价单生成之日起；',
        '具体折扣金额按签订合同（或销售订单）时具体数量确定价格；',
        '涉及短信、小程序授权、外卖平台接口调用等第三方机构收费部分，需单独计费；',
        '如需要三方代仓对接，需要一事一议。',
    ])

    terms_start = notes_row + 1
    ws.merge_cells(start_row=terms_start, start_column=1,
                   end_row=terms_start, end_column=7)
    c = ws.cell(row=terms_start, column=1, value='备注：')
    c.font = Font(name='微软雅黑', size=10, bold=True, color='CC8800')
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[terms_start].height = 18

    cn_nums = '①②③④⑤⑥⑦⑧⑨⑩'
    for i, term in enumerate(terms):
        r = terms_start + 1 + i
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        prefix = cn_nums[i] if i < 10 else f'{i+1}.'
        c = ws.cell(row=r, column=1, value=f'{prefix} {term}')
        c.font = Font(name='微软雅黑', size=9, color='555555')
        c.alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[r].height = 16

    # ── 页脚 ──
    footer_row = terms_start + 1 + len(terms) + 1
    ws.merge_cells(start_row=footer_row, start_column=1,
                   end_row=footer_row, end_column=7)
    c = ws.cell(row=footer_row, column=1,
                value='上海收钱吧互联网科技股份有限公司  |  地址：上海市闵行区浦江智慧广场陈行公路2168号7号楼')
    c.font = Font(name='微软雅黑', size=8, color='888888')
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[footer_row].height = 16

    # 冻结表头
    ws.freeze_panes = f'A{header_row + 1}'

    return wb


# ============================================================
# 定制多页模板（>50店）— Excel
# ============================================================
def _generate_xlsx_custom(data):
    """生成定制多 Sheet Excel 报价单（>50店）"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    # 删除默认 Sheet
    wb.remove(wb.active)

    client = data.get('客户信息', {})
    quote_no = data.get('报价编号', gen_quote_number())
    quote_date = data.get('报价日期', datetime.now().strftime('%Y年%m月%d日'))
    validity = data.get('报价有效期', '30个工作日')
    items = data.get('报价项目', [])

    # ── Sheet 1：封面 ──
    ws_cover = wb.create_sheet('封面')
    ws_cover.sheet_view.showGridLines = False
    ws_cover.column_dimensions['A'].width = 18
    ws_cover.column_dimensions['B'].width = 30

    ws_cover.row_dimensions[1].height = 20
    ws_cover.merge_cells('A2:B2')
    c = ws_cover.cell(row=2, column=1, value='"全来店"产品报价方案')
    _xl_title_style(c, size=18)
    ws_cover.row_dimensions[2].height = 44

    ws_cover.merge_cells('A3:B3')
    c = ws_cover.cell(row=3, column=1, value='上海收钱吧互联网科技股份有限公司')
    _xl_subtitle_style(c)
    ws_cover.row_dimensions[3].height = 28

    ws_cover.row_dimensions[4].height = 12

    cover_info = [
        ('客户名称', client.get('公司名称', '')),
        ('联系人',   client.get('联系人', '')),
        ('联系电话', client.get('电话', '')),
        ('报价编号', quote_no),
        ('报价日期', quote_date),
        ('有效期',   validity),
    ]

    for i, (label, value) in enumerate(cover_info):
        r = 5 + i
        c_label = ws_cover.cell(row=r, column=1, value=label)
        _xl_info_label_style(c_label)
        c_val = ws_cover.cell(row=r, column=2, value=value)
        _xl_info_value_style(c_val)
        ws_cover.row_dimensions[r].height = 22

    _xl_apply_border(ws_cover, 5, 1, 5 + len(cover_info) - 1, 2)

    # 记录封面下一可用行（用于后续追加汇总内容）
    cover_summary_start_row = 5 + len(cover_info) + 2

    # ── 按模块分类（不含硬件设备）──
    categories = {
        '门店软件套餐': [],
        '门店增值模块': [],
        '总部模块': [],
        '实施服务': [],
    }

    for item in items:
        cat = item.get('模块分类', '门店软件套餐')
        if cat in categories:
            categories[cat].append(item)
        elif cat != '硬件设备':
            categories['门店软件套餐'].append(item)

    # ── 各分类 Sheet ──
    def _override_items(src_items, deal_price_factor, qty=1):
        """返回 qty/商品单价 覆盖后的副本（刊例价展示用）"""
        result = []
        for it in src_items:
            ni = dict(it)
            ni['数量'] = qty
            if ni.get('标准价') not in ('赠送', None):
                if ni.get('模块分类') == '门店软件套餐':
                    unit_price = calc_actual_price(ni.get('标准价'), deal_price_factor)
                    ni['deal_price_factor'] = deal_price_factor
                    ni['成交价系数'] = deal_price_factor
                    ni['折扣'] = round(1 - deal_price_factor, 6)
                    ni['商品单价'] = float(unit_price)
                subtotal = get_item_unit_price(ni)
                if subtotal != '赠送':
                    ni['报价小计'] = float((subtotal * Decimal(str(qty))).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP))
            result.append(ni)
        return result

    MERGED_SHEET_CATS = ['门店软件套餐', '门店增值模块']
    cat_totals = {}

    # ── 合并 Sheet：门店软件与增值 ──
    merged_has_items = any(categories[c] for c in MERGED_SHEET_CATS)
    if merged_has_items:
        ws_merged = wb.create_sheet('门店软件与增值')
        ws_merged.sheet_view.showGridLines = False
        _xl_set_col_widths(ws_merged)

        ws_merged.merge_cells('A1:G1')
        c = ws_merged.cell(row=1, column=1, value='门店软件与增值模块')
        _xl_title_style(c, size=14)
        ws_merged.row_dimensions[1].height = 30
        ws_merged.row_dimensions[2].height = 8

        section_row = 3
        for cat_name in MERGED_SHEET_CATS:
            cat_items = categories[cat_name]
            if not cat_items:
                continue
            # 分区标题行
            ws_merged.merge_cells(start_row=section_row, start_column=1,
                                  end_row=section_row, end_column=7)
            c = ws_merged.cell(row=section_row, column=1, value=cat_name)
            c.font = Font(name='微软雅黑', bold=True, size=10, color='CC8800')
            c.fill = PatternFill('solid', fgColor='FFFBF0')
            c.alignment = Alignment(horizontal='left', vertical='center')
            ws_merged.row_dimensions[section_row].height = 18
            section_row += 1

            display_items = _override_items(cat_items, deal_price_factor=0.8, qty=1)
            _, total_row = _xl_write_item_table(ws_merged, display_items, section_row, compute_values=True)
            cat_totals[cat_name] = (f'G{total_row}', ws_merged.title)
            section_row = total_row + 2

        ws_merged.freeze_panes = 'A4'

    # ── 总部模块 Sheet ──
    if categories.get('总部模块'):
        ws = wb.create_sheet('总部模块')
        ws.sheet_view.showGridLines = False
        _xl_set_col_widths(ws)
        ws.merge_cells('A1:G1')
        c = ws.cell(row=1, column=1, value='总部模块')
        _xl_title_style(c, size=14)
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 8
        display_items = _override_items(categories['总部模块'], deal_price_factor=0.8, qty=1)
        _, total_row = _xl_write_item_table(ws, display_items, 3, compute_values=True)
        ws.freeze_panes = 'A4'
        cat_totals['总部模块'] = (f'G{total_row}', ws.title)

    # ── 实施服务 Sheet ──
    if categories.get('实施服务'):
        ws = wb.create_sheet('实施服务')
        ws.sheet_view.showGridLines = False
        _xl_set_col_widths(ws)
        ws.merge_cells('A1:G1')
        c = ws.cell(row=1, column=1, value='实施服务')
        _xl_title_style(c, size=14)
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 8
        display_items = _override_items(categories['实施服务'], deal_price_factor=1.0, qty=1)
        _, total_row = _xl_write_item_table(ws, display_items, 3, compute_values=True)
        ws.freeze_panes = 'A4'
        cat_totals['实施服务'] = (f'G{total_row}', ws.title)

    # ── 封面追加：条款说明 ──
    r = cover_summary_start_row

    terms = data.get('条款', [
        '以上报价金额均为含税金额，税率为6%；',
        '报价有效期为30个工作日，自报价单生成之日起；',
        '具体折扣金额按签订合同（或销售订单）时具体数量确定价格；',
        '涉及短信、小程序授权、外卖平台接口调用等第三方机构收费部分，需单独计费；',
        '如需要三方代仓对接，需要一事一议。',
    ])
    ws_cover.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    c = ws_cover.cell(row=r, column=1, value='备注与条款：')
    c.font = Font(name='微软雅黑', size=10, bold=True, color='CC8800')
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws_cover.row_dimensions[r].height = 18
    r += 1

    cn_nums = '①②③④⑤⑥⑦⑧⑨⑩'
    for i, term in enumerate(terms):
        ws_cover.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        prefix = cn_nums[i] if i < 10 else f'{i+1}.'
        c = ws_cover.cell(row=r, column=1, value=f'{prefix} {term}')
        c.font = Font(name='微软雅黑', size=9, color='555555')
        c.alignment = Alignment(horizontal='left', vertical='center')
        ws_cover.row_dimensions[r].height = 16
        r += 1

    # NOTE: tiered sheet is added by render_xlsx() entry point, not here

    return wb


# ============================================================
# 阶梯报价参考 Sheet
# ============================================================
def _xl_add_tiered_sheet(wb, data):
    """在 Excel 工作簿末尾添加阶梯报价参考 Sheet"""
    tiers = data.get('阶梯配置', [])
    if not tiers:
        return

    from openpyxl.styles import Font, PatternFill, Alignment

    ws = wb.create_sheet('阶梯报价参考')
    ws.sheet_view.showGridLines = False

    items = data.get('报价项目', [])
    n_tiers = len(tiers)

    # 列宽
    ws.column_dimensions['A'].width = 32
    ws.column_dimensions['B'].width = 10
    tier_col_letters = ['C', 'D', 'E', 'F', 'G'][:n_tiers]
    for col in tier_col_letters:
        ws.column_dimensions[col].width = 18

    last_col = tier_col_letters[-1]

    # 标题
    ws.merge_cells(f'A1:{last_col}1')
    c = ws.cell(row=1, column=1, value='阶梯报价参考')
    _xl_title_style(c, size=14)
    ws.row_dimensions[1].height = 32

    # 表头
    def tier_label(t):
        return t['标签']

    headers = ['商品名称', '单位'] + [tier_label(t) for t in tiers]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=ci, value=h)
        _xl_header_style(c)
    ws.row_dimensions[2].height = 22

    current_row = 3

    cat_order = ['门店软件套餐', '门店增值模块', '总部模块', '实施服务']
    categories = {k: [] for k in cat_order}
    for item in items:
        cat = item.get('模块分类', '门店软件套餐')
        if cat == '硬件设备':
            continue
        if cat in categories:
            categories[cat].append(item)
        else:
            categories['门店软件套餐'].append(item)

    tier_grand_totals = [Decimal('0')] * n_tiers
    NO_TIER_DISCOUNT_CATS = {'实施服务'}

    for cat_name in cat_order:
        cat_items = categories[cat_name]
        if not cat_items:
            continue

        # 分类标题行
        ws.merge_cells(start_row=current_row, start_column=1,
                       end_row=current_row, end_column=2 + n_tiers)
        c = ws.cell(row=current_row, column=1, value=cat_name)
        c.font = Font(name='微软雅黑', bold=True, size=10, color='CC8800')
        c.fill = PatternFill('solid', fgColor='FFFBF0')
        c.alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[current_row].height = 18
        current_row += 1

        cat_tier_totals = [Decimal('0')] * n_tiers
        apply_tier_discount = cat_name not in NO_TIER_DISCOUNT_CATS

        for item in cat_items:
            unit = item.get('单位', '')
            item_qty = item.get('数量', 1)
            is_per_store = '店' in unit
            unit_price = get_item_unit_price(item)

            c = ws.cell(row=current_row, column=1, value=item.get('商品名称', ''))
            c.font = Font(name='微软雅黑', size=9)
            c.alignment = Alignment(horizontal='left', vertical='center')

            c = ws.cell(row=current_row, column=2, value=unit)
            c.font = Font(name='微软雅黑', size=9)
            c.alignment = Alignment(horizontal='center', vertical='center')

            if unit_price == '赠送':
                for ci in range(n_tiers):
                    c = ws.cell(row=current_row, column=3 + ci, value='赠送')
                    c.font = Font(name='微软雅黑', size=9)
                    c.alignment = Alignment(horizontal='center', vertical='center')
            else:
                for ti, t in enumerate(tiers):
                    d = Decimal(str(get_deal_price_factor(t))) if apply_tier_discount else Decimal('1')
                    qty = Decimal(str(t['门店数'])) if is_per_store else Decimal(str(item_qty))
                    actual = get_tier_unit_price(item, d) if apply_tier_discount else unit_price
                    subtotal = (actual * qty).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
                    cat_tier_totals[ti] += subtotal
                    c = ws.cell(row=current_row, column=3 + ti, value=float(subtotal))
                    c.font = Font(name='微软雅黑', size=9)
                    c.number_format = '#,##0.00'
                    c.alignment = Alignment(horizontal='right', vertical='center')

            ws.row_dimensions[current_row].height = 18
            current_row += 1

        # 分类小计行
        c = ws.cell(row=current_row, column=2, value='小计')
        c.font = Font(name='微软雅黑', bold=True, size=9)
        c.fill = PatternFill('solid', fgColor='FFF5D6')
        c.alignment = Alignment(horizontal='center', vertical='center')
        for ti, tot in enumerate(cat_tier_totals):
            tier_grand_totals[ti] += tot
            c = ws.cell(row=current_row, column=3 + ti, value=float(tot))
            c.font = Font(name='微软雅黑', bold=True, size=9)
            c.number_format = '#,##0.00'
            c.fill = PatternFill('solid', fgColor='FFF5D6')
            c.alignment = Alignment(horizontal='right', vertical='center')
        ws.row_dimensions[current_row].height = 18
        current_row += 1

    # 合计行
    c = ws.cell(row=current_row, column=2, value='合计')
    c.font = Font(name='微软雅黑', bold=True, size=10, color='CC8800')
    c.fill = PatternFill('solid', fgColor='FFE082')
    c.alignment = Alignment(horizontal='center', vertical='center')
    for ti, tot in enumerate(tier_grand_totals):
        c = ws.cell(row=current_row, column=3 + ti, value=float(tot))
        c.font = Font(name='微软雅黑', bold=True, size=10, color='CC8800')
        c.number_format = '#,##0.00'
        c.fill = PatternFill('solid', fgColor='FFE082')
        c.alignment = Alignment(horizontal='right', vertical='center')
    ws.row_dimensions[current_row].height = 22
    grand_total_row = current_row
    current_row += 1

    # 折算单店年费行
    ws.merge_cells(start_row=current_row, start_column=1,
                   end_row=current_row, end_column=2)
    c = ws.cell(row=current_row, column=1, value='折算单店年费')
    c.font = Font(name='微软雅黑', bold=True, size=9)
    c.fill = PatternFill('solid', fgColor='FFF5D6')
    c.alignment = Alignment(horizontal='left', vertical='center')
    for ti, t in enumerate(tiers):
        stores = Decimal(str(t['门店数']))
        per_store = (tier_grand_totals[ti] / stores).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        c = ws.cell(row=current_row, column=3 + ti, value=float(per_store))
        c.font = Font(name='微软雅黑', size=9)
        c.number_format = '#,##0.00'
        c.fill = PatternFill('solid', fgColor='FFF5D6')
        c.alignment = Alignment(horizontal='right', vertical='center')
    ws.row_dimensions[current_row].height = 18

    _xl_apply_border(ws, 2, 1, current_row, 2 + n_tiers)


# ============================================================
# 公共入口
# ============================================================
def render_xlsx(config: dict) -> bytes:
    """Generate XLSX quotation from config dict. Returns XLSX bytes."""
    if config.get("pricing_info", {}).get("route_strategy") == "small-segment":
        wb = _generate_xlsx_standard(config)
    else:
        wb = _generate_xlsx_custom(config)
    if config.get("阶梯配置"):
        _xl_add_tiered_sheet(wb, config)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
