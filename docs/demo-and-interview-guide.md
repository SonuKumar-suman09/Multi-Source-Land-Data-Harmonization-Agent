# Demo and interview guide

## Five-minute demo flow

1. Start the full application from the repository root:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

   Wait for `db`, `redis`, `api`, and `frontend` to become healthy. The migration service should exit with code zero.

2. Open `http://localhost:8080`, register a synthetic analyst account, and select **Upload datasets**.
3. Name the batch **Synthetic land-record demo** and select these three generated files from `data/sample/`:
   - `source_a.csv`
   - `source_b.xlsx`
   - `source_c.geojson`
4. Review the detected source columns, accept or change the proposed canonical fields, and select **Approve mappings & process**. Gemini suggestions are optional; only request them after consenting to send header names. Explain that the fixtures contain synthetic missing values, duplicates, area conflicts, and an invalid coordinate on purpose.
5. On **Overview**, point out real persisted dataset/record counts and review status; the application does not fill the charts with invented demo metrics.
6. On **Parcel map**, filter valid or invalid features, select a record, and inspect stored attributes. Invalid or missing geometry is not drawn as a valid parcel.
7. On **Reports & audit**, show the source file hashes/metadata, findings, recorded workflow events, and download both CSV and PDF. The CSV carries original source data and transformation history for traceability.
8. On **Knowledge base**, index a small synthetic Markdown rule, search for a matching phrase, and show the retrieved chunk and its source reference. QA can retrieve indexed guidance during a subsequent run.
9. Open **Agent activity** to inspect stored agent execution status and timing, then use **Data quality** to filter the job's persisted findings by severity.

With the checked-in fixtures, the uploaded batch contains 11 source rows across 3 files. The last verified run displayed 2 valid records, 2 invalid, 2 needing review, 5 conflict records, 5 duplicate pairs, and a 69.9 quality score. These are results from that specific synthetic fixture run, not performance measurements or government data.

## Interview questions and grounded answers

**1. What problem does the project solve?**  
It gives a reviewable pipeline for combining land-record tables and spatial files that use different field names, area units, date formats, and coordinate systems. It keeps source rows and transformations linked to each output.

**2. Why are the important transformations deterministic?**  
Area conversion, date interpretation, CRS projection, duplicate checks, and validation can affect consequential land attributes. Deterministic rules make those operations reproducible and allow uncertain inputs to be flagged rather than guessed.

**3. What makes the workflow agentic?**  
LangGraph stores a typed job state and coordinates ingestion verification, harmonization, quality checks, retries, and checkpoints. Celery/Redis run the graph asynchronously so an upload request does not have to wait for full processing.

**4. How do you use RAG?**  
Workspace rule documents are split into chunks and indexed in PostgreSQL with pgvector embeddings. QA retrieves relevant chunks and records their references. Local hashing embeddings support offline tests; Gemini embeddings are optional. Retrieved guidance does not silently rewrite source records.

**5. How do you handle schema mapping?**  
Known aliases are proposed deterministically and shown for a person to approve. Unmatched headers can be mapped manually or left unmapped. If the user consents and configures a Gemini key, the optional chat model receives header names only and returns advisory proposals; the person still chooses which fields are accepted. Cell values and owner names are not sent to Gemini.

**6. How does spatial normalization work?**  
The service reads the declared source CRS, transforms geometry to EPSG:4326 with PyProj/Shapely, checks bounds and validity, and stores valid geometry as a PostGIS geometry. The map API returns filtered GeoJSON from stored geometries.

**7. How are duplicates and conflicts different?**  
Matching normalized plot IDs create candidate pairs. When corresponding owner or area attributes disagree, the pair is marked as a conflict. The system preserves all source records and never automatically merges or selects an owner/area value.

**8. What does the quality score mean?**  
It is a deterministic review-priority score based on recorded checks. It is not a cadastral certification, a probability of correctness, or a benchmark of system speed.

**9. How do you keep one user's reports private?**  
The API derives allowed workspaces from the authenticated user's membership and returns 404 for jobs outside those workspaces. Integration tests cover JSON/CSV/PDF report isolation and CSV formula-prefix escaping.

**10. What would you improve before production?**  
Add stronger account administration/refresh-token lifecycle, backup/restore drills, and operational MinIO provisioning/credential rotation. Configure OTLP and Langfuse credentials only for a deployment that has approved telemetry destinations.

## Resume-ready description

**Multi-Source Land-Data Harmonization Agent** — Built a workspace-scoped land-data integration platform with FastAPI, PostgreSQL/PostGIS, pgvector, LangGraph, Celery/Redis, and React. Implemented multi-format ingestion with immutable source files and row-level lineage, deterministic schema/area/date/CRS normalization, duplicate/conflict detection, rule retrieval, quality checks, interactive GeoJSON mapping, execution monitoring, audit history, and CSV/PDF reports. Packaged the application with Docker Compose and verified the workflow with integration and worker end-to-end tests. All demonstration land records are synthetic.

## Two-minute project explanation

“I built a multi-source land-data harmonization platform because source files often describe the same parcel with different column names, units, coordinate reference systems, and data quality. The system accepts CSV, Excel, JSON, GeoJSON, and zipped Shapefiles. It preserves original files and raw rows, then applies deterministic schema mapping, area/date normalization, and CRS transformation into a common record model.

The processing workflow uses LangGraph for persisted stages and checkpoints, while Celery and Redis run longer jobs outside the API request. PostgreSQL stores the records and audit history, PostGIS stores spatial geometry, and pgvector supports workspace-scoped retrieval of validation guidance. Quality checks flag missing identifiers, invalid areas or geometry, duplicate plots, and conflicting ownership or area values. The system keeps conflicting source rows and asks for review instead of silently choosing a value.

The React dashboard lets an analyst upload a batch, review actual quality counts, filter parcels on a Leaflet map, and download a provenance-rich CSV or PDF report. The checked-in demo uses three synthetic files with 11 rows, including intentionally problematic records. I also tested the API, workspace report isolation, CSV export safety, and a real Celery worker run. The current implementation uses deterministic mapping; Gemini embeddings can be enabled for RAG, while LLM-generated mapping proposals and a mapping-approval UI are planned extensions.”

## Scope to state clearly in a presentation

- Gemini chat suggestions are optional and require explicit header-sharing consent; the deterministic and manual mapping flow works without a Gemini key.
- Original uploads can use local storage (default) or a configured MinIO endpoint; deployment and credential rotation still need operational setup.
- Knowledge documents can be indexed and searched through the authenticated API or the dashboard Knowledge base page.
- OpenTelemetry and Langfuse callbacks are implemented but optional; without endpoints and keys, they remain off. Langfuse only sees Gemini schema suggestion calls made after header-sharing consent.
- The project is a strong local demonstration, not a land-title authority or production deployment for legal decisions.

