# Project data-quality policy, version 1

This is a project-authored synthetic policy for software demonstrations. It is not a government rule, legal standard, or substitute for jurisdiction-specific review.

## Parcel identifiers

Each harmonized land record should have a non-empty parcel or plot identifier. If multiple source columns could map to the identifier, keep the mapping in review until a human confirms the correct column.

## Area values

Area must be a finite positive number. Convert to acres only when the unit is established by the column name or source metadata. Unknown units and non-positive values require review; never replace the source value silently.

## Ownership

Keep the owner name exactly as supplied after whitespace normalization. Missing or conflicting ownership values require source-document review and must not be inferred by the system.

## Geometry

Store normalized geometries in EPSG:4326. Reject empty, invalid, or out-of-bounds geometries from the canonical geometry field while retaining the original source row. Flag overlapping parcel polygons for human review; do not automatically edit boundaries.
