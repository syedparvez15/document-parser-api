# document-parser-api

A FastAPI backend for uploading, parsing, and searching structured PDF documents. Supports multi-language PDFs including Unicode scripts, with full-text search and fuzzy name matching.

## Features

- **PDF Upload & Parsing** — Upload PDFs via API or drag-and-drop UI; records extracted in-memory (no files stored)
- **Multi-language Support** — Handles Latin and Unicode script documents; auto-detects language per page
- **Full-Text Search** — FTS5-powered search across all indexed fields
- **Fuzzy Name Matching** — Finds similar names using `rapidfuzz`, tolerates spelling errors
- **Session-based Uploads** — Uploaded documents are session-only; cleared on server restart
- **RESTful API** — Clean endpoints for search, stats, upload, and record lookup
- **Dashboard UI** — Single-file HTML/JS frontend for interactive search and upload

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn
- **Database**: SQLite with FTS5 full-text search
- **PDF Parsing**: pdfplumber
- **Fuzzy Search**: rapidfuzz
- **Frontend**: Vanilla HTML/CSS/JS (no build step)
- **Containers**: Docker, docker-compose

## Project Structure

```
document-parser-api/
├── backend/
│   ├── main.py          # FastAPI application and all endpoints
│   ├── parser.py        # PDF extraction and record parsing engine
│   └── ingest.py        # Database initialization and seeding
├── frontend/
│   └── index.html       # Dashboard UI
├── data/                # SQLite database (git-ignored)
├── tests/
│   └── test_parser.py   # Parser unit tests
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .gitignore
```

## Getting Started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialize the database

```bash
cd backend
python ingest.py
```

To seed from an existing JSON file:

```bash
python ingest.py --seed path/to/records.json
```

### 3. Start the API

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at `http://localhost:8000/docs`

### 4. Open the dashboard

Open `frontend/index.html` in your browser directly, or serve it:

```bash
cd frontend
python -m http.server 3000
```

Then visit `http://localhost:3000`

## Docker

```bash
docker-compose up --build
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API status and record counts |
| `GET` | `/stats` | Detailed statistics |
| `GET` | `/sources` | List loaded documents |
| `POST` | `/upload` | Upload and parse a PDF |
| `DELETE` | `/documents/{filename}` | Remove a document's records |
| `GET` | `/search` | Structured search with pagination |
| `GET` | `/fuzzy` | Fuzzy name matching |
| `GET` | `/records/{reference_id}` | Lookup by reference ID |
| `GET` | `/group/{group_no}` | All records in a group |

### Search Parameters

**`GET /search`**

| Param | Type | Description |
|---|---|---|
| `name` | string | Primary name (partial match, Unicode supported) |
| `relation` | string | Relation name |
| `reference_id` | string | Exact reference ID match |
| `group_no` | string | Group number prefix |
| `category` | string | Category filter (`A` or `B`) |
| `value` | int | Numeric value (±5 tolerance) |
| `pdf_source` | string | Filter by document filename |
| `page` | int | Page number (default: 1) |
| `page_size` | int | Results per page (default: 20, max: 100) |

**`GET /fuzzy`**

| Param | Type | Description |
|---|---|---|
| `name` | string | Name to match (required) |
| `threshold` | int | Min match score 40–100 (default: 70) |
| `pdf_source` | string | Filter by document |
| `limit` | int | Max results (default: 30) |

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## How the Parser Works

1. **PDF Loading** — Uses `pdfplumber` to extract text from each page
2. **Language Detection** — Counts Unicode characters per page to determine script
3. **Header Parsing** — Extracts document ID, section number, and section name from page headers
4. **Line Parsing** — Each data line is tokenized and fields are extracted by position and regex pattern
5. **Confidence Scoring** — Records are scored HIGH/MEDIUM/LOW based on how many expected fields were found
6. **FTS Indexing** — Extracted records are indexed in SQLite FTS5 with transliterated forms for cross-script search

## License

MIT
