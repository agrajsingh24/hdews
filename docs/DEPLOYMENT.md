# Deploying HDEWS

HDEWS is a **research prototype with simulated telemetry and uncalibrated thresholds**. A hosted instance is a
demonstration. Do not present it as an official or validated public warning service.

## 1. Architecture

| Component | Where it runs | Notes |
|---|---|---|
| Frontend (compiled TypeScript, `frontend/dist`) | Served by the backend process, same origin | No separate static host and no CORS needed. GitHub Pages is **not** suitable: it cannot run the API. |
| Backend API + background loop | One Docker container (`Dockerfile`), **one instance** | Starlette/uvicorn, 1 worker. The loop continues simulated telemetry and re-assesses sites, so the service must stay running. |
| Database | SQLite file on a **persistent disk** mounted at `/data` | Alerts, audit log and assessments live here. Without persistent storage they are lost on every restart. The PostgreSQL runtime path is untested; do not use it in a deployment yet. |
| ML | Not deployed | There is no ML inference at runtime: no model has been validated. The offline harness (`ml/`, scikit-learn/pandas) is excluded from the image. No GPU is needed. |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml`) | Tests (Linux and Windows), frontend build check, Docker smoke test, browser E2E; then the Render deploy hook on `main`. |

**Recommended host: Render**, one Docker web service on a **paid instance** with a 1 GB disk (`render.yaml`). Facts this
choice relies on, from Render's documentation:
* Free web services spin down after 15 minutes without inbound traffic and have an ephemeral filesystem with no
  persistent-disk support. The SQLite database would be lost on every restart, deploy or spin-down, and the background
  loop would stop. **The free plan is therefore unsuitable** beyond a throw-away look.
* A persistent disk requires a paid service, limits it to one instance (which HDEWS needs anyway), and disables
  zero-downtime deploys (a few seconds of downtime per deploy). Render snapshots disks daily.
* Render sets the port in `PORT` (default 10000); `scripts/start.py` binds to it.
* A deploy hook is a secret URL that triggers a deploy with a GET request.

Check Render's current pricing for the instance and disk before creating the service.

**Alternatives**
* **Railway or Fly.io:** same Docker image, with a volume mounted at `/data`. Untested here; follow their volume docs and set the
  same environment variables.
* **Your own VPS:** `docker compose up -d --build` behind a TLS reverse proxy (e.g. Caddy or nginx), with the
  `hdews-data` volume backed up. Set `CLIENT_IP_SOURCE=x-forwarded-for-last` if the proxy appends the client address.

## 2. One-time setup (needs your accounts)

1. **Create a GitHub repository.** Private is recommended. Push this code with the default branch named `main`:
   ```bash
   git remote add origin https://github.com/<you>/hdews.git
   git push -u origin master:main                  # the local branch is 'master'; the remote default becomes 'main'
   git push -u origin audit-and-deploy             # then open a pull request: CI runs on it
   ```
2. **Let CI pass on the pull request**, then merge it into `main`.
3. **Create the Render service from the Blueprint.** In Render: *New → Blueprint*, select the repository. Render reads
   `render.yaml` and asks for the `sync: false` secrets:
   * `HDEWS_DEMO_PASSWORD`: at least 12 characters, not `hdews-demo` / `change-me-demo-password`. This is the password of
     the four demo accounts; share it only with people who should sign in.
   * `FIELD_GATEWAY_INGEST_KEY`: optional; at least 16 random characters if you want the gateway ingestion API. It must be set
     **before the first deploy**, because it is stored when the demo data is first loaded.
4. **Connect CI to Render.** In the Render service *Settings → Deploy Hook*, copy the hook URL. In GitHub *Settings →
   Secrets and variables → Actions*, add it as the **secret** `RENDER_DEPLOY_HOOK_URL`. Add the service's public URL
   (e.g. `https://hdews.onrender.com`) as the **variable** `HDEWS_PUBLIC_URL`. Create a GitHub environment named `production`
   if you want a manual approval before each deploy.
5. **First deploy:** use *Manual Deploy* in Render, or push to `main`.

## 3. After the first deploy: verify (about 10 minutes)

1. `https://<your-service>/api/health` returns `"status":"ok"` and `"environment":"demo"`.
2. Open the site, sign in as `reviewer` with your password, and walk through the README demo (simulator → alert → acknowledge → resolve → audit verify).
3. Check that secrets did not reach the logs: the Render log should show `HDEWS demo data seeded.` and *no* password or key.
4. **Check the rate-limit client address.** The Blueprint sets `CLIENT_IP_SOURCE=x-forwarded-for-first`, because Render
   staff state the first `X-Forwarded-For` entry is the real client. This is not in Render's formal docs, so verify it: make
   11 wrong login attempts from one network. The 11th must be refused (HTTP 429), while a sign-in from a different network
   (e.g. a phone on mobile data) still works.
5. Redeploy once (*Manual Deploy*) and confirm that alerts and the audit log are still there and `/api/audit-log/verify` is valid.

## 4. Everyday operation

* **Change the app:** open a pull request; CI runs. Merge to `main`: CI runs again, then calls the deploy hook. Render builds
  the `Dockerfile`, runs migrations on start-up (`scripts/start.py`), and keeps the existing database (it is never reseeded).
* **Roll back:** in Render, redeploy a previous successful deploy, or revert the commit on `main`. Migrations only add
  columns and tables, so the previous version can still read the database.
* **Accounts:** open a shell on the service (*Shell* tab) and run `python scripts/manage_users.py --help`. You can create
  personal accounts, change passwords (sessions are revoked) or disable the shared demo accounts. Every change is audited.
* **Rotate the demo password:** `HDEWS_NEW_PASSWORD=... python scripts/manage_users.py set-password <user>` for each account
  (changing `HDEWS_DEMO_PASSWORD` later has no effect on an existing database).
* **Reset the demo data:** stop relying on the current data first, then in the shell
  `rm /data/hdews.db*` and restart the service. It reseeds an empty database. This deletes all alerts and the audit log.
* **Backups:** Render snapshots the disk daily. For an extra copy, run `sqlite3 /data/hdews.db ".backup /data/backup.db"` if
  `sqlite3` is available, or use Python's `sqlite3` backup API, then download the copy.
* **Gateway scope:** `python scripts/set_ingest_scope.py FIELD-GATEWAY-01 [SITE ...]`.

## 5. Environment variables

See `.env.example` for every setting. For the hosted demo the important ones are `HDEWS_ENV=demo`,
`DATABASE_URL=sqlite:////data/hdews.db`, `HDEWS_DEMO_PASSWORD` (secret), `FIELD_GATEWAY_INGEST_KEY` (secret, optional),
`CLIENT_IP_SOURCE` and, optionally, `LLM_PROVIDER=anthropic` + `LLM_API_KEY` (secret) for LLM-worded explanations.

## 6. What has and has not been verified

Verified locally:
* Test suites, lint and the frontend build.
* The container's start-up path: entrypoint privilege drop, start-up refusals, seeding without printing secrets.
* Persistence across restarts, and the CI Docker-job script (with a stand-in for the `docker` CLI).

**Not verified, because the build environment had no access to Docker Hub, PyPI, npm, GitHub credentials or Render:**
* an actual `docker build`;
* installation of the pinned packages from public PyPI/npm;
* the GitHub Actions run itself, including the Windows job;
* any live deployment.

The first CI run and the post-deploy checks above close these gaps.
