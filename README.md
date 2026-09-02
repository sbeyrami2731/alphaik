# Alphaik MVP 0.2

First project-oriented web application milestone.

## Current workflow
Login → Projects → Upload P6 Excel → Automatic analysis → Versioned dashboard.

## Run
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open: http://127.0.0.1:8000

## Development login
Default development credentials:
- user: `admin`
- password: `Alphaik123!`

For any shared/deployed environment set environment variables before first run:
- `ALPHAIK_ADMIN_USER`
- `ALPHAIK_ADMIN_PASSWORD`

Delete `runtime/alphaik.db` if you intentionally want to recreate the development database with new initial credentials.

## What is implemented
- Login/session authentication
- Project creation/list
- Project-scoped uploads
- Automatic version numbering (U001, U002, ...)
- Persist uploaded files and latest analysis
- Existing TASK/TASKPRED parser
- Schedule analysis and findings
- Dashboard and activity table
- Version history

## Current analysis rules
- Critical: Total Float <= 0
- Near Critical: 0 < Total Float <= 10
- Open start/finish detection
- Negative lag (lead) detection
- Long lag detection
- Negative float detection
- Transparent provisional Schedule Health score

Baseline/progress/cost/risk inputs will extend the same project/version model later.
