"""Synthetic Google Drive files for Growth Analysis and Vendor Match.

    growth_performance_sample.xlsx    the store performance sheet Growth Analysis
                                      reads: the 18- and 15-month cohort tabs
                                      (benchmarks on rows 3-6, owner tags on row
                                      10, header on row 11) and the "ArcGIS (HH,
                                      At Scale GOV)" location tab (header on row 3),
                                      keyed by kitchen name
    master_vendor_dictionary.xlsx     Vendor Match's master dictionary
    incoming_vendors_sample.xlsx      a vendor list to standardize, with variants
                                      of known vendors and some new ones

Every value is made up. Write the files, then put them in Drive:

    uv run --group dev python deployment/seed/sample_drive_files.py
    uv run --group dev python deployment/seed/sample_drive_files.py --upload \\
        --growth-folder <id> --master-folder <id> --source-folder <id>

Upload converts the performance sheet to a Google Sheet (the agent reads it through
the Sheets API) and prints its ID for GROWTH_SPREADSHEET_ID. It needs ADC with the
Drive scope:

    gcloud auth application-default login \\
        --scopes=openid,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "sample_data" / "drive"
SEED = 20261012

# Kitchen name, DMA, city, county, state, zip, lat, long. Names match the BigQuery
# sample kitchens, so the two data sets describe the same (fictional) stores.
STORES = (
    ("South Congress Kitchen", "Austin", "Austin", "Travis", "TX", "78704", 30.2496, -97.7497),
    ("Round Rock Kitchen", "Austin", "Round Rock", "Williamson", "TX", "78664", 30.5083, -97.6789),
    ("Uptown Kitchen", "Dallas-Ft. Worth", "Dallas", "Dallas", "TX", "75201", 32.7990, -96.8010),
    ("Plano Kitchen", "Dallas-Ft. Worth", "Plano", "Collin", "TX", "75093", 33.0198, -96.6989),
    ("Heights Kitchen", "Houston", "Houston", "Harris", "TX", "77008", 29.7988, -95.3984),
    ("Highlands Kitchen", "Denver", "Denver", "Denver", "CO", "80211", 39.7620, -105.0110),
    ("Littleton Kitchen", "Denver", "Littleton", "Arapahoe", "CO", "80120", 39.6133, -105.0166),
    ("Wicker Park Kitchen", "Chicago", "Chicago", "Cook", "IL", "60622", 41.9088, -87.6796),
    ("Naperville Kitchen", "Chicago", "Naperville", "DuPage", "IL", "60540", 41.7508, -88.1535),
    (
        "North Loop Kitchen",
        "Minneapolis-St. Paul",
        "Minneapolis",
        "Hennepin",
        "MN",
        "55401",
        44.9893,
        -93.2760,
    ),
    (
        "Edina Kitchen",
        "Minneapolis-St. Paul",
        "Edina",
        "Hennepin",
        "MN",
        "55424",
        44.8897,
        -93.3499,
    ),
    ("Midtown Kitchen", "Atlanta", "Atlanta", "Fulton", "GA", "30308", 33.7810, -84.3830),
    (
        "Pearl District Kitchen",
        "San Antonio",
        "San Antonio",
        "Bexar",
        "TX",
        "78215",
        29.4436,
        -98.4800,
    ),
    ("Frisco Kitchen", "Dallas-Ft. Worth", "Frisco", "Collin", "TX", "75034", 33.1507, -96.8236),
    ("Boulder Kitchen", "Denver", "Boulder", "Boulder", "CO", "80302", 40.0150, -105.2705),
    ("Evanston Kitchen", "Chicago", "Evanston", "Cook", "IL", "60201", 42.0451, -87.6877),
    ("Decatur Kitchen", "Atlanta", "Decatur", "DeKalb", "GA", "30030", 33.7748, -84.2963),
    ("Alpharetta Kitchen", "Atlanta", "Alpharetta", "Fulton", "GA", "30009", 34.0754, -84.2941),
    ("Tempe Kitchen", "Phoenix", "Tempe", "Maricopa", "AZ", "85281", 33.4255, -111.9400),
    ("Scottsdale Kitchen", "Phoenix", "Scottsdale", "Maricopa", "AZ", "85251", 33.4942, -111.9261),
)
# Stores open 15 to 18 months: only on the 15-month tab. Same columns as STORES.
NEWER_STORES = (
    ("Short North Kitchen", "Columbus", "Columbus", "Franklin", "OH", "43215", 39.9780, -83.0030),
    ("Cary Kitchen", "Raleigh-Durham", "Cary", "Wake", "NC", "27513", 35.7915, -78.7811),
    (
        "Crossroads Kitchen",
        "Kansas City",
        "Kansas City",
        "Jackson",
        "MO",
        "64108",
        39.0910,
        -94.5830,
    ),
    ("The Gulch Kitchen", "Nashville", "Nashville", "Davidson", "TN", "37203", 36.1526, -86.7895),
    (
        "South End Kitchen",
        "Charlotte",
        "Charlotte",
        "Mecklenburg",
        "NC",
        "28203",
        35.2131,
        -80.8582,
    ),
)
# Same-store sales: five negative on the 18-month tab, so the report has a bottom
# five to diagnose, and three more among the newer stores for the 15-month bottom three.
SSS = (
    3.8,
    6.1,
    -7.4,
    2.2,
    -2.9,
    9.5,
    1.4,
    -1.8,
    -5.6,
    4.7,
    -3.3,
    0.9,
    5.2,
    7.8,
    2.9,
    -0.6,
    3.4,
    8.3,
    -4.4,
    1.7,
)
NEWER_SSS = (-4.1, -2.4, -6.3, 3.1, -1.2)
COHORT_TABS = ("L6W SSS Summary (18 Mo.)", "L6W SSS Summary (15 Mo.)")
# Header row 11 of each cohort tab: the table columns and the metrics the TL;DR
# evaluates (resources/agents/sheet_reader_agent.yaml), with how each is generated
# (low, high, format) and the owner tagged on row 10.
METRICS = {
    "Kitchen Name": None,
    "Population Type": None,
    "L6W SSS or YoY (Kitchen + MP)": None,
    "GOV (Kitchen + MP)": (60_000, 180_000, "money", "@finance"),
    "GOV (Kitchen Only)": (45_000, 140_000, "money", "@finance"),
    "GOV (MP Only)": (10_000, 50_000, "money", "@marketplace"),
    "App / Web Traffic (1P) - Overall": (4_000, 15_000, "thousands", "@growth"),
    "Conversion (1P)": (8, 16, "percent", "@growth"),
    "Taste Rating (Kitchen)": (3.8, 4.8, "rating", "@culinary"),
    "IOR % (Kitchen) Target = < 10%": (4, 14, "percent", "@ops"),
    "In-Stock Rate %": (91, 99, "percent", "@supply"),
    "Dinner Mix % Total GOV": (45, 70, "percent", "@growth"),
    "Promo GOV % 1P GOV": (5, 18, "percent", "@marketing"),
    "Households (Geolytix)": (18_000, 60_000, "thousands", "@real-estate"),
    "Google Rating": (3.6, 4.8, "rating", "@cx"),
    "3P GOV % of Total GOV": (15, 40, "percent", "@marketplace"),
    "MP % of 1P App / Web": (10, 35, "percent", "@marketplace"),
    "New Brand Mix % (Kitchen)": (5, 25, "percent", "@brands"),
    "O2E": (22, 38, "minutes", "@ops"),
    "Order Accuracy": (92, 99, "percent", "@ops"),
    "Value Rating (Kitchen)": (3.5, 4.6, "rating", "@marketing"),
}
METRIC_COLUMNS = tuple(METRICS)
BENCHMARKS = ("Total Simple Average", "Urban Simple Average", "Suburban Simple Average")
URBAN_CITIES = {
    "Austin",
    "Dallas",
    "Houston",
    "Denver",
    "Chicago",
    "Minneapolis",
    "Atlanta",
    "Columbus",
    "Kansas City",
    "San Antonio",
    "Tempe",
    "Nashville",
    "Charlotte",
}
LOCATION_COLUMNS = (
    "strategy_id",
    "strategy_name",
    "source",
    "dma",
    "city",
    "county",
    "state",
    "zip_code",
    "lat",
    "long",
)

MASTER = {
    "Sysco": ("Sysco Corp", "SYSCO CORPORATION", "Sysco Food Services", "sysco inc"),
    "US Foods": ("US Foods Inc", "U.S. Foods", "USFoods", "US FOODS HOLDING"),
    "Amazon": ("Amazon Web Services", "Amazon Business", "AMAZON.COM", "Amazon Marketplace"),
    "Restaurant Depot": ("Restaurant Depot LLC", "RESTAURANT DEPOT", "Rest Depot"),
    "Cintas": ("Cintas Corp", "CINTAS CORPORATION #2", "Cintas Uniforms"),
    "Ecolab": ("Ecolab Inc", "ECOLAB", "Ecolab Pest Elimination"),
    "Coca-Cola": ("Coca Cola Bottling", "COCA-COLA BEVERAGES", "Coke Northeast"),
}
INCOMING = (
    "SYSCO CORP",
    "Sysco Food Svcs",
    "US Foods, Inc.",
    "U S FOODS",
    "Amazon.com Services LLC",
    "AWS",
    "Restaurant Depot",
    "cintas corp no 2",
    "Ecolab Inc.",
    "Coca-Cola Bottling Co",
    # New vendors, not in the dictionary, some with their own variants.
    "Chef's Warehouse",
    "The Chefs' Warehouse Inc",
    "CHEFS WAREHOUSE MID-ATLANTIC",
    "Baldor Specialty Foods",
    "BALDOR FOOD",
    "Blue Engine Marketing",
    "Blue Cross Blue Shield",
    "Tiger Consulting LLC",
    "Hobart Service",
    "HOBART CORP",
    "Zoom Video Communications",
    "ZOOM.US",
)


def _format(value: float, kind: str) -> str:
    if kind == "money":
        return f"${value / 1000:.1f}K"
    if kind == "thousands":
        return f"{value / 1000:.1f}K"
    if kind == "percent":
        return f"{value:.1f}%"
    if kind == "rating":
        return f"{value:.2f}"
    return f"{value:.1f}"


def _cohort_tab(book: Workbook, title: str, stores, sss, rng: random.Random, as_of: str) -> None:
    """One cohort tab laid out as the sheet reader expects.

    Row 1 carries the L6W reference date in E1, rows 3 to 6 the benchmark
    averages (labelled "... Simple Average"), row 10 each metric's owner tag,
    row 11 the headers and row 12 on the stores.
    """
    sheet = book.create_sheet(title)
    sheet["A1"] = f"{title} (SAMPLE DATA - not real)"
    sheet["D1"] = "L6W ending"
    sheet["E1"] = as_of
    rows = []
    for store, value in zip(stores, sss, strict=True):
        numbers = {
            name: rng.uniform(spec[0], spec[1])
            for name, spec in METRICS.items()
            if spec is not None
        }
        # Total sales are the two channels added up, so the table reads consistently.
        numbers["GOV (Kitchen + MP)"] = numbers["GOV (Kitchen Only)"] + numbers["GOV (MP Only)"]
        urban = store[2] in URBAN_CITIES
        rows.append((store[0], "Urban" if urban else "Suburban", value, numbers))

    for offset, label in enumerate(BENCHMARKS):
        row = 3 + offset
        sheet.cell(row=row, column=1, value=label)
        kind = label.split()[0]
        members = [r for r in rows if kind == "Total" or r[1] == kind]
        for column, (name, spec) in enumerate(METRICS.items(), start=1):
            if spec is None or not members:
                continue
            average = sum(r[3][name] for r in members) / len(members)
            sheet.cell(row=row, column=column, value=_format(average, spec[2]))

    for column, (name, spec) in enumerate(METRICS.items(), start=1):
        if spec is not None:
            sheet.cell(row=10, column=column, value=spec[3])
        sheet.cell(row=11, column=column, value=name)
    for row, (name, population, value, numbers) in enumerate(rows, start=12):
        for column, (metric, spec) in enumerate(METRICS.items(), start=1):
            if metric == "Kitchen Name":
                cell = name
            elif metric == "Population Type":
                cell = population
            elif spec is None:
                cell = f"{value:.1f}%"
            else:
                cell = _format(numbers[metric], spec[2])
            sheet.cell(row=row, column=column, value=cell)


def performance_workbook(as_of: str | None = None) -> Workbook:
    """The 18- and 15-month cohort tabs and the store location tab.

    as_of is the L6W reference date written to E1 (YYYY-MM-DD); it defaults to
    three days ago, inside the weather archive's reach.
    """
    import datetime as dt

    as_of = as_of or (dt.date.today() - dt.timedelta(days=3)).isoformat()
    rng = random.Random(SEED)
    book = Workbook()
    book.remove(book.active)
    _cohort_tab(book, COHORT_TABS[0], STORES, SSS, rng, as_of)
    _cohort_tab(
        book,
        COHORT_TABS[1],
        STORES + NEWER_STORES,
        tuple(s + 0.4 for s in SSS) + NEWER_SSS,
        rng,
        as_of,
    )

    locations = book.create_sheet("ArcGIS (HH, At Scale GOV)")
    locations["A1"] = "Store locations (SAMPLE DATA)"
    for column, name in enumerate(LOCATION_COLUMNS, start=1):
        locations.cell(row=3, column=column, value=name)
    for row, (name, dma, city, county, state, zip_code, lat, lon) in enumerate(
        STORES + NEWER_STORES, start=4
    ):
        values = (f"S{row - 3:03d}", name, "sample", dma, city, county, state, zip_code, lat, lon)
        for column, value in enumerate(values, start=1):
            locations.cell(row=row, column=column, value=value)
    return book


def master_dictionary_workbook() -> Workbook:
    book = Workbook()
    sheet = book.active
    sheet.title = "Master Dictionary"
    sheet.append(("Standardized Vendor Name", "Raw Vendor Variant"))
    for master, variants in MASTER.items():
        for variant in (master, *variants):
            sheet.append((master, variant))
    return book


def incoming_vendors_workbook() -> Workbook:
    book = Workbook()
    sheet = book.active
    sheet.title = "Vendors"
    sheet.append(("Vendor Name", "Invoice Count"))
    rng = random.Random(SEED + 2)
    for name in INCOMING:
        sheet.append((name, rng.randint(1, 40)))
    return book


FILES = {
    "growth_performance_sample.xlsx": performance_workbook,
    "master_vendor_dictionary.xlsx": master_dictionary_workbook,
    "incoming_vendors_sample.xlsx": incoming_vendors_workbook,
}


def write_files(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, build in FILES.items():
        path = out / name
        build().save(path)
        written.append(path)
    return written


def upload(files: list[Path], folders: dict[str, str]) -> None:
    """Upload each file to its folder; the performance sheet becomes a Google Sheet."""
    import google.auth
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    for path in files:
        folder = folders[path.name]
        body: dict[str, object] = {"name": path.stem, "parents": [folder]}
        if path.name == "growth_performance_sample.xlsx":
            body["mimeType"] = "application/vnd.google-apps.spreadsheet"
        else:
            # Vendor Match finds the dictionary by its file name, extension included.
            body["name"] = path.name
        created = (
            drive.files()
            .create(
                body=body,
                media_body=MediaFileUpload(str(path), mimetype=xlsx),
                fields="id,name",
                supportsAllDrives=True,
            )
            .execute()
        )
        print(f"UPLOADED={created['name']} id={created['id']}")
        if path.name == "growth_performance_sample.xlsx":
            print(f"GROWTH_SPREADSHEET_ID={created['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--upload", action="store_true", help="Also upload the files to Drive.")
    parser.add_argument("--growth-folder", help="Folder for the performance sheet.")
    parser.add_argument("--master-folder", help="Vendor Match master dictionary folder.")
    parser.add_argument("--source-folder", help="Vendor Match source folder.")
    args = parser.parse_args()

    files = write_files(args.out)
    for path in files:
        print(f"WROTE={path}")
    if not args.upload:
        return
    folders = {
        "growth_performance_sample.xlsx": args.growth_folder,
        "master_vendor_dictionary.xlsx": args.master_folder,
        "incoming_vendors_sample.xlsx": args.source_folder,
    }
    missing = [name for name, folder in folders.items() if not folder]
    if missing:
        sys.exit("--upload needs --growth-folder, --master-folder and --source-folder.")
    upload(files, folders)


if __name__ == "__main__":
    main()
