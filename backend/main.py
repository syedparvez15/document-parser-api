"""
Document Parser & Search API — v2.0
=====================================
A FastAPI backend for uploading, parsing, and searching structured PDF documents.

Features:
  - PDF upload with in-memory OCR extraction (no files stored to disk)
  - Full-text search with FTS5 indexing
  - Fuzzy name matching via rapidfuzz
  - Multi-language document support (Latin + Unicode scripts)
  - Session-based uploads — non-base documents are cleared on restart

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import sqlite3
import re
import io
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rapidfuzz import fuzz

try:
    from indic_transliteration import sanscript
    from indic_transliteration.sanscript import transliterate
    TRANSLIT_OK = True
except ImportError:
    TRANSLIT_OK = False

DB_PATH = Path("./data/documents.db")

# ── Base documents — these persist across restarts ─────────────────────────────
# Add filenames here to make them permanent across server restarts.
BASE_DOCUMENTS: set = set()


# ── Startup: clear session-only uploads ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    """
    On every server start: remove all non-base uploaded documents from DB.
    This ensures session-only uploads don't accumulate across restarts.
    """
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            all_sources = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT pdf_source FROM records WHERE pdf_source IS NOT NULL"
                ).fetchall()
            ]
            to_delete = [s for s in all_sources if s not in BASE_DOCUMENTS]
            if to_delete:
                for src in to_delete:
                    conn.execute("DELETE FROM records WHERE pdf_source=?", (src,))
                conn.commit()
                _rebuild_fts(conn)
                print(f"[startup] Cleared {len(to_delete)} session document(s): {to_delete}")
            else:
                print("[startup] DB clean — only base documents present")
            total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            print(f"[startup] Ready — {total} records loaded")
            conn.close()
        except Exception as e:
            print(f"[startup] Warning during cleanup: {e}")
    yield


app = FastAPI(
    title="Document Parser & Search API",
    description="Upload, parse, and search structured PDF documents with full-text and fuzzy search.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ─────────────────────────────────────────────────────────────────────
class ParsedRecord(BaseModel):
    id: int
    document_id: Optional[str]
    sequence_no: Optional[str]
    section_no: Optional[str]
    group_no: Optional[str]
    primary_name: Optional[str]
    primary_name_en: Optional[str]
    relation_type: Optional[str]
    relation_name: Optional[str]
    relation_name_en: Optional[str]
    reference_id: Optional[str]
    category: Optional[str]
    value: Optional[int]
    page_no: Optional[int]
    pdf_source: Optional[str]
    language: Optional[str]
    parse_confidence: Optional[str]
    parse_notes: Optional[str]


class FuzzyResult(BaseModel):
    record: ParsedRecord
    match_score: int
    match_on: str


class FuzzyResponse(BaseModel):
    total_results: int
    fuzzy_threshold: int
    query: str
    results: list[FuzzyResult]


class SearchResponse(BaseModel):
    total_results: int
    page: int
    page_size: int
    total_pages: int
    search_mode: str
    query_used: dict
    results: list[ParsedRecord]


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_conn():
    if not DB_PATH.exists():
        raise HTTPException(503, "Database not found. Run: python ingest.py first.")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _normalize(text):
    if not text:
        return text
    return " ".join(text.split()).strip()


def _is_unicode_script(text):
    return any("\u0C00" <= c <= "\u0C7F" for c in (text or "")) or \
           any("\u0900" <= c <= "\u097F" for c in (text or ""))


def _transliterate(text):
    if not text or not _is_unicode_script(text):
        return text
    if TRANSLIT_OK:
        try:
            r = transliterate(text, sanscript.TELUGU, sanscript.HK)
            r = r.lower().replace("aa", "a").replace("ii", "i").replace("uu", "u")
            return re.sub(r"[^a-z\s]", "", r).strip()
        except Exception:
            pass
    return text


def _row_to_record(d):
    return ParsedRecord(
        id=d.get("id", 0),
        document_id=d.get("document_id"),
        sequence_no=d.get("sequence_no"),
        section_no=d.get("section_no"),
        group_no=d.get("group_no"),
        primary_name=d.get("primary_name"),
        primary_name_en=d.get("primary_name_en"),
        relation_type=d.get("relation_type"),
        relation_name=d.get("relation_name"),
        relation_name_en=d.get("relation_name_en"),
        reference_id=d.get("reference_id"),
        category=d.get("category"),
        value=d.get("value"),
        page_no=d.get("page_no"),
        pdf_source=d.get("pdf_source"),
        language=d.get("language", "en"),
        parse_confidence=d.get("parse_confidence"),
        parse_notes=d.get("parse_notes"),
    )


def _ensure_columns(conn):
    for col, typ in [("language", "TEXT"), ("parse_notes", "TEXT"), ("search_text", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE records ADD COLUMN {col} {typ}")
        except Exception:
            pass
    conn.commit()


def _rebuild_fts(conn):
    try:
        conn.execute("DELETE FROM records_fts")
        conn.execute("""
            INSERT INTO records_fts
                (rowid, primary_name, primary_name_en, relation_name, relation_name_en,
                 reference_id, group_no, document_id, pdf_source, search_text)
            SELECT id, primary_name, primary_name_en, relation_name, relation_name_en,
                   reference_id, group_no, document_id, pdf_source, search_text
            FROM records
        """)
        conn.commit()
    except Exception as e:
        print(f"FTS rebuild: {e}")


def _insert_records(conn, records, source_name):
    cur = conn.cursor()
    for rec in records:
        name_en = _transliterate(rec.get("primary_name") or "")
        rel_en = _transliterate(rec.get("relation_name") or "")
        search_text = " ".join(filter(None, [
            rec.get("primary_name", ""), rec.get("relation_name", ""),
            rec.get("reference_id", ""), rec.get("group_no", ""),
            rec.get("document_id", ""), source_name, name_en, rel_en
        ]))
        cur.execute("""
            INSERT INTO records
                (document_id, sequence_no, section_no, group_no,
                 primary_name, primary_name_en, relation_type,
                 relation_name, relation_name_en, reference_id,
                 category, value, page_no, pdf_source,
                 language, parse_confidence, parse_notes, search_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec.get("document_id"), rec.get("sequence_no"),
            rec.get("section_no"), rec.get("group_no"),
            rec.get("primary_name"), name_en,
            rec.get("relation_type"), rec.get("relation_name"), rel_en,
            rec.get("reference_id"), rec.get("category"),
            int(rec["value"]) if rec.get("value") else None,
            rec.get("page_no"), source_name,
            rec.get("language", "en"),
            rec.get("parse_confidence", "MEDIUM"),
            rec.get("parse_notes", ""),
            search_text,
        ))
    conn.commit()


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    db_ok = DB_PATH.exists()
    count = 0
    sources = []
    if db_ok:
        try:
            c = sqlite3.connect(str(DB_PATH))
            count = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            sources = [
                r[0] for r in c.execute(
                    "SELECT DISTINCT pdf_source FROM records ORDER BY pdf_source"
                ).fetchall()
            ]
            c.close()
        except Exception:
            db_ok = False
    return {
        "status": "running",
        "api": "Document Parser & Search API v2.0",
        "total_records": count,
        "loaded_documents": len(sources),
        "document_sources": sources,
        "session_only_uploads": True,
        "base_documents": list(BASE_DOCUMENTS),
    }


@app.get("/stats")
def stats():
    conn = get_conn()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    with_ref = cur.execute("SELECT COUNT(*) FROM records WHERE reference_id IS NOT NULL").fetchone()[0]
    cat_a = cur.execute("SELECT COUNT(*) FROM records WHERE category='A'").fetchone()[0]
    cat_b = cur.execute("SELECT COUNT(*) FROM records WHERE category='B'").fetchone()[0]
    sources = [
        {
            "file": r[0], "records": r[1], "document_id": r[2],
            "language": "English" if r[3] == "en" else "Unicode",
            "persistent": r[0] in BASE_DOCUMENTS,
        }
        for r in cur.execute(
            "SELECT pdf_source, COUNT(*), MAX(document_id), MAX(COALESCE(language,'en')) "
            "FROM records GROUP BY pdf_source ORDER BY pdf_source"
        ).fetchall()
    ]
    conn.close()
    return {
        "total_records": total,
        "with_reference_id": with_ref,
        "category_a": cat_a,
        "category_b": cat_b,
        "sources": sources,
    }


@app.get("/sources")
def sources():
    conn = get_conn()
    rows = conn.execute(
        "SELECT pdf_source, COUNT(*), MAX(document_id), MAX(COALESCE(language,'en')) "
        "FROM records GROUP BY pdf_source ORDER BY pdf_source"
    ).fetchall()
    conn.close()
    all_sources = [
        {"file": r[0], "records": r[1], "document_id": r[2],
         "language": "English" if r[3] == "en" else "Unicode"}
        for r in rows
    ]
    session_sources = [s for s in all_sources if s["file"] not in BASE_DOCUMENTS]
    return {
        "total_sources": len(rows),
        "sources": all_sources,
        "session_sources": session_sources,
    }


@app.get("/fuzzy", response_model=FuzzyResponse)
def fuzzy_search(
    name: str = Query(..., description="Name to search for (supports fuzzy matching)"),
    threshold: int = Query(70, ge=40, le=100, description="Minimum match score (40-100)"),
    pdf_source: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    value: Optional[int] = Query(None, ge=1, le=120),
    limit: int = Query(30, ge=1, le=100),
):
    """Fuzzy name search — finds similar names, tolerates spelling variations."""
    conn = get_conn()
    cond = []
    params = []
    if pdf_source:
        cond.append("pdf_source LIKE ?")
        params.append(f"%{pdf_source}%")
    if category and category.upper() in ("A", "B"):
        cond.append("category=?")
        params.append(category.upper())
    if value:
        cond.append("value BETWEEN ? AND ?")
        params.extend([max(1, value - 8), value + 8])
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(f"SELECT * FROM records {where} LIMIT 5000", params).fetchall()
    conn.close()

    if not rows:
        return FuzzyResponse(total_results=0, fuzzy_threshold=threshold, query=name, results=[])

    q = _normalize(name.strip())
    scored = []
    for rec in [dict(r) for r in rows]:
        best = 0
        best_field = ""
        for field, label in [
            ("primary_name", "name"),
            ("primary_name_en", "name (EN)"),
            ("relation_name", "relation"),
            ("relation_name_en", "relation (EN)"),
        ]:
            val = rec.get(field) or ""
            if not val:
                continue
            s = fuzz.WRatio(q, _normalize(val))
            if s > best:
                best = s
                best_field = label
        if best >= threshold:
            scored.append((rec, int(best), best_field))

    scored.sort(key=lambda x: -x[1])
    return FuzzyResponse(
        total_results=len(scored[:limit]),
        fuzzy_threshold=threshold,
        query=name,
        results=[
            FuzzyResult(record=_row_to_record(r), match_score=s, match_on=f)
            for r, s, f in scored[:limit]
        ],
    )


@app.get("/search", response_model=SearchResponse)
def search(
    name: Optional[str] = Query(None),
    relation: Optional[str] = Query(None),
    reference_id: Optional[str] = Query(None),
    group_no: Optional[str] = Query(None),
    section_no: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    value: Optional[int] = Query(None, ge=1, le=120),
    value_exact: bool = Query(False),
    pdf_source: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Structured search with pagination. Supports all indexed fields."""
    conn = get_conn()
    cur = conn.cursor()
    offset = (page - 1) * page_size
    conds = []
    params = []
    qused = {}

    if reference_id:
        rc = reference_id.strip().upper()
        conds.append("r.reference_id=?")
        params.append(rc)
        qused["reference_id"] = rc
    if group_no:
        h = group_no.strip()
        conds.append("r.group_no LIKE ?")
        params.append(f"{h}%")
        qused["group_no"] = h
    if section_no:
        conds.append("r.section_no=?")
        params.append(section_no.strip())
    if category:
        g = category.strip().upper()
        conds.append("r.category=?")
        params.append(g)
        qused["category"] = g
    if value:
        if value_exact:
            conds.append("r.value=?")
            params.append(value)
        else:
            conds.append("r.value BETWEEN ? AND ?")
            params.extend([max(1, value - 5), value + 5])
        qused["value"] = value
    if pdf_source:
        conds.append("r.pdf_source LIKE ?")
        params.append(f"%{pdf_source.strip()}%")

    if name:
        n = _normalize(name.strip())
        qused["name"] = name.strip()
        if _is_unicode_script(n):
            conds.append("r.id IN (SELECT rowid FROM records_fts WHERE records_fts MATCH ?)")
            params.append(n)
        else:
            for w in n.split():
                conds.append("(LOWER(r.primary_name) LIKE ? OR LOWER(COALESCE(r.primary_name_en,'')) LIKE ?)")
                params.extend([f"%{w.lower()}%"] * 2)

    if relation:
        rel = _normalize(relation.strip())
        qused["relation"] = relation.strip()
        if _is_unicode_script(rel):
            conds.append("r.id IN (SELECT rowid FROM records_fts WHERE records_fts MATCH ?)")
            params.append(rel)
        else:
            for w in rel.split():
                conds.append("(LOWER(r.relation_name) LIKE ? OR LOWER(COALESCE(r.relation_name_en,'')) LIKE ?)")
                params.extend([f"%{w.lower()}%"] * 2)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    try:
        total = cur.execute(f"SELECT COUNT(*) FROM records r {where}", params).fetchone()[0]
        rows = cur.execute(
            f"SELECT r.* FROM records r {where} ORDER BY r.sequence_no+0 LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Search error: {e}")

    conn.close()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return SearchResponse(
        total_results=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        search_mode="mixed",
        query_used=qused,
        results=[_row_to_record(dict(r)) for r in rows],
    )


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload a structured PDF for parsing.
    Processing is in-memory — no files are written to disk.
    Records are session-only and cleared on next server restart.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from parser import extract_from_bytes
        records = extract_from_bytes(data, file.filename)
    except Exception as e:
        raise HTTPException(500, f"Extraction failed: {str(e)}")

    if not records:
        raise HTTPException(400, "No records could be extracted. Check the PDF format.")

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_columns(conn)
        conn.execute("DELETE FROM records WHERE pdf_source=?", (file.filename,))
        conn.commit()
        _insert_records(conn, records, file.filename)
        _rebuild_fts(conn)
        total_db = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        sources = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT pdf_source FROM records ORDER BY pdf_source"
            ).fetchall()
        ]
        conn.close()

        lang_counts = {}
        for r in records:
            lang = r.get("language", "en")
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        main_lang = max(lang_counts, key=lang_counts.get)

        return {
            "status": "success",
            "filename": file.filename,
            "records_extracted": len(records),
            "language": "English" if main_lang == "en" else "Unicode",
            "document_id": records[0].get("document_id", "?") if records else "?",
            "total_in_db": total_db,
            "loaded_documents": sources,
            "session_only": True,
            "message": f"✓ {len(records)} records extracted and indexed.",
        }
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}")


@app.delete("/documents/{filename}")
def remove_document(filename: str):
    """Remove an uploaded document's records. Cannot remove base documents."""
    if filename in BASE_DOCUMENTS:
        raise HTTPException(400, f"Cannot remove base document: {filename}")
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM records WHERE pdf_source=?", (filename,)
    ).fetchone()[0]
    if count == 0:
        conn.close()
        raise HTTPException(404, f"Document '{filename}' not found.")
    conn.execute("DELETE FROM records WHERE pdf_source=?", (filename,))
    conn.commit()
    _rebuild_fts(conn)
    total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    return {
        "status": "removed",
        "filename": filename,
        "records_removed": count,
        "total_remaining": total,
    }


@app.get("/records/{reference_id}", response_model=ParsedRecord)
def by_reference_id(reference_id: str):
    """Look up a record by its unique reference ID."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE reference_id=?",
        (reference_id.strip().upper(),),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Reference ID not found: {reference_id.upper()}")
    return _row_to_record(dict(row))


@app.get("/group/{group_no}")
def by_group(
    group_no: str,
    page: int = 1,
    page_size: int = 50,
    pdf_source: Optional[str] = None,
):
    """Retrieve all records belonging to a specific group number."""
    conn = get_conn()
    offset = (page - 1) * page_size
    extra = ""
    count_params = [f"{group_no}%"]
    fetch_params = [f"{group_no}%"]
    if pdf_source:
        extra = " AND pdf_source LIKE ?"
        count_params.append(f"%{pdf_source}%")
        fetch_params.append(f"%{pdf_source}%")
    total = conn.execute(
        f"SELECT COUNT(*) FROM records WHERE group_no LIKE ?{extra}", count_params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM records WHERE group_no LIKE ?{extra} "
        f"ORDER BY group_no, sequence_no+0 LIMIT ? OFFSET ?",
        fetch_params + [page_size, offset],
    ).fetchall()
    conn.close()
    return {
        "group_no": group_no,
        "total_records": total,
        "page": page,
        "results": [dict(r) for r in rows],
    }
