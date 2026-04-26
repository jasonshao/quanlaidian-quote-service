"""Inject a page-header watermark image into a saved xlsx.

Why this module exists
----------------------
openpyxl 3.1 has no API for header/footer images. We want a watermark that
shows in Page Layout view and on print, but does NOT intercept double-click
cell-edit events in Normal view (which is what AbsoluteAnchor floating images
do). Excel's standard solution is the header/footer image facility, which
uses a VML drawing per sheet referencing a shared image part.

This module operates on already-serialized xlsx bytes (output of wb.save()),
edits the underlying ZIP/OOXML in-memory, and returns new bytes.
"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO


# OOXML namespaces and relationship types
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_TYPE_IMAGE = _NS_R + "/image"
_REL_TYPE_VML = _NS_R + "/vmlDrawing"

# Single shared image part — every sheet's VML drawing points at this
_SHARED_IMAGE_PART = "xl/media/imageHF1.png"
_SHARED_IMAGE_RELTARGET = "../media/imageHF1.png"

# Standard VML for an Excel header watermark. Shape id="CH1" is the magic
# token Excel reads to know "this image goes in the Center Header position".
# Width/height in points sized for an A4 portrait page (595×842pt) so the
# image visibly extends down through the printable area; Excel/WPS scale
# it to match the actual page setup.
_VML_DRAWING_TEMPLATE = """<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">
 <o:shapelayout v:ext="edit">
  <o:idmap v:ext="edit" data="1"/>
 </o:shapelayout>
 <v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75" o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">
  <v:stroke joinstyle="miter"/>
  <v:formulas>
   <v:f eqn="if lineDrawn pixelLineWidth 0"/>
   <v:f eqn="sum @0 1 0"/>
   <v:f eqn="sum 0 0 @1"/>
   <v:f eqn="prod @2 1 2"/>
   <v:f eqn="prod @3 21600 pixelWidth"/>
   <v:f eqn="prod @3 21600 pixelHeight"/>
   <v:f eqn="sum @0 0 1"/>
   <v:f eqn="prod @6 1 2"/>
   <v:f eqn="prod @7 21600 pixelWidth"/>
   <v:f eqn="sum @8 21600 0"/>
   <v:f eqn="prod @7 21600 pixelHeight"/>
   <v:f eqn="sum @10 21600 0"/>
  </v:formulas>
  <v:path o:extrusionok="f" gradientshapeok="t" o:connecttype="rect"/>
  <o:lock v:ext="edit" aspectratio="t"/>
 </v:shapetype>
 <v:shape id="CH1" o:spid="_x0000_s1025" type="#_x0000_t75" style="position:absolute;margin-left:0;margin-top:0;width:595pt;height:595pt;z-index:1">
  <v:imagedata o:relid="rIdHFImage" o:title="watermark"/>
  <o:lock v:ext="edit" rotation="t"/>
 </v:shape>
</xml>
"""

_VML_RELS = (
    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>"""
    """<Relationships xmlns="{ns}">"""
    """<Relationship Id="rIdHFImage" Type="{rt}" Target="{tgt}"/>"""
    """</Relationships>"""
).format(ns=_NS_PR, rt=_REL_TYPE_IMAGE, tgt=_SHARED_IMAGE_RELTARGET)


def inject_header_watermark(xlsx_bytes: bytes, png_bytes: bytes) -> bytes:
    """Add a centered odd-page header image to every worksheet.

    Returns new xlsx bytes; the input is not mutated.
    """
    if not xlsx_bytes or not png_bytes:
        return xlsx_bytes

    src = zipfile.ZipFile(BytesIO(xlsx_bytes), "r")
    try:
        files = {name: src.read(name) for name in src.namelist()}
    finally:
        src.close()

    sheet_paths = _list_worksheet_paths(files)
    if not sheet_paths:
        return xlsx_bytes

    # Single shared image part
    files[_SHARED_IMAGE_PART] = png_bytes

    for idx, sheet_path in enumerate(sheet_paths, start=1):
        vml_path = f"xl/drawings/vmlDrawingHF{idx}.vml"
        vml_rels_path = f"xl/drawings/_rels/vmlDrawingHF{idx}.vml.rels"

        files[vml_path] = _VML_DRAWING_TEMPLATE.encode("utf-8")
        files[vml_rels_path] = _VML_RELS.encode("utf-8")

        sheet_xml = files[sheet_path].decode("utf-8")
        sheet_rels_path = _sheet_rels_path(sheet_path)
        sheet_rels_xml = files.get(sheet_rels_path, _empty_rels()).decode("utf-8")

        rel_id, sheet_rels_xml = _add_vml_rel(sheet_rels_xml, idx)
        sheet_xml = _wire_header_image_into_sheet(sheet_xml, rel_id)

        files[sheet_path] = sheet_xml.encode("utf-8")
        files[sheet_rels_path] = sheet_rels_xml.encode("utf-8")

    files["[Content_Types].xml"] = _ensure_content_types(
        files["[Content_Types].xml"].decode("utf-8")
    ).encode("utf-8")

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, data in files.items():
            dst.writestr(name, data)
    return out.getvalue()


def _list_worksheet_paths(files: dict[str, bytes]) -> list[str]:
    """Return worksheet xml paths in workbook order.

    Walks xl/_rels/workbook.xml.rels to honour whatever path scheme openpyxl
    used (worksheets/sheet1.xml is the default but not guaranteed).
    """
    rels_xml = files.get("xl/_rels/workbook.xml.rels", b"").decode("utf-8")
    if not rels_xml:
        return []
    paths: list[str] = []
    # Match <Relationship .../> or <Relationship ...></Relationship>; the
    # attribute values contain "/" (URL types), so we cannot exclude / inside
    # the tag. Allow anything up to the closing /> non-greedily.
    for m in re.finditer(r"<Relationship\b[^>]*?/?>", rels_xml):
        chunk = m.group(0)
        if "/relationships/worksheet" not in chunk:
            continue
        target = re.search(r'Target="([^"]+)"', chunk)
        if not target:
            continue
        rel_target = target.group(1)
        # openpyxl emits Target="/xl/worksheets/sheet1.xml" (absolute) but
        # other writers may emit "worksheets/sheet1.xml" (relative to xl/).
        if rel_target.startswith("/"):
            normalized = rel_target.lstrip("/")
        else:
            normalized = "xl/" + rel_target
        if normalized in files:
            paths.append(normalized)
    return paths


def _sheet_rels_path(sheet_path: str) -> str:
    """xl/worksheets/sheetN.xml -> xl/worksheets/_rels/sheetN.xml.rels"""
    head, _, tail = sheet_path.rpartition("/")
    return f"{head}/_rels/{tail}.rels"


def _empty_rels() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_NS_PR}"/>'
    ).encode("utf-8")


def _add_vml_rel(rels_xml: str, idx: int) -> tuple[str, str]:
    """Append a vmlDrawing relationship; return (assigned_id, new_rels_xml)."""
    existing_ids = {m.group(1) for m in re.finditer(r'\bId="([^"]+)"', rels_xml)}
    n = 1
    while f"rIdHF{n}" in existing_ids:
        n += 1
    rel_id = f"rIdHF{n}"

    new_rel = (
        f'<Relationship Id="{rel_id}" Type="{_REL_TYPE_VML}" '
        f'Target="../drawings/vmlDrawingHF{idx}.vml"/>'
    )

    if "</Relationships>" in rels_xml:
        rels_xml = rels_xml.replace("</Relationships>", new_rel + "</Relationships>")
    elif "<Relationships" in rels_xml and rels_xml.rstrip().endswith("/>"):
        # Self-closing root <Relationships ... /> with no children
        rels_xml = re.sub(
            r"(<Relationships\b[^/]*?)/>",
            r"\1>" + new_rel + "</Relationships>",
            rels_xml,
            count=1,
        )
    else:
        # Fallback: build a fresh rels doc
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_NS_PR}">{new_rel}</Relationships>'
        )
    return rel_id, rels_xml


def _wire_header_image_into_sheet(sheet_xml: str, rel_id: str) -> str:
    """Edit a worksheet xml so it (a) declares <oddHeader>&C&G</oddHeader>
    and (b) references the VML via <legacyDrawingHF r:id="..."/>.

    Element order inside <worksheet> is schema-strict in OOXML:
        ... headerFooter, drawing, legacyDrawing, legacyDrawingHF, ...
    We only need to handle existing trees produced by openpyxl which already
    contain the standard elements in the right order; we slot ours in
    relative to <headerFooter> / <pageSetup> as anchors.
    """
    # 1. Set <oddHeader>&C&G</oddHeader> inside <headerFooter>.
    odd_header = "<oddHeader>&amp;C&amp;G</oddHeader>"

    if "<headerFooter" in sheet_xml:
        # Replace any existing <oddHeader>...</oddHeader> in the headerFooter
        # block, or insert one right after the <headerFooter ...> opening tag.
        if re.search(r"<oddHeader\b", sheet_xml):
            sheet_xml = re.sub(
                r"<oddHeader\b[^>]*>.*?</oddHeader>",
                odd_header,
                sheet_xml,
                count=1,
                flags=re.DOTALL,
            )
            # Self-closing variant <oddHeader/>
            sheet_xml = re.sub(r"<oddHeader\s*/>", odd_header, sheet_xml, count=1)
        else:
            sheet_xml = re.sub(
                r"(<headerFooter\b[^>]*?>)",
                r"\1" + odd_header,
                sheet_xml,
                count=1,
            )
            # Self-closing <headerFooter ... /> -> open it up
            sheet_xml = re.sub(
                r"<headerFooter\b([^/]*)/>",
                lambda m: f"<headerFooter{m.group(1)}>{odd_header}</headerFooter>",
                sheet_xml,
                count=1,
            )
    else:
        # No headerFooter element; openpyxl normally emits one but be safe.
        # Insert before </worksheet>.
        sheet_xml = sheet_xml.replace(
            "</worksheet>",
            f"<headerFooter>{odd_header}</headerFooter></worksheet>",
            1,
        )

    # 2. Add <legacyDrawingHF r:id="..."/>. Per OOXML schema this element
    #    appears late in the worksheet child sequence — after <legacyDrawing>
    #    if present, otherwise after <drawing>, otherwise just before
    #    </worksheet>. We search anchors in priority order.
    # Declare xmlns:r inline because openpyxl's worksheet root element omits
    # the relationships namespace declaration.
    legacy_hf = f'<legacyDrawingHF xmlns:r="{_NS_R}" r:id="{rel_id}"/>'

    if re.search(r"<legacyDrawingHF\b", sheet_xml):
        # Already present — replace it (idempotent re-injection)
        sheet_xml = re.sub(
            r"<legacyDrawingHF\b[^/>]*/>", legacy_hf, sheet_xml, count=1
        )
    else:
        for anchor_pattern in (
            r"(<legacyDrawing\b[^/>]*/>)",
            r"(<drawing\b[^/>]*/>)",
            r"(<headerFooter\b[^>]*>.*?</headerFooter>)",
            r"(<headerFooter\b[^/]*/>)",
        ):
            new_xml, n = re.subn(
                anchor_pattern,
                lambda m: m.group(1) + legacy_hf,
                sheet_xml,
                count=1,
                flags=re.DOTALL,
            )
            if n:
                sheet_xml = new_xml
                break
        else:
            sheet_xml = sheet_xml.replace(
                "</worksheet>", legacy_hf + "</worksheet>", 1
            )

    return sheet_xml


def _ensure_content_types(ct_xml: str) -> str:
    """Make sure png and vml Default extensions are declared."""
    if 'Extension="png"' not in ct_xml:
        ct_xml = _insert_default(ct_xml, "png", "image/png")
    if 'Extension="vml"' not in ct_xml:
        ct_xml = _insert_default(
            ct_xml,
            "vml",
            "application/vnd.openxmlformats-officedocument.vmlDrawing",
        )
    return ct_xml


def _insert_default(ct_xml: str, ext: str, content_type: str) -> str:
    new_default = f'<Default Extension="{ext}" ContentType="{content_type}"/>'
    return ct_xml.replace("</Types>", new_default + "</Types>", 1)
