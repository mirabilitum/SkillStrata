#!/usr/bin/env python3
"""
doc2md.py - 将 PDF/Word/Excel/PPT 等文档转换为适合 LLM 读取的 Markdown

用法:
  python doc2md.py input.pdf
  python doc2md.py input.docx -o output.md
  python doc2md.py ./docs/           # 批量处理目录
"""

import argparse
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


# --------------------------------------------------------------------------- #
# 文本后处理
# --------------------------------------------------------------------------- #

def sanitize_text(text: str) -> str:
    """Unicode NFKC 标准化 + 过滤控制字符，保留换行/制表符"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


def table_to_list(md_text: str) -> str:
    """将 Markdown 管道表格转为 LLM 友好的列表形式"""
    lines = md_text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            result.extend(_parse_table_block(block))
        else:
            result.append(line)
            i += 1
    return "\n".join(result)


def _parse_table_block(block: list[str]) -> list[str]:
    headers = []
    rows = []
    for line in block:
        if re.match(r"\|[\s:\-]+\|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not headers:
            headers = cells
        else:
            rows.append(cells)

    if not headers:
        return block

    out = []
    for idx, row in enumerate(rows):
        out.append(f"\n<!-- row {idx + 1} -->")
        for h, v in zip(headers, row):
            if h or v:
                out.append(f"- **{h or '—'}**：{v or '—'}")
    return out


# --------------------------------------------------------------------------- #
# LibreOffice 老格式转换（.doc / .xls / .ppt）
# --------------------------------------------------------------------------- #

def _find_soffice() -> str | None:
    candidates = [
        "soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if shutil.which(c) or Path(c).exists():
            return c
    return None


OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_SIGNATURE = b"PK"
LEGACY_CONVERT_TIMEOUT = 90

# 复审 P2-e：处理不可信文件的边界（zip bomb / 路径穿越 / 外部进程超时）。
_MAX_ZIP_ENTRIES = 5000            # 条目数上限
_MAX_ZIP_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # 解压总大小上限 500MB
_SOFFICE_TIMEOUT = 120             # LibreOffice 转换超时（秒）


def _guard_zip(zf: "zipfile.ZipFile") -> None:
    """对不可信 zip（docx/xlsx/pptx 本质是 zip）做 bomb / 穿越预检，越界即拒。"""
    infos = zf.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise ValueError(f"zip 条目过多（{len(infos)} > {_MAX_ZIP_ENTRIES}）：疑似 zip bomb")
    total = 0
    for info in infos:
        name = info.filename
        # 路径穿越：绝对路径 / .. 逃逸
        if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
            raise ValueError(f"zip 含不安全路径（疑似穿越）：{name}")
        total += info.file_size
        if total > _MAX_ZIP_TOTAL_UNCOMPRESSED:
            raise ValueError(
                f"zip 解压总大小超限（> {_MAX_ZIP_TOTAL_UNCOMPRESSED} 字节）：疑似 zip bomb"
            )


def _detect_container_format(path: Path) -> str | None:
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return None
    if header.startswith(ZIP_SIGNATURE):
        return "zip"
    if header == OLE_SIGNATURE:
        return "ole"
    return None


def _effective_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    container = _detect_container_format(path)
    if container == "ole" and suffix in {".docx", ".xlsx", ".pptx"}:
        return {".docx": ".doc", ".xlsx": ".xls", ".pptx": ".ppt"}[suffix]
    return suffix


def _make_temp_dir(base_dir: Path) -> str:
    base_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        tmp_dir = base_dir / f".doc2md_{uuid.uuid4().hex}"
        try:
            tmp_dir.mkdir()
            return str(tmp_dir)
        except FileExistsError:
            continue
    raise RuntimeError(f"无法创建临时目录: {base_dir}")


def _convert_via_word_com(path: Path, target_suffix: str, tmp_dir: str) -> Path:
    """用 Office COM 接口将老格式转为新格式"""
    import win32com.client
    src_path = path
    out = str(Path(tmp_dir) / (path.stem + target_suffix))
    src_suffix = _effective_suffix(path)
    if src_suffix != path.suffix.lower():
        src_path = Path(tmp_dir) / (path.stem + src_suffix)
        shutil.copy2(path, src_path)
    src = str(src_path.resolve())

    if src_suffix == ".doc":
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        try:
            doc = app.Documents.Open(
                src,
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                OpenAndRepair=True,
                NoEncodingDialog=True,
            )
            doc.SaveAs2(out, FileFormat=16)  # wdFormatXMLDocument
            doc.Close(False)
        finally:
            app.Quit()
    elif src_suffix == ".xls":
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        try:
            wb = app.Workbooks.Open(src, ReadOnly=True, CorruptLoad=1)
            wb.SaveAs(out, FileFormat=51)  # xlOpenXMLWorkbook
            wb.Close(False)
        finally:
            app.Quit()
    elif src_suffix == ".ppt":
        app = win32com.client.DispatchEx("PowerPoint.Application")
        app.Visible = False
        app.DisplayAlerts = 1
        try:
            prs = app.Presentations.Open(src, ReadOnly=True, WithWindow=False)
            prs.SaveAs(out, 24)  # ppSaveAsOpenXMLPresentation
            prs.Close()
        finally:
            app.Quit()
    else:
        raise RuntimeError(f"不支持的格式: {src_suffix}")

    return Path(out)


def _word_com_worker_cli() -> None:
    """CLI entry — called by subprocess to convert one file via COM.
    
    Prints the converted file path to stdout on success; writes error to
    stderr and exits with code 1 on failure.
    """
    import json as _json
    src = Path(sys.argv[2])
    target_suffix = sys.argv[3]
    tmp_dir = sys.argv[4]
    try:
        converted = _convert_via_word_com(src, target_suffix, tmp_dir)
        print(_json.dumps({"ok": str(converted)}), flush=True)
    except Exception as e:
        print(_json.dumps({"err": repr(e)}), file=sys.stderr, flush=True)
        sys.exit(1)


def _convert_via_word_com_with_timeout(
    path: Path, target_suffix: str, tmp_dir: str, timeout: int = LEGACY_CONVERT_TIMEOUT
) -> Path:
    """Spawn an isolated subprocess for COM conversion (avoids Windows spawn
    import issues when doc2md is loaded via importlib as ``doc2md_external``).
    """
    import json as _json
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()),
         "--_word_com_worker", str(path), target_suffix, tmp_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise TimeoutError(f"Word/Office COM conversion timed out after {timeout}s")

    if proc.returncode != 0:
        err = stderr.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(err)

    try:
        data = _json.loads(stdout.strip())
    except Exception:
        raise RuntimeError(f"Unexpected subprocess output: {stdout[:200]}")

    if "ok" in data:
        return Path(data["ok"])
    raise RuntimeError(data.get("err", "unknown error"))


def convert_legacy_format(
    path: Path, target_suffix: str, source_suffix: str | None = None
) -> Path:
    """将老格式转为新格式：优先 Word/Excel/PPT COM，其次 LibreOffice"""
    tmp_dir = _make_temp_dir(path.parent)

    # Windows COM 方式
    if sys.platform == "win32":
        try:
            return _convert_via_word_com_with_timeout(path, target_suffix, tmp_dir)
        except Exception as e:
            print(f"  Word COM 转换失败，尝试 LibreOffice: {e}", file=sys.stderr)

    # LibreOffice 后备
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            f"无法处理 {source_suffix or path.suffix} 格式：Word COM 不可用且未找到 LibreOffice。\n"
            "请确保本机安装了 Microsoft Word 或 LibreOffice。"
        )
    fmt_map = {".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}
    subprocess.run(
        [soffice, "--headless", "--convert-to", fmt_map[target_suffix],
         "--outdir", tmp_dir, str(path)],
        check=True, capture_output=True, timeout=_SOFFICE_TIMEOUT  # 复审 P2-e：外部进程超时
    )
    converted = Path(tmp_dir) / (path.stem + target_suffix)
    if not converted.exists():
        raise RuntimeError(f"LibreOffice 转换失败，未生成 {converted}")
    return converted


# --------------------------------------------------------------------------- #
# PDF 处理
# --------------------------------------------------------------------------- #

def _is_scanned(doc) -> bool:
    pages = min(5, len(doc))
    total = sum(len(doc[i].get_text().strip()) for i in range(pages))
    return (total / pages) < 100 if pages else True


def _pdf_pages_to_images(doc, assets_dir: Path, stem: str) -> list[tuple[int, str]]:
    import fitz
    refs = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        name = f"{stem}_page_{i + 1:03d}.png"
        pix.save(str(assets_dir / name))
        refs.append((i + 1, name))
    return refs


def _extract_pdf_images(doc, assets_dir: Path, stem: str) -> list[str]:
    seen = set()
    filenames = []
    counter = 1
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base = doc.extract_image(xref)
                ext = base["ext"]
                name = f"{stem}_img_{counter:03d}.{ext}"
                (assets_dir / name).write_bytes(base["image"])
                filenames.append(name)
                counter += 1
            except Exception:
                pass
    return filenames


def process_pdf(path: Path, assets_dir: Path) -> str:
    try:
        import fitz
    except ImportError:
        sys.exit("缺少依赖: pip install pymupdf")

    stem = path.stem
    doc = fitz.open(str(path))

    if _is_scanned(doc):
        refs = _pdf_pages_to_images(doc, assets_dir, stem)
        lines = [f"# {stem}\n", "> 扫描版 PDF，已将每页转为图片。\n"]
        for page_num, name in refs:
            lines += [f"\n## 第 {page_num} 页\n", f"![第{page_num}页](assets/{name})\n"]
        return "\n".join(lines)

    parts = []
    img_counter = 1
    seen_xrefs = set()

    for i, page in enumerate(doc):
        parts.append(f"## 第 {i + 1} 页")

        # 收集文字块：(y0, "text", text)
        # 收集图片块：(y0, "img", xref, bbox)
        elements = []
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] == 0:  # 文字
                text = "\n".join(
                    span["text"] for line in block["lines"] for span in line["spans"]
                ).strip()
                if text:
                    elements.append((block["bbox"][1], "text", text))
            elif block["type"] == 1:  # 内嵌图片
                xref = block.get("xref", 0)
                elements.append((block["bbox"][1], "img", xref, block["bbox"]))

        # 浮动图片（非文字流中的图片，通过 get_images 获取）
        page_img_xrefs = {b.get("xref") for b in blocks if b["type"] == 1}
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in page_img_xrefs:
                continue  # 已在文字流中
            # 找图片在页面上的位置
            rects = page.get_image_rects(xref)
            y0 = rects[0].y0 if rects else 99999
            elements.append((y0, "img", xref, None))

        elements.sort(key=lambda e: e[0])

        for el in elements:
            if el[1] == "text":
                parts.append(el[2])
            elif el[1] == "img":
                xref = el[2]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    base = doc.extract_image(xref)
                    ext = base["ext"]
                    name = f"{stem}_img_{img_counter:03d}.{ext}"
                    (assets_dir / name).write_bytes(base["image"])
                    parts.append(f"![图片](assets/{name})")
                    img_counter += 1
                except Exception:
                    pass

    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# DOCX 处理（按文档结构顺序，图片嵌入原位）
# --------------------------------------------------------------------------- #

# docx XML 命名空间
_W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A  = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DML_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def _save_image_from_part(part, assets_dir: Path, stem: str, counter: int) -> str | None:
    try:
        blob = part.blob
        ext = part.content_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        name = f"{stem}_img_{counter:03d}.{ext}"
        (assets_dir / name).write_bytes(blob)
        return name
    except Exception:
        return None


def _para_images(para, doc_part, assets_dir: Path, stem: str, counter_ref: list) -> list[str]:
    """从段落的 drawing/inline 和 VML pict 元素中提取图片，返回 markdown 图片引用列表"""
    from lxml import etree
    imgs = []
    NS_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
    NS_BLIP = "http://schemas.openxmlformats.org/drawingml/2006/main"
    NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    NS_O = "urn:schemas-microsoft-com:office:office"
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    VML_NS = "urn:schemas-microsoft-com:vml"

    # ── DrawingML 图片 ──
    for drawing in para._element.iter(f"{{{W_NS}}}drawing"):
        # 找 blip（图片数据引用）
        for blip in drawing.iter(f"{{{NS_DRAWING}}}blip"):
            rEmbed = blip.get(f"{{{NS_R}}}embed")
            if not rEmbed:
                continue
            try:
                img_part = doc_part.rels[rEmbed].target_part
                name = _save_image_from_part(img_part, assets_dir, stem, counter_ref[0])
                if name:
                    imgs.append(f"![图片](assets/{name})")
                    counter_ref[0] += 1
            except Exception:
                pass

    # ── VML 图片（w:pict → v:shape → v:imagedata）──
    for pict in para._element.iter(f"{{{W_NS}}}pict"):
        for imagedata in pict.iter(f"{{{VML_NS}}}imagedata"):
            rId = imagedata.get(f"{{{NS_R}}}id") or imagedata.get(f"{{{NS_O}}}relid")
            if not rId:
                continue
            try:
                img_part = doc_part.rels[rId].target_part
                name = _save_image_from_part(img_part, assets_dir, stem, counter_ref[0])
                if name:
                    imgs.append(f"![图片](assets/{name})")
                    counter_ref[0] += 1
            except Exception:
                pass

    return imgs


def _render_para(para, doc_part, assets_dir: Path, stem: str, counter_ref: list) -> list[str]:
    """将一个段落渲染为 markdown 行（含内嵌图片）"""
    lines = []
    imgs = _para_images(para, doc_part, assets_dir, stem, counter_ref)
    text = para.text.strip()
    style = para.style.name.lower() if para.style else ""

    if text:
        if style.startswith("heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 2
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)

    lines.extend(imgs)
    return lines


_KEY_VALUE_LABEL_RE = re.compile(
    r"(姓名|单位|手机|电话|邮箱|QQ|职务|职称|身份证|证件|照片|领域|"
    r"课题|专题|简介|银行|账号|户名|开户|支行|资格|专业|类别|"
    r"性别|发证|时间|日期|编号|学历|学位|地址|区域|民族|政治)"
)


def _cell_markdown(cell, doc_part, assets_dir: Path, stem: str, counter_ref: list) -> str:
    cell_text = cell.text.strip()
    cell_imgs = []
    for para in cell.paragraphs:
        cell_imgs.extend(_para_images(para, doc_part, assets_dir, stem, counter_ref))
    if cell_imgs:
        img_refs = " ".join(cell_imgs)
        cell_text = f"{cell_text} {img_refs}".strip() if cell_text else img_refs
    return cell_text


def _compact_cell_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_key_value_label(text: str) -> bool:
    compact = _compact_cell_text(text)
    if not compact:
        return False
    if len(compact) > 48:
        return False
    if re.search(r"@\w+|\d{6,}|https?://|www\.", compact, flags=re.I):
        return False
    if _KEY_VALUE_LABEL_RE.search(compact):
        return True
    if len(compact) <= 12 and re.search(r"(号|表|码)$", compact):
        return True
    return False


def _is_key_value_table(table) -> bool:
    if not table.rows:
        return False
    col_count = len(table.rows[0].cells)
    if col_count < 2 or col_count % 2 != 0:
        return False

    scored_rows = 0
    key_value_rows = 0
    for row in table.rows:
        cells = [_compact_cell_text(cell.text) for cell in row.cells]
        if not any(cells):
            continue
        even_labels = sum(1 for idx in range(0, len(cells), 2) if _is_key_value_label(cells[idx]))
        odd_labels = sum(1 for idx in range(1, len(cells), 2) if _is_key_value_label(cells[idx]))
        scored_rows += 1
        if even_labels >= 1 and even_labels > odd_labels:
            key_value_rows += 1

    return scored_rows > 0 and key_value_rows / scored_rows >= 0.5


def _render_table(table, doc_part, assets_dir: Path, stem: str, counter_ref: list) -> list[str]:
    """将表格渲染为 LLM 友好列表，单元格内图片按位置嵌入"""
    if not table.rows:
        return []
    lines = []
    if _is_key_value_table(table):
        for idx, row in enumerate(table.rows, 1):
            lines.append(f"\n<!-- row {idx} -->")
            previous_values = set()
            cells = list(row.cells)
            for cell_idx in range(0, len(cells) - 1, 2):
                key = cells[cell_idx].text.strip()
                value = _cell_markdown(cells[cell_idx + 1], doc_part, assets_dir, stem, counter_ref)
                compact_key = _compact_cell_text(key)
                compact_value = _compact_cell_text(value)
                if not compact_key:
                    continue
                if compact_key == compact_value or compact_key in previous_values:
                    continue
                previous_values.add(compact_value)
                lines.append(f"- **{key or '—'}**：{value or '—'}")
        return lines

    headers = []
    for cell in table.rows[0].cells:
        headers.append(cell.text.strip())

    for idx, row in enumerate(table.rows[1:], 1):
        lines.append(f"\n<!-- row {idx} -->")
        for h, cell in zip(headers, row.cells):
            cell_text = _cell_markdown(cell, doc_part, assets_dir, stem, counter_ref)
            lines.append(f"- **{h or '—'}**：{cell_text or '—'}")
    return lines


def _iter_block_elements(doc):
    """按文档顺序迭代顶层块元素（段落和表格），保持原始顺序"""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    body = doc.element.body
    for child in body:
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _relationship_target_member(rels_name: str, target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    if "/_rels/" in rels_name:
        base = rels_name.split("/_rels/", 1)[0]
    elif rels_name == "_rels/.rels":
        base = ""
    else:
        base = posixpath.dirname(rels_name)
    return posixpath.normpath(posixpath.join(base, target)).lstrip("./")


def _repair_docx_relationships(path: Path, repaired: Path) -> Path | None:
    changed = False

    try:
        with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(repaired, "w") as zout:
            _guard_zip(zin)  # 复审 P2-e：bomb / 穿越预检
            members = set(zin.namelist())
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".rels"):
                    try:
                        root = ET.fromstring(data)
                    except ET.ParseError:
                        zout.writestr(item, data)
                        continue

                    for rel in list(root):
                        target = rel.get("Target")
                        if not target or rel.get("TargetMode") == "External":
                            continue
                        member = _relationship_target_member(item.filename, target)
                        if member not in members:
                            root.remove(rel)
                            changed = True

                    if changed:
                        ET.register_namespace("", REL_NS)
                        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)

                zout.writestr(item, data)
    except zipfile.BadZipFile:
        return None

    return repaired if changed else None


def process_docx(path: Path, assets_dir: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        sys.exit("缺少依赖: pip install python-docx")

    assets_dir.mkdir(parents=True, exist_ok=True)
    repaired_path = assets_dir / f".repaired_{path.stem}_{os.getpid()}.docx"
    repaired = _repair_docx_relationships(path, repaired_path)
    doc_path = repaired or path
    try:
        doc = Document(str(doc_path))
        stem = path.stem
        counter_ref = [1]
        parts = []

        for block in _iter_block_elements(doc):
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            if isinstance(block, Paragraph):
                lines = _render_para(block, doc.part, assets_dir, stem, counter_ref)
                parts.extend(lines)
            elif isinstance(block, Table):
                parts.extend(_render_table(block, doc.part, assets_dir, stem, counter_ref))
    finally:
        if repaired and repaired.exists():
            try:
                repaired.unlink(missing_ok=True)
            except OSError:
                pass

    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# PPTX 处理（按幻灯片顺序，文字与图片混排）
# --------------------------------------------------------------------------- #

def process_pptx(path: Path, assets_dir: Path) -> str:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import PP_PLACEHOLDER
    except ImportError:
        sys.exit("缺少依赖: pip install python-pptx")

    stem = path.stem
    prs = Presentation(str(path))
    parts = []
    img_counter = 1

    for slide_idx, slide in enumerate(prs.slides, 1):
        parts.append(f"## 第 {slide_idx} 页")

        # 按形状在页面上的位置排序（从上到下）
        shapes = sorted(slide.shapes, key=lambda s: (s.top or 0, s.left or 0))

        for shape in shapes:
            # 文本框
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        parts.append(text)

            # 图片
            if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                try:
                    blob = shape.image.blob
                    ext = shape.image.ext
                    name = f"{stem}_img_{img_counter:03d}.{ext}"
                    (assets_dir / name).write_bytes(blob)
                    parts.append(f"![图片](assets/{name})")
                    img_counter += 1
                except Exception:
                    pass

            # 表格
            if shape.has_table:
                table = shape.table
                if table.rows:
                    headers = [table.cell(0, c).text.strip() for c in range(len(table.columns))]
                    for r_idx in range(1, len(table.rows)):
                        parts.append(f"\n<!-- row {r_idx} -->")
                        for c_idx, h in enumerate(headers):
                            cell = table.cell(r_idx, c_idx)
                            v = cell.text.strip()
                            parts.append(f"- **{h or '—'}**：{v or '—'}")

    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# XLSX 处理（按行输出，图片嵌入锚定单元格所在行）
# --------------------------------------------------------------------------- #

def process_xlsx(path: Path, assets_dir: Path) -> str:
    try:
        import openpyxl
        from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor, OneCellAnchor, AbsoluteAnchor
    except ImportError:
        sys.exit("缺少依赖: pip install openpyxl")

    stem = path.stem
    wb = openpyxl.load_workbook(str(path), data_only=True)
    img_counter = 1
    parts = []

    for sheet in wb.worksheets:
        parts.append(f"## {sheet.title}")

        # 收集图片的锚定行：{row_index: [md_img_ref, ...]}
        img_by_row: dict[int, list[str]] = {}
        for drawing in sheet._images:
            anchor = drawing.anchor
            try:
                if isinstance(anchor, (TwoCellAnchor, OneCellAnchor)):
                    row = anchor._from.row + 1  # openpyxl 0-based → 1-based
                elif isinstance(anchor, AbsoluteAnchor):
                    # AbsoluteAnchor 没有行信息，放到第 0 行（输出在 sheet 标题后）
                    row = 0
                else:
                    row = 0
            except Exception:
                row = 0

            try:
                img_data = drawing._data()
                ext = drawing.format or "png"
                name = f"{stem}_img_{img_counter:03d}.{ext}"
                (assets_dir / name).write_bytes(img_data)
                img_by_row.setdefault(row, []).append(f"![图片](assets/{name})")
                img_counter += 1
            except Exception:
                pass

        # 输出行 0 的浮动图片（无锚定行）
        if 0 in img_by_row:
            parts.extend(img_by_row[0])

        # 读取有内容的行范围
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [str(c) if c is not None else "" for c in rows[0]]

        for row_idx, row in enumerate(rows[1:], 2):
            row_parts = []
            for h, val in zip(headers, row):
                v = str(val).strip() if val is not None else ""
                cell_imgs = img_by_row.get(row_idx, [])
                if cell_imgs:
                    # 图片附加到最后一个有值的列，或直接追加
                    v = (v + " " + " ".join(cell_imgs)).strip()
                    img_by_row.pop(row_idx, None)  # 已消费，避免重复
                if h or v:
                    row_parts.append(f"- **{h or '—'}**：{v or '—'}")
            if row_parts:
                parts.append(f"\n<!-- row {row_idx - 1} -->")
                parts.extend(row_parts)

        # 没有匹配到具体列的图片（行存在但列数超出）
        for row_idx, imgs in img_by_row.items():
            if row_idx > 1:
                parts.append(f"\n<!-- row {row_idx - 1} 图片 -->")
                parts.extend(imgs)

    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# 通用处理（HTML / TXT / CSV …）
# --------------------------------------------------------------------------- #

def process_generic(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError:
        sys.exit("缺少依赖: pip install markitdown")
    return MarkItDown().convert(str(path)).text_content


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

SUPPORTED = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
             ".html", ".htm", ".txt", ".csv", ".rtf"}

LEGACY_MAP = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}


def _iter_supported_files(input_path: Path):
    for root, dirs, filenames in os.walk(input_path):
        dirs[:] = [
            d
            for d in dirs
            if d.lower() != "assets"
            and not d.startswith(".")
            and not d.startswith("doc2md_")
            and not d.startswith("_doc2md_")
        ]
        root_path = Path(root)
        for filename in filenames:
            if filename.startswith("."):
                continue
            f = root_path / filename
            if f.suffix.lower() in SUPPORTED:
                yield f


def convert_file(input_path: Path, output_path: Path | None = None) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if output_path is None:
        output_path = input_path.with_suffix(".md")

    assets_dir = output_path.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    suffix = _effective_suffix(input_path)
    tmp_dir = None

    # 老格式先转换为新格式
    if suffix in LEGACY_MAP:
        target_suffix = LEGACY_MAP[suffix]
        converted = convert_legacy_format(input_path, target_suffix, suffix)
        tmp_dir = str(converted.parent)
        input_path = converted
        suffix = target_suffix

    try:
        if suffix == ".pdf":
            md = process_pdf(input_path, assets_dir)
        elif suffix == ".docx":
            md = process_docx(input_path, assets_dir)
        elif suffix == ".xlsx":
            md = process_xlsx(input_path, assets_dir)
        elif suffix == ".pptx":
            md = process_pptx(input_path, assets_dir)
        else:
            md = process_generic(input_path)
    finally:
        if tmp_dir and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    md = sanitize_text(md)
    md = table_to_list(md)

    output_path.write_text(md, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="文档 → LLM 友好 Markdown")
    parser.add_argument("input", help="输入文件或目录")
    parser.add_argument("-o", "--output", help="输出文件路径（单文件时有效）")
    args = parser.parse_args()

    input_path = Path(args.input)

    if input_path.is_dir():
        files = list(_iter_supported_files(input_path))
        if not files:
            print("目录中没有可处理的文件。")
            return
        for f in files:
            print(f"START {f.name}", flush=True)
            try:
                out = convert_file(f)
                print(f"OK    {f.name}  →  {out.name}", flush=True)
            except Exception as e:
                print(f"SKIP  {f.name}: {e}", file=sys.stderr, flush=True)
    else:
        out = convert_file(input_path, Path(args.output) if args.output else None)
        print(f"已生成: {out}")


if __name__ == "__main__":
    if "--_word_com_worker" in sys.argv:
        _word_com_worker_cli()
    else:
        main()
