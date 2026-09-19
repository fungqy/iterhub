"""文档故障截图:从上传的 Excel 里抽出【截图1】【截图2】两列的浮动图片,算归属,生成缩略图。

为什么独立成模块:`data_import.py` 已经 740+ 行,而这里做的是「OOXML 包解析 +
图片编码」,与「导入业务流程」正交 —— 分开后能单独测、单独读。

⚠ 关于归属这件事,先说清楚它为什么不像听起来那么简单:
   源表的图片是**浮动对象**,不是单元格的值。openpyxl 的 read_only 会整个跳过
   xl/media(这正是导入 297MB 文件还能很快的原因),所以想拿图片只能自己解 OOXML 包。
   实测该表 395 个锚点:
     · 全部是 `oneCellAnchor`(只有左上角单元格 + 显式尺寸,没有 to 角);
     · 列号只有 8(截图1) / 11(截图2) 两种 —— 没有一个跑偏;
     · 工作簿只有「问题明细表」一张 sheet,故 行号对齐是确定的,不是巧合。
   因此「锚点 from 单元格」就是权威归属:sheet 行 = from_row + 1(锚点行是 0-based)。

⚠ 另一个实测结论:同一张图会被多个故障引用(image313/314/315 同属 m09021020 与
   m09031042),一个故障内也有重复引用。所以图片的语义是「属于哪个故障」而不是
   「文件去重」,本模块按 (key, 出现次序) 产出,不做内容级合并。
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from typing import Any

# 源表「图片列」的 0-based 列号 → 列名。实测该表 395 个锚点只落在这两列。
DOC_BUG_IMAGE_COLUMNS: dict[int, str] = {8: "截图1", 11: "截图2"}

# 缩略图参数:原图中位 2618×1448 / 587KiB。
# 宽度取 900 而不是 560 的理由:详情弹窗内容区约 700px,560px 的缩略图铺进去会被
# 放大发虚;900px 可 1:1 显示。代价实测很小(见 verify-ui/probe-docbug-image-extract.py),
# 且缩略图只用于「认出是哪张图」,要读清文字仍需点「查看原图」。
THUMB_MAX_WIDTH = 900
THUMB_QUALITY = 82
_THUMB_FALLBACK_MIME = "image/png"
# 超此像素数不生成缩略图(防解压炸弹),原图照常入库
MAX_THUMB_PIXELS = 40_000_000

_NS_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_DRAW = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"

_MIME_BY_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"RIFF", "image/webp"),
)


def _normalize_part(base_dir: str, target: str | None) -> str | None:
    """把 OOXML 关系里的相对 Target 归一成包内绝对路径(如 xl/media/image1.png)。"""
    if not target:
        return None
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def detect_mime(blob: bytes) -> str:
    for magic, mime in _MIME_BY_MAGIC:
        if blob.startswith(magic):
            return mime
    return "application/octet-stream"


def read_png_size(blob: bytes) -> tuple[int | None, int | None]:
    """直接从 PNG 的 IHDR 头取宽高 —— 不必依赖 Pillow,也不解码整张图。"""
    if len(blob) < 24 or blob[:8] != b"\x89PNG\r\n\x1a\n" or blob[12:16] != b"IHDR":
        return None, None
    width, height = struct.unpack(">II", blob[16:24])
    return width, height


def _find_drawing_part(z: zipfile.ZipFile, sheet_name: str) -> str | None:
    """按 sheet **名字**定位它挂的 drawing part。

    刻意走完整链路(workbook.xml → workbook.xml.rels → sheetN.xml.rels → drawing),
    而不是硬编码 xl/drawings/drawing1.xml —— 硬编码在工作簿多 sheet、或维护方
    重排顺序时会静默取到**另一张表**的图,那种错不报错、只出错数据。
    """
    names = set(z.namelist())
    if "xl/workbook.xml" not in names:
        return None

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheet_rid: str | None = None
    for sh in wb.iter(f"{{{_NS_SML}}}sheet"):
        if sh.get("name") == sheet_name:
            sheet_rid = sh.get(f"{{{_NS_R}}}id")
            break
    if sheet_rid is None:
        return None

    if "xl/_rels/workbook.xml.rels" not in names:
        return None
    sheet_part: str | None = None
    wrels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in wrels.iter(f"{{{_NS_PR}}}Relationship"):
        if rel.get("Id") == sheet_rid:
            sheet_part = _normalize_part("xl", rel.get("Target"))
            break
    if not sheet_part:
        return None

    sheet_dir = posixpath.dirname(sheet_part)
    sheet_rels = f"{sheet_dir}/_rels/{posixpath.basename(sheet_part)}.rels"
    if sheet_rels not in names:
        return None

    srels = ET.fromstring(z.read(sheet_rels))
    for rel in srels.iter(f"{{{_NS_PR}}}Relationship"):
        if (rel.get("Type") or "").endswith("/drawing"):
            return _normalize_part(sheet_dir, rel.get("Target"))
    return None


def parse_drawing_anchors(
    z: zipfile.ZipFile, drawing_part: str
) -> list[dict[str, Any]]:
    """解析 drawing part → [{order, row, col, media, anchor_kind}]。

    order = 在 drawing xml 里的出现次序,用作同一单元格内多张图排序的稳定兜底。
    """
    names = set(z.namelist())
    drawing_dir = posixpath.dirname(drawing_part)
    rels_part = f"{drawing_dir}/_rels/{posixpath.basename(drawing_part)}.rels"

    rid2target: dict[str, str] = {}
    if rels_part in names:
        rroot = ET.fromstring(z.read(rels_part))
        for rel in rroot.iter(f"{{{_NS_PR}}}Relationship"):
            rid = rel.get("Id")
            part = _normalize_part(drawing_dir, rel.get("Target"))
            if rid and part:
                rid2target[rid] = part

    root = ET.fromstring(z.read(drawing_part))
    anchors: list[dict[str, Any]] = []
    for order, child in enumerate(list(root)):
        kind = child.tag.rsplit("}", 1)[-1]
        if not kind.endswith("CellAnchor"):
            continue
        frm = child.find(f"{{{_NS_DRAW}}}from")
        blip = child.find(f".//{{{_NS_A}}}blip")
        if frm is None or blip is None:
            continue
        col_el = frm.find(f"{{{_NS_DRAW}}}col")
        row_el = frm.find(f"{{{_NS_DRAW}}}row")
        embed = blip.get(f"{{{_NS_R}}}embed")
        if col_el is None or row_el is None or not col_el.text or not row_el.text:
            continue
        anchors.append(
            {
                "order": order,
                "row": int(row_el.text),  # 0-based sheet 行号
                "col": int(col_el.text),  # 0-based 列号
                "media": rid2target.get(embed) if embed else None,
                "anchor_kind": kind,
            }
        )
    return anchors


def make_thumbnail(blob: bytes) -> tuple[bytes | None, str | None]:
    """生成缩略图 → (bytes, mime)。不可用时返回 (None, None),不影响原图入库。"""
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - 缺依赖时降级
        return None, None

    try:
        with Image.open(io.BytesIO(blob)) as im:
            if im.width * im.height > MAX_THUMB_PIXELS:
                return None, None
            im.thumbnail((THUMB_MAX_WIDTH, 10**6))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=THUMB_QUALITY, method=4)
            return buf.getvalue(), "image/webp"
    except Exception:
        pass

    # WebP 编不出来(或解码本身有问题)→ 退回 PNG;再失败就只存原图
    try:
        from PIL import Image

        with Image.open(io.BytesIO(blob)) as im:
            im.thumbnail((THUMB_MAX_WIDTH, 10**6))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), _THUMB_FALLBACK_MIME
    except Exception:
        return None, None


def has_drawing(xlsx_path: str, sheet_name: str) -> bool:
    """该 sheet 是否挂了 drawing(即源文件里到底有没有内嵌图片)。

    单独提供这个轻量判断,是为了让调用方能**先决定**要不要动图片表 ——
    否则要么把全部原图先读进内存再判断(破坏流式),要么在「文件本来就没图」时
    误删掉库里已有的截图。
    """
    try:
        with zipfile.ZipFile(xlsx_path) as z:
            part = _find_drawing_part(z, sheet_name)
            return bool(part and part in set(z.namelist()))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return False


def iter_doc_bug_image_rows(
    xlsx_path: str,
    sheet_name: str,
    key_by_sheet_row: dict[int, str],
    stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """逐张产出可直接入库的图片行(生成器:一次只在内存里放一张原图)。

    key_by_sheet_row: {sheet 行号(1-based): 文档故障编码} —— 只传**会被导入的行**,
    于是「无 sprint 的行 / 不属于本次项目的行」的图片天然被排除,与本表的存留范围一致。

    stats 会被填充:anchors_total / skipped_unknown_column / skipped_row_not_imported /
    skipped_no_media / images_yielded。
    """
    stats = stats if stats is not None else {}
    stats.update(
        anchors_total=0,
        skipped_unknown_column=0,
        skipped_row_not_imported=0,
        skipped_no_media=0,
        images_yielded=0,
    )

    if not key_by_sheet_row:
        return

    with zipfile.ZipFile(xlsx_path) as z:
        drawing_part = _find_drawing_part(z, sheet_name)
        if drawing_part is None or drawing_part not in set(z.namelist()):
            return

        anchors = parse_drawing_anchors(z, drawing_part)
        stats["anchors_total"] = len(anchors)

        # 排序口径:先按来源列(截图1 在 截图2 前),再按表内行序,最后按 drawing 里的出现次序
        col_rank = {c: i for i, c in enumerate(sorted(DOC_BUG_IMAGE_COLUMNS))}
        picked: list[tuple[str, str, dict[str, Any]]] = []
        for a in anchors:
            label = DOC_BUG_IMAGE_COLUMNS.get(a["col"])
            if label is None:
                stats["skipped_unknown_column"] += 1
                continue
            key = key_by_sheet_row.get(a["row"] + 1)
            if not key:
                stats["skipped_row_not_imported"] += 1
                continue
            picked.append((key, label, a))
        picked.sort(key=lambda t: (col_rank[t[2]["col"]], t[2]["row"], t[2]["order"]))

        seq_by_key: dict[str, int] = {}
        for key, label, a in picked:
            media = a["media"]
            if not media:
                stats["skipped_no_media"] += 1
                continue
            try:
                blob = z.read(media)
            except KeyError:
                stats["skipped_no_media"] += 1
                continue

            seq_by_key[key] = seq_by_key.get(key, 0) + 1
            width, height = read_png_size(blob)
            thumb, thumb_mime = make_thumbnail(blob)
            stats["images_yielded"] += 1

            yield {
                "doc_bug_key": key,
                "seq": seq_by_key[key],
                "column_label": label,
                "source_name": media,
                "mime_type": detect_mime(blob),
                "byte_size": len(blob),
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "thumb_mime": thumb_mime,
                "thumb_byte_size": len(thumb) if thumb else None,
                "data": blob,
                "thumb": thumb,
            }
