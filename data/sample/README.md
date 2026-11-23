# Synthetic sample data inventory

All records and names below are fictional and do not represent government records.

| File | Format / declared CRS | Deliberate data cases |
|---|---|---|
| `source_a.csv` | CSV, latitude/longitude in WGS 84 (EPSG:4326), area in acres | Repeated K-101, missing owner, negative area, latitude outside valid range, mixed date formats. |
| `source_b.xlsx` | Excel, projected coordinates in UTM zone 43N (EPSG:32643), area in hectares | K-102 with conflicting area, missing owner, alternate column names and date style. CRS and units are stated in the `Source_Metadata` sheet. |
| `source_c.geojson` | GeoJSON, CRS84 longitude/latitude (equivalent axis order for EPSG:4326) | K-102 cross-source area candidate, missing area, malformed date, self-intersecting polygon, wrong geometry type, longitude outside range. |

The fixtures are intentionally imperfect. A processing implementation must preserve each row and report issues instead of silently correcting or dropping critical values.
