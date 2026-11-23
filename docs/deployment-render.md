# Render deployment

The repository includes a Render Blueprint in `render.yaml`. It defines a public dashboard, a FastAPI web service, a Celery worker, private Postgres, and private Redis-compatible Key Value storage. The Postgres database enables PostGIS and pgvector through the existing Alembic migration. The dashboard reverse-proxies API requests so the browser uses one HTTPS origin.

## Before provisioning

The Blueprint uses minimum persistent plans for a small portfolio demo. Current published plan prices add up to approximately **US$37.25/month** before taxes or usage overages: three 0.5 CPU/512 MB web/worker services at $7 each, 256 MB Key Value at $10, Postgres at $6, and a 1 GB persistent upload disk at $0.25. Confirm current prices in Render before deploying.

The free plans are not used because the full application needs a persistent worker and files. Render's free Postgres expires after 30 days, free Key Value data can be lost on restart, and free services cannot attach persistent disks.

## Provision the Blueprint

1. Push the intended deployment commit to GitHub `main`.
2. Sign in to Render and connect the GitHub account that can access this repository.
3. Create a new Blueprint and select `SonuKumar-suman09/Multi-Source-Land-Data-Harmonization-Agent` on `main`.
4. Review the resources and monthly plan prices Render proposes before selecting **Apply**. Applying the Blueprint creates billable services.
5. Wait for the Postgres service, Redis-compatible service, migration pre-deploy command, API, worker, and dashboard to report healthy.
6. Open the dashboard URL. Create an account, then check `/health/ready` on the dashboard URL. It should return `ready` with database and Redis connected.

The Blueprint generates `JWT_SECRET_KEY` within Render. It does not put credentials in Git. Gemini, MinIO, OTLP, and Langfuse are not provisioned by this Blueprint; local deterministic mode works without those integrations. If Gemini is enabled, set its key on both the API and worker services.

## Data and recovery

The API service has a persistent disk mounted at `/app/data/uploads`. The worker reads processed rows from Postgres; it does not need to share that disk. Postgres and Key Value traffic remains on Render's private network. Back up MinIO objects separately if the storage backend is later changed to MinIO.

Render's dashboard provides database backups for paid Postgres plans and daily disk snapshots. Before using the site for anything beyond a synthetic portfolio demo, perform a restore drill and check actual service memory, upload limits, retention, and monthly usage.

## Implementation notes

- The API Dockerfile honors Render's `PORT` environment variable and continues to use port 8000 in local Compose.
- The dashboard Nginx template proxies `/api/` and `/health/` to the API's private host and port.
- Standard `postgres://` and `postgresql://` URLs supplied by managed database services are normalized to the installed psycopg 3 driver.
- The API migration runs in Render's paid pre-deploy step before the web service starts.
