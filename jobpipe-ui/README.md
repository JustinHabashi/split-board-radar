# jobpipe-ui

React frontend for JobPipe. Provides two views:

- **Matches** — trigger a digest run and browse scored job matches above the relevance threshold. Filterable by candidate and minimum score. Click any row to expand the Claude scoring reason.
- **Add Company** — form to append a new company to `companies.csv` and seed it into the database immediately, without editing the file manually.

> **New here?** Start with the [root README](../README.md) for full setup instructions. This file covers the frontend in detail.

---

## Running

The preferred way is the monorepo launcher from the repo root, which starts the API and UI together:

```bash
# from job-mover/
npm run dev
```

To run the frontend on its own (the API must already be running):

```bash
npm install
npm run dev     # http://localhost:5173
```

Start the API server separately:

```bash
# from job-mover/jobpipe/
python -m uvicorn jobpipe.server:app --host 0.0.0.0 --port 8090
```

---

## Network access

The dev server is configured with `--host` so it is accessible from other machines on the network. By default the UI calls the API at `http://localhost:8090`. To point it at a different host, create `jobpipe-ui/.env.local` (gitignored):

```
VITE_API_URL=http://<server-ip>:8090
```

See `.env.local.example` in this directory for the template.

---

## Build for production

```bash
npm run build   # output in dist/
```

---

## Project structure

```
src/
  api.ts                    typed fetch wrappers for all backend endpoints
  App.tsx                   tab shell and top-level layout
  components/
    MatchesView.tsx          digest table, Run Digest button, status polling
    AddCompany.tsx           company form (name, candidate, ATS, URL)
  index.css                 minimal global reset
```
