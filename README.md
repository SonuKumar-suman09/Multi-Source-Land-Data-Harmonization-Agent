# Multi-Source Land-Data Harmonization Agent

An incremental project for safely ingesting, harmonizing, validating, and reviewing synthetic land-record datasets with geospatial data, agent workflows, and provenance.

## Current milestone

Phase 1 architecture is documented in [`docs/architecture.md`](docs/architecture.md). Phase 2 has the project skeleton, local environment bootstrap, and synthetic CSV, Excel, and GeoJSON inputs. No API, database, AI workflow, or dashboard has been implemented yet.

All sample records are fictional and do not represent government records.

## Local bootstrap (PowerShell)

Run these commands from the repository root. Python 3.11 or newer is required.

```powershell
python --version
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python data/sample/create_fixtures.py
```

The expected fixture counts are 5 CSV rows, 3 Excel parcel rows, and 3 GeoJSON features. `backend/requirements.txt` currently contains only the Phase 2 Excel-fixture dependency; runtime dependencies will be added in their implementation phases.

Copy `.env.example` to `.env` when local services are introduced. Replace placeholder secrets before enabling authentication, and do not commit `.env` or user uploads.
