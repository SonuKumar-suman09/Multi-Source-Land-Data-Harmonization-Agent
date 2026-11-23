# Local database service

Phase 3 uses PostgreSQL 17, PostGIS 3.7, and pgvector 0.8.7 in a local Docker Compose service. The custom image starts from the PostGIS project image and builds the pinned pgvector extension against PostgreSQL 17. The database volume is named `postgres_data` and is retained across container restarts. The host port defaults to `5433` because Windows denied Docker access to `5432`; PostgreSQL itself still listens on `5432` inside the container.

The schema is managed by SQLAlchemy 2 and Alembic. It records tenant/workspace membership, sources and uploaded-file metadata, raw rows, canonical records, schema decisions, provenance, validation results, duplicate candidates, workflow/agent execution, audit events, and versioned rules. Parcel geometries use PostGIS SRID 4326. Rule embeddings use `vector(768)`; configure the embedding provider to return 768 dimensions before Phase 9 indexes data.

## Start and migrate

From the repository root in PowerShell:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build db
docker compose up -d db
docker compose ps
docker compose exec db psql -U land_app -d land_harmonizer -c "SELECT version(), PostGIS_Full_Version(), extversion FROM pg_extension WHERE extname = 'vector';"
```

Activate the virtual environment and run the initial migration:

```powershell
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
alembic -c backend/alembic.ini upgrade head
```

The project root is the expected working directory so Pydantic Settings can read `.env`. Verify the spatial column and version:

```powershell
docker compose exec db psql -U land_app -d land_harmonizer -c "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name = 'harmonized_land_records' AND column_name = 'geometry';"
docker compose exec db psql -U land_app -d land_harmonizer -c "SELECT version_num FROM alembic_version;"
```

The first Alembic revision is the local bootstrap baseline. It materializes the initial metadata once; after it is shared/applied, do not edit it. Subsequent schema changes must be new, explicit Alembic revisions.

To use a different free host port, set `POSTGRES_HOST_PORT` in `.env` and update `DATABASE_URL` to the same port. The container port remains `5432`.

To stop the service while keeping its data, run `docker compose down`. To intentionally discard the local database and all its rows, use `docker compose down -v`; that command is destructive and is not part of routine startup.
