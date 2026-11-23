# Multi-Source Land-Data Harmonization Agent

An incremental project for safely ingesting, harmonizing, validating, and reviewing synthetic land-record datasets with geospatial data, agent workflows, and provenance.

## Current milestone

Phase 1 architecture is documented in [`docs/architecture.md`](docs/architecture.md). Phase 2 has the project skeleton and synthetic CSV, Excel, and GeoJSON inputs. Phase 3 is running locally with PostgreSQL 17, PostGIS 3.7, pgvector 0.8.7, SQLAlchemy models, and the initial Alembic migration. The database is available at `127.0.0.1:5433` because Windows would not allow Docker to bind host port `5432`. Phase 4 provides JWT authentication, Argon2 password hashing, protected routes, health checks, and a default workspace for each account. Phase 5 adds authenticated CSV, Excel, JSON, GeoJSON, and zipped Shapefile ingestion with immutable local originals, hashes, metadata, and raw-row lineage. Phase 6 adds deterministic alias-based harmonization, area normalization to acres, CRS conversion to EPSG:4326, validation findings, duplicate/conflict candidates, and row-level transformation provenance. Phase 7 adds an authenticated, repeat-safe quality assurance pass using Pandera canonical-schema checks, deterministic land rules, PostGIS geometry validation, and polygon-overlap detection. Phase 8 adds a LangGraph coordinator with ingestion verification, harmonization and QA nodes, retry policy for transient database failures, PostgreSQL checkpoints, and auditable workflow status. Phase 9 adds workspace-scoped rule-document indexing, Gemini embeddings, pgvector retrieval, and retrieved rule references in QA reports. Phase 10 runs the checkpointed workflow as a durable Celery task using Redis, with queued/running/completed/failed state, idempotent enqueue behavior, retry handling for transient database connectivity errors, and readiness checks for PostgreSQL and Redis. Phase 11 adds the React dashboard with JWT sign-in/registration, live workspace metrics, recent job activity, quality charts, and multi-file upload. Phase 12 adds a workspace-scoped GeoJSON API and React Leaflet map with status/search filtering, parcel selection, and record details.

Phase 13 adds workspace-scoped JSON, CSV, and PDF reports for each processing job, including source-file provenance, agent execution history, audit events, validation findings, record counts, duplicate counts, and quality score. The React **Reports & audit** page selects a recent job and downloads its CSV or PDF. Phase 14 adds integration and security tests for report downloads, spreadsheet formula escaping, and workspace isolation. Phase 15 packages the database, API, Celery worker, and React dashboard as a Docker Compose application with health checks, ordered migrations, persistent local data volumes, and a same-origin Nginx API proxy. Phase 16 adds architecture and ER diagrams, an API reference, a demo walkthrough, interview Q&A, and a resume-ready project description.

The design roadmap includes optional capabilities that are not implemented yet. The current limits are listed in [`docs/demo-and-interview-guide.md`](docs/demo-and-interview-guide.md); in particular, ambiguous mapping approval, Gemini chat-based mapping proposals, a React knowledge-base page, MinIO, Langfuse, and OpenTelemetry are future work. Do not describe these as completed features in a presentation.

Project presentation materials:

- [System architecture, agent workflow, database ER diagram, API reference](docs/architecture-and-data-model.md)
- [Demo script, interview questions, resume description, two-minute explanation](docs/demo-and-interview-guide.md)

All sample records are fictional and do not represent government records.

## Local bootstrap (PowerShell)

Run these commands from the repository root. Python 3.14 is the tested local version for the pinned dependencies.

```powershell
python --version
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt
python data/sample/create_fixtures.py
```

The expected fixture counts are 5 CSV rows, 3 Excel parcel rows, and 3 GeoJSON features. `backend/requirements.txt` contains the pinned runtime stack through the RAG phase, including Pandera, LangGraph/PostgreSQL checkpoints, and the Gemini LangChain integration.

Copy `.env.example` to `.env` if it does not already exist to configure local services. Set `JWT_SECRET_KEY` to a random value of at least 32 characters; do not commit `.env` or user uploads. Database startup, migration, and verification commands are in [`database/README.md`](database/README.md). Redis runs in the same Docker Compose project and is exposed only on localhost by default.

## Run the full application with Docker

Docker Desktop must be running. Copy `.env.example` to `.env` if needed, then replace `JWT_SECRET_KEY` with a unique random value before starting the stack. For a shared environment, replace the sample PostgreSQL password too. Docker maps the frontend to port `8080` and API docs to `8001` by default, avoiding the usual local development ports. From the repository root in PowerShell:

```powershell
docker compose up --build -d
docker compose ps
```

Wait until `db`, `redis`, `api`, and `frontend` show healthy/running and the one-shot `migrate` service exits successfully. Open `http://localhost:8080` for the dashboard or `http://localhost:8001/docs` for API docs. The frontend forwards API calls through Nginx to the API container, so the browser uses one origin. Celery workers process queued workflows in the background. Uploaded files, knowledge documents, and processed data remain in the local `data/` folders; database and Redis state use Docker volumes.

Useful commands:

```powershell
docker compose logs -f api worker
docker compose down
```

`docker compose down` stops and removes the containers while keeping database/Redis volumes and local files. Use `docker compose down -v` only when intentionally deleting the stored database and Redis data.

## Run the API

Start PostgreSQL and Redis using the commands in [`database/README.md`](database/README.md), then from the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. Available starter endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness check |
| `GET` | `/health/ready` | PostgreSQL and Redis readiness check |
| `POST` | `/api/v1/auth/register` | Create an analyst account and personal workspace |
| `POST` | `/api/v1/auth/login` | Verify credentials and issue a bearer token |
| `GET` | `/api/v1/auth/me` | Read the signed-in user's profile |
| `GET` | `/api/v1/dashboard/summary` | Read workspace-scoped persisted record and job metrics |
| `GET` | `/api/v1/map/parcels` | Retrieve valid workspace parcel geometries as filtered GeoJSON |
| `GET` | `/api/v1/reports/jobs/{job_id}` | Read report metrics, source provenance, findings, agent runs, and audit events |
| `GET` | `/api/v1/reports/jobs/{job_id}/csv` | Download harmonized records with original row data and transformation lineage |
| `GET` | `/api/v1/reports/jobs/{job_id}/pdf` | Download a processing summary with quality and audit details |
| `POST` | `/api/v1/ingestion/uploads` | Ingest one or more files for a named source |
| `GET` | `/api/v1/ingestion/jobs/{job_id}` | Read the stored ingestion summary |
| `POST` | `/api/v1/harmonization/jobs/{job_id}/run` | Harmonize an ingested job and record findings and lineage |
| `POST` | `/api/v1/quality/jobs/{job_id}/run` | Run canonical-field, land-rule, and PostGIS quality checks |
| `POST` | `/api/v1/workflows/jobs/{job_id}/run` | Run the checkpointed ingestion → harmonization → QA workflow |
| `POST` | `/api/v1/workflows/jobs/{job_id}/enqueue` | Queue the checkpointed workflow for a Celery worker (202 response) |
| `GET` | `/api/v1/workflows/jobs/{job_id}` | Read workflow stage and persisted state summary |
| `POST` | `/api/v1/knowledge/documents` | Index a workspace-scoped Markdown, TXT, or JSON rules document |
| `GET` | `/api/v1/knowledge/documents` | List indexed documents in the signed-in workspace |
| `POST` | `/api/v1/knowledge/search` | Retrieve relevant rule chunks using pgvector similarity |

Example registration request body:

```json
{
  "email": "analyst@example.com",
  "password": "a-long-unique-password"
}
```

Generate a local JWT secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste it into `.env`. Run the test suite from the repository root with `python -m pytest` (the API integration tests use the configured PostgreSQL service).

### Upload synthetic datasets

Register or log in through Swagger to get an `access_token`. Use the **Authorize** button and enter `Bearer <access_token>`. Then call `POST /api/v1/ingestion/uploads` with a `source_name` and one or more files. The included CSV has 5 rows, the Excel workbook has 3 rows, and the GeoJSON has 3 features; uploading all three in one request should report **11 records**. Each upload has a 100 MB combined limit by default. Exact duplicate file content in the same workspace is rejected with `409`.

PowerShell example after putting the token into `$jwtToken`:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/ingestion/uploads" `
  -H "Authorization: Bearer $jwtToken" `
  -F "source_name=Synthetic demonstration batch" `
  -F "files=@data/sample/source_a.csv" `
  -F "files=@data/sample/source_b.xlsx" `
  -F "files=@data/sample/source_c.geojson"
```

The response includes a job ID, file IDs, detected formats, SHA-256 hashes, row counts, columns, and source metadata. The service preserves the uploaded bytes under `data/uploads/`, stores parsed rows in `raw_land_records`, and returns a job status of `mapping` for the next workflow phase. A zipped Shapefile must contain exactly one `.shp` plus matching `.shx` and `.dbf` files; a `.prj` is needed to identify its CRS automatically. The parser uses GeoPandas with the GDAL-backed Pyogrio engine for Shapefile reads.

### Harmonize an ingested job

After upload, call `POST /api/v1/harmonization/jobs/{job_id}/run` with the same bearer token. Exact normalized aliases are mapped deterministically; duplicate aliases for a canonical field are marked for review. Area values are converted only when their source column or declared metadata identifies the unit. Geometry is transformed with PyProj into EPSG:4326; invalid or out-of-bounds geometry is flagged and omitted from the canonical geometry column. Ambiguous dates and missing or invalid area values are retained in the raw row and generate findings for review. Duplicate plot IDs are recorded as candidate pairs, and disagreements in owner or area mark both records as conflicts. Every output record links back to its raw row and mapping/transformation history. The endpoint returns record counts, duplicate pairs, findings, and a summary quality score; running it a second time returns `409` to avoid duplicate output rows.

Next, call `POST /api/v1/quality/jobs/{job_id}/run`. Pandera checks the canonical field schema; Python rules flag missing identifiers, non-positive areas, and missing owners; PostGIS checks stored geometry validity, emptiness, SRID, and polygon overlaps above one square metre. Findings are persisted with severity and review guidance. Quality execution is recorded and repeat calls return the stored report without duplicating findings. The score is a deterministic review-priority score, not an externally certified land-data rating.

To run the full orchestrated sequence on a newly uploaded job in the background, first start the Celery worker in a second VS Code terminal from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
python -m celery -A app.tasks.celery_app:celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` is a simple local development worker mode. Keep that terminal open. In Swagger, call `POST /api/v1/workflows/jobs/{job_id}/enqueue`; it returns HTTP `202` and a task ID after recording the queued state and publishing the task. `GET /api/v1/workflows/jobs/{job_id}` reports progress and the final result. Repeated enqueue requests while the task is queued or running return the existing task ID instead of creating duplicate work. The synchronous `/run` endpoint remains useful for debugging. Run `docker compose up -d db redis` to start the database and broker, and check `GET /health/ready` for both service connections. The LangGraph graph does not call Gemini yet, so no paid LLM key is needed for this workflow.

The regular suite checks task configuration without requiring a worker. For a real queue-to-worker integration check, start the worker as above, then in another terminal run:

```powershell
$env:RUN_CELERY_E2E = "1"
python -m pytest backend/tests/test_celery_workflow_e2e.py -q
```

The optional check creates a synthetic account and upload, enqueues the job, waits for completion, verifies the persisted agent execution, and removes its test data. It is skipped in the standard suite unless `RUN_CELERY_E2E=1` is set.

### Run the React dashboard

Start the API and the Celery worker as described above, then open another VS Code terminal:

```powershell
node --version
Set-Location frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). Register an account or sign in, then upload a synthetic source batch. The overview reads actual workspace-scoped counts from `/api/v1/dashboard/summary`; it does not fill empty states with sample metrics. Uploaded files are sent to the FastAPI ingestion endpoint and then queued for the Celery workflow. `VITE_API_URL` can override the API base URL when it is not `http://127.0.0.1:8000`.

The **Parcel map** view requests valid stored geometries from `/api/v1/map/parcels` as GeoJSON, then draws them with Leaflet. Search by plot or landholder, filter by harmonized record status, select a parcel to inspect its stored attributes, and zoom to it from the parcel list. The API can also accept a complete WGS84 bounding box with `min_lon`, `min_lat`, `max_lon`, and `max_lat`; partial or inverted bounds are rejected. OpenStreetMap tiles include the required attribution; review the [Leaflet map and tile guidance](https://leafletjs.com/examples/quick-start/) before changing tile providers or using this demo in production.

The **Reports & audit** page is available from the dashboard navigation. Select a recent processing job to review source files, record-quality totals, validation findings, recorded agent executions, and the job's audit timeline. Download CSV for row-level data and lineage or PDF for a compact processing summary. Both downloads require sign-in and the job must belong to a workspace where the signed-in user is a member. CSV text fields are escaped to reduce spreadsheet formula injection risk.

### Index and retrieve land-data rules

The **Knowledge base** page accepts UTF-8 `.md`, `.txt`, and `.json` documents up to 1 MB, lists indexed sources, and searches retrieved rule chunks. The API stores each original under the ignored `data/knowledge/` directory, hashes it, splits it into overlapping text chunks, and stores 768-dimensional embeddings with source references in PostgreSQL/pgvector. Listing, upload, and search are scoped to the authenticated user's workspace. QA retrieves relevant indexed policy chunks and includes their titles and source references in its report; rule text is surfaced for review while record corrections remain deterministic and auditable.

The default `RAG_EMBEDDING_PROVIDER=local` mode works offline without a paid API key using deterministic lexical feature hashing. To use Gemini, add these values to your untracked `.env` file and restart the API:

```env
RAG_EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

Keep the key out of frontend code and Git. Upload the project-authored sample policies at [`knowledge_base/rules/project_data_quality_policy.md`](knowledge_base/rules/project_data_quality_policy.md) and [`knowledge_base/schemas/canonical_land_record.md`](knowledge_base/schemas/canonical_land_record.md) with `POST /api/v1/knowledge/documents`. They document project behavior and are explicitly not government or legal standards.
