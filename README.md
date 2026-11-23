# Multi-Source Land-Data Harmonization Agent

An incremental project for safely ingesting, harmonizing, validating, and reviewing synthetic land-record datasets with geospatial data, agent workflows, and provenance.

## Current milestone

Phase 1 architecture is documented in [`docs/architecture.md`](docs/architecture.md). Phase 2 has the project skeleton and synthetic CSV, Excel, and GeoJSON inputs. Phase 3 is running locally with PostgreSQL 17, PostGIS 3.7, pgvector 0.8.7, SQLAlchemy models, and the initial Alembic migration. The database is available at `127.0.0.1:5433` because Windows would not allow Docker to bind host port `5432`. Phase 4 provides JWT authentication, Argon2 password hashing, protected routes, health checks, and a default workspace for each account. Phase 5 adds authenticated CSV, Excel, JSON, GeoJSON, and zipped Shapefile ingestion with immutable local originals, hashes, metadata, and raw-row lineage. Phase 6 adds deterministic alias-based harmonization, area normalization to acres, CRS conversion to EPSG:4326, validation findings, duplicate/conflict candidates, and row-level transformation provenance.

All sample records are fictional and do not represent government records.

## Local bootstrap (PowerShell)

Run these commands from the repository root. Python 3.11 or newer is required.

```powershell
python --version
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt
python data/sample/create_fixtures.py
```

The expected fixture counts are 5 CSV rows, 3 Excel parcel rows, and 3 GeoJSON features. `backend/requirements.txt` contains the fixture dependency and the current database foundation dependencies.

Copy `.env.example` to `.env` if it does not already exist to configure local services. Set `JWT_SECRET_KEY` to a random value of at least 32 characters; do not commit `.env` or user uploads. Database startup, migration, and verification commands are in [`database/README.md`](database/README.md).

## Run the API

Start PostgreSQL using the commands in [`database/README.md`](database/README.md), then from the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. Available starter endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness check |
| `GET` | `/health/ready` | Database readiness check |
| `POST` | `/api/v1/auth/register` | Create an analyst account and personal workspace |
| `POST` | `/api/v1/auth/login` | Verify credentials and issue a bearer token |
| `GET` | `/api/v1/auth/me` | Read the signed-in user's profile |
| `POST` | `/api/v1/ingestion/uploads` | Ingest one or more files for a named source |
| `GET` | `/api/v1/ingestion/jobs/{job_id}` | Read the stored ingestion summary |
| `POST` | `/api/v1/harmonization/jobs/{job_id}/run` | Harmonize an ingested job and record findings and lineage |

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
