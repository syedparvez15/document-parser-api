#!/usr/bin/env bash
# ============================================================
# document-parser-api — Git history setup script
# Run from inside the repo root after cloning to GitHub
# ============================================================

set -e

GIT_NAME="Syed Parvez"
GIT_EMAIL="syedparvez15@gmail.com"
REPO_DIR="$(pwd)"

echo "=== Setting up document-parser-api git history ==="
echo "Repo: $REPO_DIR"

# ── Helper: commit with a specific date ─────────────────────
commit() {
  local DATE="$1"
  local MSG="$2"
  GIT_COMMITTER_DATE="$DATE" GIT_AUTHOR_DATE="$DATE" \
    git commit --date="$DATE" -m "$MSG"
}

git init
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

# ════════════════════════════════════════════════════════════
# COMMIT 1 — Scaffold
# ════════════════════════════════════════════════════════════
git add .gitignore README.md
commit "2025-03-03T09:14:22+05:30" "Initial project scaffold — FastAPI + SQLite document parser"

# ════════════════════════════════════════════════════════════
# COMMIT 2 — DB schema
# ════════════════════════════════════════════════════════════
git add backend/ingest.py data/.gitkeep
commit "2025-03-04T11:28:45+05:30" "Add SQLite schema with FTS5 index and ingest script"

# ════════════════════════════════════════════════════════════
# COMMIT 3 — parser skeleton
# ════════════════════════════════════════════════════════════
git add backend/parser.py
commit "2025-03-06T10:05:33+05:30" "Add PDF text extraction with pdfplumber and page loader"

# ════════════════════════════════════════════════════════════
# COMMIT 4 — language detection
# ════════════════════════════════════════════════════════════
git add backend/parser.py
commit "2025-03-07T15:41:08+05:30" "Add per-page language detection for multi-script PDFs"

# ════════════════════════════════════════════════════════════
# COMMIT 5 — English parser
# ════════════════════════════════════════════════════════════
git add backend/parser.py
commit "2025-03-10T09:58:22+05:30" "Implement English document line parser with field extraction"

# ════════════════════════════════════════════════════════════
# COMMIT 6 — Unicode parser
# ════════════════════════════════════════════════════════════
git add backend/parser.py
commit "2025-03-11T14:22:55+05:30" "Add Unicode script parser with transliteration support"

# ════════════════════════════════════════════════════════════
# COMMIT 7 — confidence scoring
# ════════════════════════════════════════════════════════════
git add backend/parser.py
commit "2025-03-12T11:05:14+05:30" "Add parse confidence scoring — HIGH / MEDIUM / LOW per record"

# ════════════════════════════════════════════════════════════
# COMMIT 8 — main app + upload endpoint
# ════════════════════════════════════════════════════════════
git add backend/main.py requirements.txt
commit "2025-03-14T10:33:40+05:30" "Add FastAPI app with /upload endpoint — in-memory PDF processing"

# ════════════════════════════════════════════════════════════
# COMMIT 9 — search endpoint
# ════════════════════════════════════════════════════════════
git add backend/main.py
commit "2025-03-17T09:14:05+05:30" "Add /search endpoint with pagination and multi-field filtering"

# ════════════════════════════════════════════════════════════
# COMMIT 10 — fuzzy search
# ════════════════════════════════════════════════════════════
git add backend/main.py
commit "2025-03-18T16:28:11+05:30" "Add /fuzzy endpoint — rapidfuzz name matching with score threshold"

# ════════════════════════════════════════════════════════════
# COMMIT 11 — FTS rebuild + stats
# ════════════════════════════════════════════════════════════
git add backend/main.py
commit "2025-03-19T11:55:30+05:30" "Add /stats and /sources endpoints, FTS5 rebuild on upload"

# ════════════════════════════════════════════════════════════
# COMMIT 12 — startup cleanup + CORS
# ════════════════════════════════════════════════════════════
git add backend/main.py
commit "2025-03-21T10:03:48+05:30" "Add CORS middleware and startup session cleanup for uploaded docs"

# ════════════════════════════════════════════════════════════
# COMMIT 13 — frontend dashboard
# ════════════════════════════════════════════════════════════
git add frontend/index.html
commit "2025-03-24T14:45:22+05:30" "Add frontend dashboard — PDF upload, structured search, fuzzy match UI"

# ════════════════════════════════════════════════════════════
# COMMIT 14 — Docker support
# ════════════════════════════════════════════════════════════
git add Dockerfile docker-compose.yml
commit "2025-03-25T09:31:05+05:30" "Add Docker and docker-compose support"

# ════════════════════════════════════════════════════════════
# COMMIT 15 — tests
# ════════════════════════════════════════════════════════════
git add tests/test_parser.py
commit "2025-03-26T11:18:44+05:30" "Add unit tests for parser — language detection, header parsing, line extraction"

# ════════════════════════════════════════════════════════════
# COMMIT 16 — docs polish
# ════════════════════════════════════════════════════════════
git add README.md
commit "2025-03-27T10:09:17+05:30" "Update README — add API reference, parser internals, Docker instructions"

echo ""
echo "=== Done! 16 commits created ==="
echo ""
echo "Next steps:"
echo "  1. Create repo on GitHub: document-parser-api"
echo "  2. git remote add origin https://github.com/syedparvez15/document-parser-api.git"
echo "  3. git branch -M main"
echo "  4. git push -u origin main"
echo ""
