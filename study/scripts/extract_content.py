"""Extract searchable lecture content from PDF, PPTX, and DOCX files.

PDF uses PyMuPDF, with pypdf as a fallback. PPTX and DOCX use the standard
library to read their Office Open XML archives. Page and slide boundaries are
preserved; DOCX content follows document order because pagination varies by
renderer.

    python extract_content.py lecture.pdf
    python extract_content.py lecture.pptx --notes
    python extract_content.py lecture.docx
    python extract_content.py lecture.pdf --out outline.md
    python extract_content.py lecture.pdf --check
"""
from __future__ import annotations

import argparse
import posixpath
import re
import sys
import time
import warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree

warnings.filterwarnings("ignore")

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHARS_PER_PAGE_FLOOR = 40


class ExtractionError(Exception):
    """An input is missing, unreadable, or unsupported."""


def parse_xml(data: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ExtractionError("The document contains malformed XML.") from exc


def parse_page_range(spec: str, total: int) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start, end = (int(value) for value in part.split("-", 1))
            else:
                start = end = int(part)
        except ValueError as exc:
            raise ExtractionError(f"Invalid page range: {part!r}") from exc
        if start < 1 or end < start:
            raise ExtractionError(f"Invalid page range: {part!r}")
        pages.extend(range(start - 1, min(end, total)))
    return sorted(set(pages))


def tidy_pdf_text(text: str) -> str:
    result: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            result.append("")
        elif result and result[-1].endswith("-") and not result[-1].endswith("--"):
            result[-1] = result[-1][:-1] + stripped
        else:
            result.append(stripped)
    return "\n".join(result).strip()


def extract_pdf(path: Path, page_spec: str | None) -> tuple[str, str, int]:
    try:
        import pymupdf
    except ImportError:
        pymupdf = None

    if pymupdf is not None:
        try:
            document = pymupdf.open(path)
            if document.needs_pass:
                document.close()
                raise ExtractionError("PDF is password protected; decrypt it first.")
            pages = [page.get_text() for page in document]
            document.close()
            backend = "PyMuPDF"
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Cannot read PDF ({exc.__class__.__name__}).") from exc
    else:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ExtractionError(
                "No PDF backend is installed. Install PyMuPDF with `pip install pymupdf`; "
                "pypdf is also supported as a slower fallback."
            ) from exc
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise ExtractionError("PDF is password protected; decrypt it first.")
            pages = [page.extract_text() or "" for page in reader.pages]
            backend = "pypdf"
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Cannot read PDF ({exc.__class__.__name__}).") from exc

    if not pages:
        raise ExtractionError("PDF contains no pages.")
    indices = parse_page_range(page_spec, len(pages)) if page_spec else list(range(len(pages)))
    cleaned = [tidy_pdf_text(pages[index]) for index in indices]
    chars = sum(len(text) for text in cleaned)
    density = chars / len(indices) if indices else 0
    sparse = sum(len(text) < CHARS_PER_PAGE_FLOOR for text in cleaned)
    verdict = "NO TEXT LAYER" if not chars else "MOSTLY SCANNED" if density < CHARS_PER_PAGE_FLOOR else "OK"
    if chars and density >= CHARS_PER_PAGE_FLOOR and sparse:
        verdict = "TEXT WITH GAPS"
    output = [f"# {path.stem} — extracted PDF text", ""]
    for index, text in zip(indices, cleaned):
        output.extend([f"## Page {index + 1}", text or "_[no text on this page]_", ""])
    report = f"{verdict}; {chars} characters across {len(indices)} selected pages; backend: {backend}."
    if sparse:
        report += f" {sparse} page(s) have little or no extractable text."
    return "\n".join(output).rstrip() + "\n", report, 3 if not chars else 0


def render_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    def escape(cell: str) -> str:
        return cell.replace("|", "\\|").replace("\n", "<br>")

    lines = ["| " + " | ".join(escape(cell) for cell in normalized[0]) + " |"]
    lines.append("|" + "|".join("---" for _ in range(width)) + "|")
    lines.extend("| " + " | ".join(escape(cell) for cell in row) + " |" for row in normalized[1:])
    return lines


def pptx_text(node: ElementTree.Element) -> str:
    pieces: list[str] = []
    for child in node.iter():
        if child.tag == f"{A}t":
            pieces.append(child.text or "")
        elif child.tag == f"{A}br":
            pieces.append("\n")
    return "".join(pieces).strip()


def pptx_table(table: ElementTree.Element) -> list[list[str]]:
    return [[pptx_text(cell) for cell in row.iter(f"{A}tc")] for row in table.iter(f"{A}tr")]


def pptx_slide_order(archive: zipfile.ZipFile) -> list[str]:
    names = {name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)}
    if not names:
        raise ExtractionError("PPTX contains no slides.")
    try:
        presentation = parse_xml(archive.read("ppt/presentation.xml"))
        relationships = parse_xml(archive.read("ppt/_rels/presentation.xml.rels"))
    except KeyError:
        return sorted(names, key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))
    targets: dict[str, str] = {}
    for relationship in relationships.iter(f"{PKG_REL}Relationship"):
        rel_id, target = relationship.get("Id"), relationship.get("Target")
        if rel_id and target and relationship.get("TargetMode") != "External":
            targets[rel_id] = posixpath.normpath(posixpath.join("ppt", target))
    ordered: list[str] = []
    slide_list = presentation.find(f".//{P}sldIdLst")
    if slide_list is not None:
        for slide in slide_list.iter(f"{P}sldId"):
            part = targets.get(slide.get(f"{R}id", ""))
            if part in names and part not in ordered:
                ordered.append(part)
    ordered.extend(sorted(names - set(ordered), key=lambda name: int(re.search(r"slide(\d+)", name).group(1))))
    return ordered


def pptx_blocks(node: ElementTree.Element) -> list[str]:
    output: list[str] = []
    for child in node:
        if child.tag == f"{A}tbl":
            output.extend(["", *render_table(pptx_table(child)), ""])
        elif child.tag in (f"{P}sp", f"{P}graphicFrame"):
            table = child.find(f".//{A}tbl")
            if table is not None:
                output.extend(["", *render_table(pptx_table(table)), ""])
            else:
                text = pptx_text(child)
                if text:
                    output.extend(text.splitlines())
        else:
            output.extend(pptx_blocks(child))
    return output


def extract_pptx(path: Path, include_notes: bool) -> tuple[str, str, int]:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExtractionError("Cannot open this file as a PPTX archive.") from exc
    output = [f"# {path.stem} — extracted slides", ""]
    empty_slides = 0
    with archive:
        names = set(archive.namelist())
        slide_parts = pptx_slide_order(archive)
        for number, part in enumerate(slide_parts, 1):
            root = parse_xml(archive.read(part))
            lines = [line for line in pptx_blocks(root) if line.strip()]
            output.append(f"## Slide {number}")
            if lines:
                output.extend(lines)
            else:
                output.append("_[no extractable text; inspect slide visuals]_")
                empty_slides += 1
            output.append("")
            if not include_notes:
                continue
            rels_part = f"ppt/slides/_rels/{Path(part).name}.rels"
            if rels_part not in names:
                continue
            rels = parse_xml(archive.read(rels_part))
            for relationship in rels.iter(f"{PKG_REL}Relationship"):
                if (relationship.get("Type") or "").endswith("/notesSlide"):
                    notes_part = posixpath.normpath(posixpath.join("ppt/slides", relationship.get("Target", "")))
                    if notes_part in names:
                        notes_root = parse_xml(archive.read(notes_part))
                        notes = [pptx_text(node) for node in notes_root.iter(f"{A}p")]
                        notes = [text for text in notes if text and not re.fullmatch(r"\d+", text)]
                        if notes:
                            output.extend(["**Speaker notes**", *notes, ""])
        image_count = sum(name.startswith("ppt/media/") for name in names)
    report = f"{len(slide_parts)} slides extracted."
    if empty_slides:
        report += f" {empty_slides} slide(s) have no extractable text; inspect their visuals."
    if image_count:
        report += f" {image_count} embedded image(s) are not interpreted; inspect relevant visuals."
    return "\n".join(output).rstrip() + "\n", report, 0


def docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    pieces: list[str] = []
    for child in paragraph.iter():
        if child.tag == f"{W}t":
            pieces.append(child.text or "")
        elif child.tag in (f"{W}tab", f"{W}br", f"{W}cr"):
            pieces.append("\t" if child.tag == f"{W}tab} else "\n")
    return "".join(pieces).strip()


def docx_table(table: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall(f"{W}tr"):
        cells = []
        for cell in row.findall(f"{W}tc"):
            paragraphs = [docx_paragraph_text(p) for p in cell.findall(f"{W}p")]
            cells.append("<br>".join(text for text in paragraphs if text))
        rows.append(cells)
    return rows


def extract_docx(path: Path) -> tuple[str, str, int]:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExtractionError("Cannot open this file as a DOCX archive.") from exc
    with archive:
        try:
            root = parse_xml(archive.read("word/document.xml"))
        except KeyError as exc:
            raise ExtractionError("DOCX has no main document body.") from exc
        body = root.find(f"{W}body")
        if body is None:
            raise ExtractionError("DOCX has no main document body.")
        output = [f"# {path.stem} — extracted document", ""]
        paragraph_count = table_count = 0
        for block in body:
            if block.tag == f"{W}p":
                text = docx_paragraph_text(block)
                if not text:
                    continue
                style = block.find(f"{W}pPr/{W}pStyle")
                style_id = style.get(f"{W}val", "") if style is not None else ""
                heading = re.fullmatch(r"Heading\s*(\d+)", style_id, re.IGNORECASE)
                if heading:
                    level = min(int(heading.group(1)) + 1, 6)
                    output.extend([f"{'#' * level} {text}", ""])
                else:
                    output.extend([text, ""])
                paragraph_count += 1
            elif block.tag == f"{W}tbl":
                rendered = render_table(docx_table(block))
                if rendered:
                    output.extend([*rendered, ""])
                    table_count += 1
        image_count = sum(name.startswith("word/media/") for name in archive.namelist())
    report = f"{paragraph_count} paragraph(s) and {table_count} table(s) extracted in document order."
    if image_count:
        report += f" {image_count} embedded image(s) are not interpreted; inspect relevant visuals."
    return "\n".join(output).rstrip() + "\n", report, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract lecture content from PDF, PPTX, or DOCX.")
    parser.add_argument("file", help="input .pdf, .pptx, or .docx file")
    parser.add_argument("--notes", action="store_true", help="include PPTX speaker notes")
    parser.add_argument("--pages", help="PDF page range, for example 4-18,25")
    parser.add_argument("--check", action="store_true", help="report extraction health without printing content")
    parser.add_argument("--out", help="write extracted content to this Markdown file")
    args = parser.parse_args()
    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        return 4
    extension = path.suffix.lower()
    if extension not in {".pdf", ".pptx", ".docx"}:
        print("ERROR: Supported formats are PDF, PPTX, and DOCX.", file=sys.stderr)
        return 4
    if args.pages and extension != ".pdf":
        print("ERROR: --pages is supported only for PDF files.", file=sys.stderr)
        return 4
    started = time.perf_counter()
    try:
        if extension == ".pdf":
            content, report, status = extract_pdf(path, args.pages)
        elif extension == ".pptx":
            content, report, status = extract_pptx(path, args.notes)
        else:
            content, report, status = extract_docx(path)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    report += f" Extraction took {(time.perf_counter() - started) * 1000:.0f} ms."
    print(f"{path.name}: {report}", file=sys.stderr)
    if args.check or status == 3:
        return status
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"Saved: {target}", file=sys.stderr)
    else:
        sys.stdout.write(content)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
