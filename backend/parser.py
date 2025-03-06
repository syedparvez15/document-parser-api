"""
Universal Document Parser — Multi-language PDF Extraction
=========================================================
Parses structured PDF documents containing tabular or record-based data.

Supports:
  - Standard PDFs via pdfplumber
  - Multi-language content (Latin script + Unicode scripts)
  - Auto-detection of document language per page
  - Both combined and split header formats

Usage:
    from parser import extract, extract_from_bytes

    # From file path
    records = extract("path/to/document.pdf")

    # From bytes (in-memory upload)
    records = extract_from_bytes(pdf_bytes, "document.pdf")
"""

import re
import zipfile
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False

# ── Compiled Patterns ─────────────────────────────────────────────────────────
REF_ID_RE   = re.compile(r'\b[A-Z]{2}\d{8,}\b')
GROUP_RE    = re.compile(r'^\d+-[\d\w*]+(?:[/&][\w\d]+)*$')
VALUE_RE    = re.compile(r'^[1-9][0-9]?$')
FOOTER_RE   = re.compile(r'^Page \d+ of \d+$')

# Header patterns
COMBINED_HEADER = re.compile(
    r'Document Section No & Name:\s*(\d+)\s*-\s*(.+?)\s+Batch No:\s*(\d+)'
)
BATCH_RE    = re.compile(r'Batch No:\s*(\d+)')
SECTION_RE  = re.compile(r'^(\d+)\s*-\s*(.+)$')

# Category markers
CAT_A_MARKERS = {"F", "H", "O", "M"}       # relation type tokens
CAT_B_MARKERS = {"తర", "ద"}                 # Unicode relation markers

UNICODE_CAT_A = {"పప", "పప్"}
UNICODE_CAT_B = {"భ"}

HEADER_SKIP = {
    "Section No Group No Category Value",
    "Document Section No & Name:",
    "Batch No Seq. No Record Name Rln Type Relation Name Ref ID",
    "Batch No Seq. No Section No Group No Record Name Rln Type Relation Name Category Value Ref ID",
}


@dataclass
class ParsedRecord:
    document_id:      str
    sequence_no:      str
    section_no:       str
    group_no:         str
    primary_name:     str
    relation_type:    Optional[str]
    relation_name:    str
    reference_id:     Optional[str]
    category:         Optional[str]
    value:            Optional[int]
    page_no:          int
    pdf_source:       str
    language:         str
    parse_confidence: str
    parse_notes:      str


def _is_unicode(text: str) -> bool:
    """Check if text contains Unicode (non-Latin) script characters."""
    return any('\u0900' <= c <= '\u0C7F' for c in text)


def _detect_language(lines: list) -> str:
    """Detect document language — returns 'unicode' or 'en'."""
    unicode_lines = sum(1 for line in lines if _is_unicode(line))
    threshold = max(len(lines) * 0.15, 2)
    return "unicode" if unicode_lines > threshold else "en"


def _parse_header(lines: list) -> tuple:
    """
    Extract batch number, section number, and section name from page header.
    Handles both combined and split header formats.

    Returns:
        (batch_no, section_no, section_name)
    """
    batch_no = "?"
    sec_no = "?"
    sec_name = "?"

    for line in lines[:8]:
        # Combined header format
        match = COMBINED_HEADER.match(line.strip())
        if match:
            sec_no   = match.group(1)
            sec_name = match.group(2).strip()
            batch_no = match.group(3)
            return batch_no, sec_no, sec_name

        # Split header format
        m2 = BATCH_RE.search(line)
        if m2:
            batch_no = m2.group(1)

        m3 = SECTION_RE.match(line.strip())
        if m3:
            sec_no   = m3.group(1)
            sec_name = m3.group(2).strip()

    return batch_no, sec_no, sec_name


def _get_pages(pdf_path: str) -> list:
    """
    Load pages from a PDF file.
    Returns a list of dicts: [{page_number, text}, ...]
    """
    # Try ZIP-format first (internal format)
    try:
        with zipfile.ZipFile(pdf_path) as zf:
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json"))
                return [
                    {
                        "page_number": p["page_number"],
                        "text": zf.read(p["text"]["path"]).decode("utf-8"),
                    }
                    for p in manifest["pages"]
                ]
    except Exception:
        pass

    # Standard PDF via pdfplumber
    if not PDFPLUMBER_OK:
        raise ValueError(
            "Cannot read PDF: install pdfplumber with: pip install pdfplumber"
        )
    try:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                pages.append({"page_number": i, "text": text})
        return pages
    except Exception as e:
        raise ValueError(f"Could not read PDF: {e}")


def _parse_unicode_line(raw, batch_no, sec_no, sec_name, page_no, pdf_source):
    """Parse a record line from a Unicode-script (non-Latin) document."""
    tokens = raw.split()
    if len(tokens) < 5 or tokens[0] != batch_no or not tokens[1].isdigit():
        return None

    seq_no = tokens[1]
    work = tokens[2:]
    notes = []

    ref_idx   = next((i for i, t in enumerate(work) if REF_ID_RE.match(t)), None)
    group_idx = next((i for i, t in enumerate(work) if GROUP_RE.match(t)), None)
    ref_after = ref_idx is not None and group_idx is not None and ref_idx > group_idx

    tail_end = ref_idx if ref_after else len(work)
    value = category = None
    value_idx = cat_idx = None

    for i in range(tail_end - 1, -1, -1):
        if value is None and VALUE_RE.match(work[i]):
            value = int(work[i])
            value_idx = i
        elif value is not None and category is None:
            if work[i] in UNICODE_CAT_A:
                category = "A"
                cat_idx = i
                break
            elif work[i] in UNICODE_CAT_B:
                category = "B"
                cat_idx = i
                break
            break

    group_no   = work[group_idx] if group_idx is not None else ""
    section_no = group_no.split("-")[0].lstrip("*") if group_no else ""

    if group_idx is not None and group_idx <= 1:
        name_start = group_idx + 1
        name_end   = cat_idx if cat_idx else tail_end
        name_zone  = [t for t in work[name_start:name_end] if t not in CAT_B_MARKERS]
    else:
        if group_idx is not None:
            left_end = group_idx
            if left_end > 0 and work[left_end - 1] == "1":
                left_end -= 1
            name_zone = work[:left_end]
        else:
            name_zone = work[:value_idx] if value_idx else work
            notes.append("no_group")
        if ref_idx is not None and not ref_after:
            name_zone = [t for t in name_zone if not REF_ID_RE.match(t)]

    sep = sep_pos = None
    for i, t in enumerate(name_zone):
        if t in CAT_B_MARKERS:
            sep = t
            sep_pos = i
            break

    if sep_pos is not None:
        primary_tokens  = name_zone[:sep_pos]
        relation_tokens = name_zone[sep_pos + 1:]
    else:
        mid = max(1, len(name_zone) // 2)
        primary_tokens  = name_zone[:mid]
        relation_tokens = name_zone[mid:]
        if name_zone:
            notes.append("heuristic_split")

    reference_id   = work[ref_idx] if ref_idx is not None else None
    primary_name   = " ".join(primary_tokens).strip()
    relation_name  = " ".join(relation_tokens).strip()
    confidence     = (
        "HIGH"   if (group_no and value and reference_id and sep) else
        "MEDIUM" if (group_no and value) else
        "LOW"
    )

    return ParsedRecord(
        document_id=batch_no, sequence_no=seq_no, section_no=section_no,
        group_no=group_no, primary_name=primary_name, relation_type=sep,
        relation_name=relation_name, reference_id=reference_id,
        category=category, value=value, page_no=page_no,
        pdf_source=pdf_source, language="unicode",
        parse_confidence=confidence, parse_notes=" | ".join(notes),
    )


def _parse_english_line(raw, batch_no, sec_no, sec_name, page_no, pdf_source):
    """Parse a record line from an English/Latin-script document."""
    tokens = raw.split()
    if len(tokens) < 6 or tokens[0] != batch_no or not tokens[1].isdigit():
        return None

    seq_no = tokens[1]
    notes = []

    reference_id = None
    clean = []
    for t in tokens[2:]:
        if REF_ID_RE.match(t):
            reference_id = t
        else:
            clean.append(t)
    tokens = clean

    value = None
    value_idx = None
    for i in range(len(tokens) - 1, -1, -1):
        if VALUE_RE.match(tokens[i]):
            value = int(tokens[i])
            value_idx = i
            break

    category = None
    cat_idx = None
    if value_idx and value_idx > 0 and tokens[value_idx - 1] in CAT_A_MARKERS:
        category = tokens[value_idx - 1]
        cat_idx = value_idx - 1

    section_no = ""
    group_no = ""
    group_idx = None
    if tokens and tokens[0].isdigit():
        section_no = tokens[0]
        if len(tokens) > 1 and re.match(r'^\d+-', tokens[1]):
            group_no = tokens[1]
            group_idx = 1
    elif tokens and re.match(r'^\d+-', tokens[0]):
        group_no = tokens[0]
        group_idx = 0

    name_start = (group_idx + 1) if group_idx is not None else 1
    name_end   = cat_idx if cat_idx is not None else (value_idx or len(tokens))
    name_zone  = tokens[name_start:name_end]

    sep = sep_pos = None
    for i, t in enumerate(name_zone):
        if t in CAT_A_MARKERS and i > 0:
            sep = t
            sep_pos = i
            break

    if sep_pos is not None:
        primary_tokens  = name_zone[:sep_pos]
        relation_tokens = [t for t in name_zone[sep_pos + 1:] if t != "X"]
    else:
        mid = max(1, len(name_zone) // 2)
        primary_tokens  = name_zone[:mid]
        relation_tokens = name_zone[mid:]
        notes.append("heuristic_split")

    primary_name  = " ".join(primary_tokens).strip()
    relation_name = " ".join(relation_tokens).strip()
    confidence    = (
        "HIGH"   if (group_no and value and sep) else
        "MEDIUM" if (group_no and value) else
        "LOW"
    )

    return ParsedRecord(
        document_id=batch_no, sequence_no=seq_no, section_no=section_no,
        group_no=group_no, primary_name=primary_name, relation_type=sep,
        relation_name=relation_name, reference_id=reference_id,
        category=category, value=value, page_no=page_no,
        pdf_source=pdf_source, language="en",
        parse_confidence=confidence, parse_notes=" | ".join(notes),
    )


def _parse_page(text: str, page_no: int, pdf_source: str) -> list:
    """Parse all records from a single page of text."""
    lines = text.strip().splitlines()
    batch_no, sec_no, sec_name = _parse_header(lines)
    lang = _detect_language(lines)
    parser = _parse_unicode_line if lang == "unicode" else _parse_english_line

    records = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in HEADER_SKIP or FOOTER_RE.match(stripped):
            continue
        if not re.match(rf'^\s*{re.escape(batch_no)}\s+\d+', line):
            continue
        rec = parser(stripped, batch_no, sec_no, sec_name, page_no, pdf_source)
        if rec:
            records.append(rec)
    return records


def extract(path: str, source_name: str = None) -> list:
    """
    Extract parsed records from a PDF file.

    Args:
        path: Path to the PDF file.
        source_name: Override the source label (defaults to filename).

    Returns:
        List of ParsedRecord dataclass instances.
    """
    source_name = source_name or Path(path).name
    pages = _get_pages(path)
    records = []
    for page in pages:
        records.extend(_parse_page(page["text"], page["page_number"], source_name))
    return records


def extract_to_dicts(path: str, source_name: str = None) -> list:
    """Extract records and return as list of plain dicts."""
    return [asdict(r) for r in extract(path, source_name)]


def extract_from_bytes(data: bytes, source_name: str = "uploaded.pdf") -> list:
    """
    Extract records from raw PDF bytes (in-memory, no disk writes).

    Writes data to a temporary file, extracts records, then immediately
    deletes the temp file. Safe for use in upload endpoints.

    Args:
        data: Raw PDF bytes.
        source_name: Label to associate with extracted records.

    Returns:
        List of record dicts.
    """
    import tempfile
    import os

    suffix = Path(source_name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return [asdict(r) for r in extract(tmp_path, source_name)]
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
