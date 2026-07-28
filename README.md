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
- ✅ Separates prequalified, review, and excluded records with a reason on every row
- ✅ Identifies Tulsa business personal property from the county legal description
- ✅ Removes LLCs, corporations, cannabis businesses, government, and nonprofits
- ✅ Keeps TRUST / TRUSTEE names (family trusts are valid leads)
- ✅ Sorts by Total Due (highest debt first = most motivated sellers)
- ✅ Produces preliminary scores without treating absentee or estate text as proof of death
- ✅ Separates deceased evidence, absentee opportunities, and data-quality review
- ✅ Shows exactly how many records were excluded and why
- ✅ Holds qualification runs for review before any CRM import
- ✅ Builds Leads and Research Queue workspaces
- ✅ Saves pipeline status, priority, research decisions, contacts and notes

## Qualification workbook

Every processing run creates five auditable sheets:

- `Prequalified - Verify`
- `Needs Review`
- `Deceased Research`
- `Absentee Opportunities`
- `Excluded Records`

The current Tulsa source does not include a row-level tax-year column. The
selected year is therefore recorded as import provenance instead of being
misrepresented as a row-level validation.

## Tulsa County Assessor verification

After qualification, the dashboard can verify current ownership in controlled
batches of 25. Each official response is cached in PostgreSQL/SQLite so a
repeated run does not create another county request. The verified export adds:

- current Assessor owner
- official account type
- vacant indicator
- owner-match decision and reason
- source URL and checked timestamp

Request failures, missing pages, and parser failures remain `Not verified`.
They are never converted into exclusions. Commercial or changed-owner records
go to review; only matching Residential/Agricultural records become verified
candidates.

## Death and probate evidence ledger

Research evidence is stored separately from county-data signals. Every item
records its type, outcome, confidence, identity match, source, URL, case number,
subject, event date, notes, and timestamp.

`Confirmed deceased` requires an exact identity match plus confirmed official
probate, death-index, or death-certificate evidence. Obituaries, estate text,
skip-trace mismatches, and probable identity matches can prioritize research,
but cannot confirm death. Confirmed living evidence marks a false positive;
conflicting confirmed evidence remains unresolved.

OSCN pages are saved as evidence links because OSCN itself warns that online
docket information is not an official record. OK2Explore is useful but only
indexes Oklahoma deaths at least five years old, so a missing result is never
treated as evidence that a person is living.

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
