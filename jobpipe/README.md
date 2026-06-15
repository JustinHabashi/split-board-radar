# jobpipe

Python backend for JobPipe. Polls company career boards on demand, scores postings against candidate profiles using Claude, and writes a local HTML digest of matches above a configurable threshold.

> **New here?** Start with the [root README](../README.md) for full setup instructions. This file covers the backend in detail.

---

## How it works

One command runs four stages in sequence:

1. **Resolve** — for any company without a detected ATS, fetch its careers URL and identify which system it uses (Greenhouse, Lever, Ashby, or Workday). Result is cached in the database so it only runs once per company.
2. **Ingest** — poll each company's job board via its official API. New postings are inserted; existing ones are updated. Re-running never creates duplicates.
3. **Filter** — two stages: (a) a fast keyword + location check with no LLM call, then (b) a Claude relevance score (0–100) for each surviving posting per candidate. Only postings at or above the configured threshold appear in the digest.
4. **Digest** — write one HTML file per candidate to `data/digests/`, listing all matches sorted by score with company, title, location, reason, and a direct link to the posting.

---

## Quickstart

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

### 1. Install

```bash
cd jobpipe
pip install -e .
```

### 2. Configure API key

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Create candidate profiles

Copy the example profiles and edit them with real candidate data:

```bash
cp config/candidates/engineer.yaml.example config/candidates/engineer.yaml
cp config/candidates/scientist.yaml.example config/candidates/scientist.yaml
```

The YAML files are gitignored — never commit real profile data. The two most important fields:

- **`summary`** — passed to Claude as context when scoring each posting
- **`locations`** — city/region list; postings outside this list are dropped before any LLM call

If you only need one candidate, delete the unused profile and remove that candidate's rows from `companies.csv`.

### 4. Add companies

Edit `config/companies.csv`:

| Column | Description |
|---|---|
| `name` | Company display name (must be unique) |
| `candidate` | `engineer`, `scientist`, or `both` |
| `sector` | Free-text label used in the digest |
| `careers_url` | The company's careers page URL |
| `ats` | `greenhouse`, `lever`, `ashby`, `workday`, or `?` to auto-detect |
| `board_token` | ATS board identifier (e.g. `stripe` for Greenhouse). Use `?` to auto-detect. |
| `active` | `true` / `false` |

If `ats` or `board_token` is `?`, the resolver detects them automatically on the next run and caches the result.

### 5. Seed the database

```bash
python -m jobpipe.pipeline seed
```

Creates `data/jobpipe.db` (SQLite) from `companies.csv`. Re-run any time you add or edit companies.

### 6. Run

```bash
python -m jobpipe.pipeline digest
```

Output paths are printed when complete:

```
[engineer]  digest written -> data/digests/digest_engineer_2026-06-11.html
[scientist] digest written -> data/digests/digest_scientist_2026-06-11.html
```

Open either file in a browser to review matches.

---

## Command reference

### Primary command

```bash
python -m jobpipe.pipeline digest
```

Runs the full pipeline (resolve → ingest → filter → digest). Optional flags:

```bash
# Write digest files to a specific directory
python -m jobpipe.pipeline digest --output-dir ~/Desktop

# Only score and report for one candidate
python -m jobpipe.pipeline digest --candidate engineer
python -m jobpipe.pipeline digest --candidate scientist
```

Running with no subcommand also runs `digest`:

```bash
python -m jobpipe.pipeline
```

### Individual stages

Each stage can be run independently for debugging:

```bash
python -m jobpipe.pipeline resolve   # detect ATS for unresolved companies
python -m jobpipe.pipeline ingest    # poll boards, store new postings
python -m jobpipe.pipeline filter    # keyword pre-filter + LLM scoring
python -m jobpipe.pipeline seed      # (re-)load companies.csv into the database
```

---

## Configuration reference

### `config/settings.yaml`

```yaml
relevance_threshold: 70         # minimum Claude score (0–100) to appear in digest

rate_limits:
  requests_per_second: 2        # polite rate limiting across all ATS requests

http:
  timeout_seconds: 30
  user_agent: "JobPipe/1.0 (...)"

tailoring:
  model: claude-sonnet-4-6      # Claude model used for LLM scoring
  max_tokens: 4096
  temperature: 0.3

filtering:
  location_aliases:             # substrings matched against the posting's location field
    - Seattle
    - Bellevue
    - Redmond
  remote_patterns:              # if any appear in title or location, the location check passes
    - remote
    - work from home
    - wfh
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude scoring |
| `DATABASE_URL` | No | SQLAlchemy URL; default `sqlite:///./data/jobpipe.db` |
| `CONFIG_DIR` | No | Override path to the `config/` directory |

---

## Project layout

```
jobpipe/
  config/
    companies.csv                 target company list
    settings.yaml                 threshold, rate limits, model config
    candidates/
      engineer.yaml.example       template — copy to engineer.yaml and fill in
      scientist.yaml.example      template — copy to scientist.yaml and fill in
      engineer.yaml               gitignored — your personal candidate profile
      scientist.yaml              gitignored — your personal candidate profile
  jobpipe/
    models.py                     Pydantic + SQLAlchemy models
    db.py                         engine, session factory
    config.py                     config loading
    ingest.py                     ATS polling, posting upsert, DB seeding
    filter.py                     keyword filter + LLM relevance scoring
    notify.py                     HTML digest builder
    pipeline.py                   stage orchestration + CLI entry point
    server.py                     FastAPI server for the React frontend
    ats/
      base.py                     ATSAdapter ABC
      greenhouse.py
      lever.py
      ashby.py
      workday.py
      resolver.py                 careers URL → (ats, board_token)
    tailor.py                     (post-MVP) CV + cover letter generation
    scheduler.py                  (post-MVP) APScheduler daily entry point
  data/
    digests/                      HTML digest output files (gitignored)
    master_cv/                    source CVs per candidate — Markdown (gitignored)
    templates/
      digest_email.html.j2        Jinja2 template for the digest HTML
    drafts/                       (post-MVP) generated draft outputs (gitignored)
  tests/
  .env.example
  docker-compose.yml
  pyproject.toml
```

---

## Running the API server standalone

The FastAPI server exposes the pipeline over HTTP for the React frontend:

```bash
python -m uvicorn jobpipe.server:app --host 0.0.0.0 --port 8090
```

Or use the monorepo launcher from the repo root, which starts both servers together:

```bash
cd ..
npm run dev
```

---

## Docker

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY
docker-compose up
```

The container mounts `./data` and `./config` as volumes so the database and digest files persist on the host. By default it runs `python -m jobpipe.pipeline digest` and exits — wrap it in a cron job or run it manually.

---

## Running tests

```bash
pytest
```

All tests run without network calls or an Anthropic API key. ATS adapters are tested with `httpx.MockTransport`; LLM calls are mocked with `unittest.mock`.

---

## Post-MVP extensions

The codebase includes stubs for features not yet wired into the default command:

- **Tailoring** (`tailor.py`) — generate a tailored CV and cover letter for each match above threshold into `data/drafts/`.
- **Scheduling** (`scheduler.py`) — APScheduler entry point to run the digest automatically on a cron schedule.
- **Email delivery** (`notify.py`) — SMTP functions for sending the digest as an email instead of writing to disk.

---

## Non-goals

- No auto-apply, CAPTCHA solving, or credential entry
- No login-walled boards
- No scraping where an official API exists
