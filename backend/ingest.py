"""
Database Initialization & Ingest Script
========================================
Sets up the SQLite database schema with FTS5 full-text search support.
Optionally ingests records from a JSON file for initial seeding.

Run once to initialize the database:
    python ingest.py

To seed from a JSON file:
    python ingest.py --seed path/to/records.json
"""

import json
import sqlite3
import re
import unicodedata
from pathlib import Path

try:
    from indic_transliteration import sanscript
    from indic_transliteration.sanscript import transliterate
    TRANSLIT_OK = True
    print("✓ indic-transliteration loaded")
except ImportError:
    TRANSLIT_OK = False
    print("⚠ indic-transliteration not available — using basic fallback")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "documents.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Transliteration ───────────────────────────────────────────────────────────
def to_latin(text: str) -> str:
    """Convert Unicode script text to Latin transliteration for search indexing."""
    if not text or not any('\u0C00' <= c <= '\u0C7F' for c in text):
        return text

    if TRANSLIT_OK:
        try:
            result = transliterate(text, sanscript.TELUGU, sanscript.HK)
            result = result.lower()
            result = result.replace("aa", "a").replace("ii", "i").replace("uu", "u")
            result = re.sub(r"[^a-z\s]", "", result).strip()
            return result
        except Exception:
            pass

    # Fallback: NFKD normalization
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").strip() or text


def build_search_text(record: dict) -> str:
    """Build combined FTS5 search text — includes both original and transliterated forms."""
    parts = []
    for field in ["primary_name", "relation_name", "reference_id", "group_no",
                  "document_id", "pdf_source"]:
        val = record.get(field) or ""
        if val:
            parts.append(val)
            # Add transliteration if Unicode
            if any('\u0C00' <= c <= '\u0C7F' for c in val):
                latin = to_latin(val)
                if latin and latin != val:
                    parts.append(latin)
    return " ".join(parts).strip()


# ── Schema ─────────────────────────────────────────────────────────────────────
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id       TEXT,
    sequence_no       TEXT,
    section_no        TEXT,
    group_no          TEXT,
    primary_name      TEXT,
    primary_name_en   TEXT,
    relation_type     TEXT,
    relation_name     TEXT,
    relation_name_en  TEXT,
    reference_id      TEXT,
    category          TEXT,
    value             INTEGER,
    page_no           INTEGER,
    pdf_source        TEXT,
    language          TEXT,
    parse_confidence  TEXT,
    parse_notes       TEXT,
    search_text       TEXT
);
"""

CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    primary_name,
    primary_name_en,
    relation_name,
    relation_name_en,
    reference_id,
    group_no,
    document_id,
    pdf_source,
    search_text,
    content='records',
    content_rowid='id'
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ref_id   ON records(reference_id);",
    "CREATE INDEX IF NOT EXISTS idx_value    ON records(value);",
    "CREATE INDEX IF NOT EXISTS idx_category ON records(category);",
    "CREATE INDEX IF NOT EXISTS idx_group    ON records(group_no);",
    "CREATE INDEX IF NOT EXISTS idx_source   ON records(pdf_source);",
    "CREATE INDEX IF NOT EXISTS idx_doc_id   ON records(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_conf     ON records(parse_confidence);",
]


# ── Init ───────────────────────────────────────────────────────────────────────
def init_db(db_path: Path = DB_PATH, fresh: bool = False):
    """Initialize the database schema. Set fresh=True to drop and recreate."""
    print(f"\n{'='*55}")
    print(f"  Document Parser — Database Init")
    print(f"{'='*55}")
    print(f"  Target: {db_path}")

    if fresh and db_path.exists():
        db_path.unlink()
        print("  ✓ Existing database removed (fresh build)")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cur = conn.cursor()

    cur.execute(CREATE_TABLE)
    cur.execute(CREATE_FTS)
    for idx in CREATE_INDEXES:
        cur.execute(idx)
    conn.commit()
    print("  ✓ Schema created (records table + FTS5 index + indexes)")
    conn.close()
    return db_path


def seed_from_json(json_path: Path, db_path: Path = DB_PATH):
    """Seed the database from a JSON file of record dicts."""
    print(f"\n  Loading records from: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        records = json.load(f)
    print(f"  ✓ {len(records)} records loaded")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    inserted = 0
    for rec in records:
        name_en = to_latin(rec.get("primary_name") or "")
        rel_en  = to_latin(rec.get("relation_name") or "")
        search  = build_search_text(rec)
        age_raw = rec.get("value")

        cur.execute("""
            INSERT INTO records (
                document_id, sequence_no, section_no, group_no,
                primary_name, primary_name_en,
                relation_type, relation_name, relation_name_en,
                reference_id, category, value,
                page_no, pdf_source, language,
                parse_confidence, parse_notes, search_text
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec.get("document_id"), rec.get("sequence_no"),
            rec.get("section_no"), rec.get("group_no"),
            rec.get("primary_name"), name_en,
            rec.get("relation_type"), rec.get("relation_name"), rel_en,
            rec.get("reference_id"), rec.get("category"),
            int(age_raw) if age_raw else None,
            rec.get("page_no"), rec.get("pdf_source"),
            rec.get("language", "en"),
            rec.get("parse_confidence", "MEDIUM"),
            rec.get("parse_notes", ""),
            search,
        ))
        inserted += 1

    conn.commit()
    print(f"  ✓ {inserted} records inserted")

    # Build FTS index
    cur.execute("""
        INSERT INTO records_fts (
            rowid, primary_name, primary_name_en,
            relation_name, relation_name_en,
            reference_id, group_no, document_id, pdf_source, search_text
        )
        SELECT id, primary_name, primary_name_en,
               relation_name, relation_name_en,
               reference_id, group_no, document_id, pdf_source, search_text
        FROM records
    """)
    conn.commit()
    print("  ✓ FTS5 index built")

    # Stats
    total  = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    with_r = conn.execute("SELECT COUNT(*) FROM records WHERE reference_id IS NOT NULL").fetchone()[0]
    srcs   = conn.execute("SELECT COUNT(DISTINCT pdf_source) FROM records").fetchone()[0]

    print(f"\n  {'='*45}")
    print(f"  DATABASE READY")
    print(f"  {'='*45}")
    print(f"  Total records   : {total}")
    print(f"  With Ref ID     : {with_r}")
    print(f"  PDF sources     : {srcs}")
    print(f"  DB size         : {db_path.stat().st_size // 1024} KB")
    print(f"  Location        : {db_path}")
    conn.close()


if __name__ == "__main__":
    import sys
    seed_file = None

    if "--seed" in sys.argv:
        idx = sys.argv.index("--seed")
        if idx + 1 < len(sys.argv):
            seed_file = Path(sys.argv[idx + 1])

    fresh = "--fresh" in sys.argv

    init_db(fresh=fresh)

    if seed_file:
        if not seed_file.exists():
            print(f"  ✗ Seed file not found: {seed_file}")
            sys.exit(1)
        seed_from_json(seed_file)

    print("\n  ✓ Done. Start the API with:")
    print("    uvicorn main:app --reload --host 0.0.0.0 --port 8000\n")
