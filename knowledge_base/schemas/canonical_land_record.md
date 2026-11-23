# Canonical land-record schema, version 1

Project demonstration dictionary. The fields below are a software integration schema, not a jurisdictional land-record standard.

- `plot_id`: source parcel or plot identifier, retained as text to preserve leading zeroes and formatting.
- `owner_name`: supplied ownership or landholder text; missing values remain missing.
- `area_acres`: positive area normalized to acres only when the source unit is known.
- `recorded_at`: unambiguous date parsed as an ISO calendar date; ambiguous dates remain in raw provenance for review.
- `geometry`: valid Shapely/PostGIS geometry stored in EPSG:4326 when source CRS is known.
- `source_crs`: CRS declared for the source coordinates before transformation.
- `normalized_attributes`: source values and mapping details for traceability.
- `status` and `quality_score`: review state and deterministic project review-priority score.
