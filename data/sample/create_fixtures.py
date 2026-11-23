"""Generate the fictional Excel input used by the project demo."""

from pathlib import Path

from openpyxl import Workbook


def main() -> None:
    output = Path(__file__).with_name("source_b.xlsx")
    workbook = Workbook()
    records = workbook.active
    records.title = "Parcels"
    records.append(
        ["Plot_Number", "Landholder", "Size_Hectares", "Easting_m", "Northing_m", "Surveyed_On"]
    )
    records.append(["K-102", "Rahul Das", 0.51, 716300, 3168000, "20-Feb-2024"])
    records.append(["K-104", None, 0.32, 717100, 3168500, "2024-04-12"])
    records.append(["K-107", "Leela Iyer", 0.0, 717500, 3169000, "12/31/2024"])

    metadata = workbook.create_sheet("Source_Metadata")
    metadata.append(["Property", "Value"])
    metadata.append(["Dataset", "Fictional district parcel extract"])
    metadata.append(["Coordinate reference system", "EPSG:32643 - WGS 84 / UTM zone 43N"])
    metadata.append(["Coordinate columns", "Easting_m and Northing_m"])
    metadata.append(["Area unit", "hectares"])
    metadata.append(["Notice", "Synthetic data only; not government records"])
    workbook.save(output)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
