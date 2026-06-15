# JobPipe

Self-hosted job-search pipeline. Add companies, define candidate profiles, run the digest — JobPipe polls each company's career board, scores postings with Claude, and surfaces matches above a configurable threshold. Nothing is auto-submitted.

Supports multiple candidate profiles (e.g. engineer + scientist) in a single instance.

## Structure

```
job-mover/
  jobpipe/        Python backend — pipeline CLI + FastAPI server
  jobpipe-ui/     React frontend — matches dashboard + company management
```

## Prerequisites

- Node.js 18+
- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

---

## Setup

### 1. Install dependencies

```bash
# From the repo root — installs concurrently for the dev launcher
npm install

# Backend
cd jobpipe && pip install -e . && cd ..

# Frontend
cd jobpipe-ui && npm install && cd ..
```

### 2. Set your API key

```bash
cp jobpipe/.env.example jobpipe/.env
```

Open `jobpipe/.env` and add your key:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Create candidate profiles

The repo ships example profiles that show every available field. Copy them and fill in real data:

```bash
cp jobpipe/config/candidates/engineer.yaml.example jobpipe/config/candidates/engineer.yaml
cp jobpipe/config/candidates/scientist.yaml.example jobpipe/config/candidates/scientist.yaml
```

The two fields that matter most for scoring quality:

- **`summary`** — a paragraph describing the candidate, passed to Claude when evaluating each posting. The more specific, the better the results.
- **`locations`** — list of cities/regions considered eligible. Postings outside this list are dropped before any LLM call.

If you only have one candidate, delete the unused profile and remove that candidate's rows from `companies.csv`.

### 4. Add target companies

Edit `jobpipe/config/companies.csv` to list the companies you want to track. The required columns are `name`, `candidate` (`engineer`, `scientist`, or `both`), and `careers_url`. Set `ats` to `?` and the pipeline will detect the ATS automatically on first run.

See [jobpipe/README.md](jobpipe/README.md) for the full column reference.

### 5. Seed the database

```bash
cd jobpipe
python -m jobpipe.pipeline seed
cd ..
```

Creates `jobpipe/data/jobpipe.db` (SQLite) from `companies.csv`. Re-run any time you edit the CSV.

### 6. Start

```bash
# From the repo root
npm run dev
```

Both servers start in one terminal with color-coded output:

- **API** → `http://localhost:8090`
- **UI** → `http://localhost:5173`

Press `Ctrl+C` to stop both.

---

## Using the UI

Open `http://localhost:5173`.

- **Matches tab** — click **Run Digest** to poll all boards, score postings, and display results. Filter by candidate or minimum score. Click any row to expand the Claude scoring reason.
- **Add Company tab** — add a company without editing the CSV directly. It is appended to `companies.csv` and seeded into the database immediately.

---

## CLI-only (no frontend)

```bash
cd jobpipe
python -m jobpipe.pipeline digest
```

See [jobpipe/README.md](jobpipe/README.md) for the full CLI and configuration reference.

---

## Accessing from another machine on the network

The Vite dev server already listens on all interfaces (`--host`). To make the UI call the API by LAN IP instead of localhost, create `jobpipe-ui/.env.local` (gitignored):

```
VITE_API_URL=http://<this-machine-ip>:8090
```

See `jobpipe-ui/.env.local.example` for the template.
