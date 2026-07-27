# LeadCleaner Pro — Setup Instructions

## First Time Setup (do this once)

Open your terminal and run these commands one by one:

```bash
# 1. Go into the project folder
cd leadcleaner

# 2. Install required packages
pip3 install flask pandas openpyxl

# 3. Start the app
python3 app.py
```

Then open your browser and go to:
**http://localhost:5000**

---

## Every Time You Want to Use It

```bash
cd leadcleaner
python3 app.py
```

Open browser → **http://localhost:5000**

---

## How to Use

1. Upload your Excel list (.xlsx or .csv)
2. Set the Tax Year you want to target (default: 2022)
3. Click **Process My List**
4. Download your clean list

---

## What the tool does automatically

- ✅ Keeps only leads from the selected tax year
- ✅ Removes all LLCs, Corporations, Inc, Churches, Ranches, etc.
- ✅ Keeps TRUST / TRUSTEE names (family trusts are valid leads)
- ✅ Sorts by Total Due (highest debt first = most motivated sellers)
- ✅ Shows exactly how many leads were removed and why
- ✅ Imports every clean record into the CRM database
- ✅ Builds Leads and Research Queue workspaces
- ✅ Saves pipeline status, priority, research decisions, contacts and notes

## CRM database

Local development uses SQLite by default and creates its database at:

```text
data/leadcleaner.db
```

To use a different local location, set:

```bash
export CRM_DATABASE=/persistent/path/leadcleaner.db
```

Production uses PostgreSQL automatically when `DATABASE_URL` is present:

```bash
export DATABASE_URL=postgresql://user:password@host/database
```

The application accepts Render's internal PostgreSQL URL directly, creates the
schema idempotently on startup, and verifies connections before reusing them.
Keep the database in the same Render region as the web service and store the
internal URL as a secret environment variable named `DATABASE_URL`.

The health endpoint confirms which database engine is active without exposing
credentials:

```text
GET /api/health
{"database":"postgresql","status":"ok"}
```

Do not commit or paste the database URL into source code, issues, or chat.

---

## To stop the app

Press `Ctrl + C` in the terminal.
