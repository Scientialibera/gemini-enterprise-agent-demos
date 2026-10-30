"""The sample data has the shape the agents query, so tests against it mean something."""

from __future__ import annotations

import datetime as dt
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "deployment"
sys.path.insert(0, str(DEV))
sample = importlib.import_module("seed.sample_data")
drive = importlib.import_module("seed.sample_drive_files")
kitchen = importlib.import_module("seed.kitchen_compliance")
sys.path.remove(str(DEV))

TODAY = dt.date(2026, 10, 12)
TABLES = {(t.dataset, t.name): t for t in sample.TABLES}


@pytest.mark.parametrize("table", sample.TABLES, ids=lambda t: f"{t.dataset}.{t.name}")
def test_rows_match_their_schema(table):
    names = [name for name, _, _ in table.schema]
    required = {name for name, _, mode in table.schema if mode == "REQUIRED"}
    rows = list(table.rows(TODAY))
    assert rows, "a sample table with no rows tests nothing"
    for row in rows:
        assert list(row) == names
        assert all(row[name] is not None for name in required)


def test_rows_are_deterministic():
    for table in sample.TABLES:
        assert list(table.rows(TODAY)) == list(table.rows(TODAY))


def test_kitchen_sql_only_uses_sample_columns():
    """Every source column the curated-table SQL reads exists in the sample tables."""
    columns = {
        name: {c for c, _, _ in TABLES[("hdr_analytics", name)].schema}
        for name in ("int_hdr_order_compliance_agg", "hdr_compliance_items")
    }
    known = columns["int_hdr_order_compliance_agg"] | columns["hdr_compliance_items"]
    produced = {"week_start", "service_date", "orders", "items", "refreshed_at"}
    for _, sql in kitchen.statements():
        body = re.sub(r"--[^\n]*", "", sql)
        # Output aliases are not source columns.
        body = re.sub(r"\bAS\s+[a-z_][a-z0-9_]*", "", body)
        referenced = set(re.findall(r"\bo\.([a-z0-9_]+)", body))
        assert referenced <= known, referenced - known
        # Bare columns in the item-level statements.
        if "hdr_compliance_items`" in body and "SELECT" in body:
            for name in re.findall(
                r"\b([a-z][a-z0-9_]*_(?:issue|tier|cook|scanned|fault|hour))\b", body
            ):
                assert name in known | produced, name


def test_recipe_prompt_columns_exist_in_the_sample_tables():
    """Recipe Editorial's prompt lists each table's columns; the sample must have them."""
    prompt = (ROOT / "agents/no_code/recipe_editorial_agent/prompt.md").read_text(encoding="utf-8")
    blocks = re.findall(
        # The prompt is Markdown exported from the agent designer, so backticks are escaped.
        r"\\?`\$\{RECIPE_(PRODUCT|LEGACY)_DATASET\}\.([a-z_]+)\\?`[^\n]*\n\s*\n?Columns: ([^\n]+)",
        prompt,
    )
    assert len(blocks) == 8, blocks
    for kind, table, listed in blocks:
        dataset = (
            sample.RECIPE_PRODUCT_DATASET if kind == "PRODUCT" else sample.RECIPE_LEGACY_DATASET
        )
        have = {name for name, _, _ in TABLES[(dataset, table)].schema}
        want = {c.strip(" .") for c in listed.split(",")}
        assert want <= have, (table, want - have)


def test_kitchen_sample_has_recent_declining_kitchens():
    rows = list(TABLES[("hdr_analytics", "int_hdr_order_compliance_agg")].rows(TODAY))
    latest = max(r["service_date_et"] for r in rows)
    assert latest == (TODAY - dt.timedelta(days=1)).isoformat()

    def rate(hdr, start, end):
        window = [
            r
            for r in rows
            if r["hdr_id"] == hdr and start <= dt.date.fromisoformat(r["service_date_et"]) < end
        ]
        return sum(r["has_force_complete"] for r in window) / len(window)

    recent = (TODAY - dt.timedelta(days=14), TODAY)
    before = (TODAY - dt.timedelta(days=42), TODAY - dt.timedelta(days=14))
    for hdr in sample.DECLINING:
        assert rate(hdr, *recent) > 1.5 * rate(hdr, *before)


def test_recipe_sample_has_the_documented_faults():
    products = {
        r["recipe_sku"]: r for r in TABLES[("recipe_products", "culinary_products")].rows(TODAY)
    }
    assert products["604430003"]["active_cook_time"] > products["604430003"]["total_cook_time"]
    steps = " ".join(
        r["step_text"]
        for r in TABLES[("recipe_legacy", "legacy_recipe_steps")].rows(TODAY)
        if r["recipe_id"] == 66006
    )
    assert "cilantro" in steps.lower()
    assert "cilantro" not in sample.INGREDIENTS[66006]
    slots = list(TABLES[("recipe_legacy", "legacy_cycle_recipe_slots")].rows(TODAY))
    assert all(sum(s["recipe_id"] == r[1] for s in slots) >= 2 for r in sample.RECIPES)


def test_load_replaces_tables_without_touching_iam(monkeypatch):
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    client = Mock()
    client.get_dataset.side_effect = NotFound("missing")
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: client)
    loaded = sample.load_sample_data("test-project", "US")
    assert client.create_dataset.call_count == 3
    assert len(loaded) == len(sample.TABLES)
    config = client.load_table_from_json.call_args.kwargs["job_config"]
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert not any("iam" in str(c).lower() for c in client.mock_calls)


def test_kitchen_tables_default_to_the_sample_source(monkeypatch):
    monkeypatch.setenv(kitchen.SEED_ENV, "true")
    monkeypatch.setenv(sample.SEED_ENV, "true")
    monkeypatch.delenv(kitchen.SOURCE_PROJECT_ENV, raising=False)
    from google.cloud import bigquery

    client = Mock()
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: client)
    kitchen.prepare_kitchen_compliance("test-project")
    assert all("test-project.hdr_analytics" in c.args[0] for c in client.query.call_args_list)


def _sheet_values(book):
    """What the Sheets API returns for a tab: rows of strings, trailing blanks dropped."""

    def read(spreadsheet_id, range_name, header_row):
        import re as _re

        import pandas as pd

        sheet = book[range_name.strip("'")]
        values = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            while cells and cells[-1] == "":
                cells.pop()
            values.append(cells)
        if len(values) <= header_row - 1:
            return pd.DataFrame(), values
        width = max(len(r) for r in values)
        frame = pd.DataFrame([r + [""] * (width - len(r)) for r in values])
        headers = [
            _re.sub(r"\s+", " ", str(v)).strip() or f"Column_{i + 1}"
            for i, v in enumerate(frame.iloc[header_row - 1].tolist())
        ]
        frame.columns = headers
        return frame.iloc[header_row:].reset_index(drop=True), values

    return read


def test_performance_sheet_reads_through_the_growth_sheet_reader(monkeypatch):
    """The V2 sheet reader finds both cohorts, benchmarks and owner tags in the sample."""
    import json

    from growth_analysis_workflow.config_loader import load_agent_config
    from growth_analysis_workflow.tools import sheet_reader_tool

    book = drive.performance_workbook(as_of="2026-10-09")
    config = load_agent_config("sheet_reader_agent")
    assert [config["sheet1_18mo"]["tab_name"], config["sheet1_15mo"]["tab_name"]] == list(
        drive.COHORT_TABS
    )
    needed = [
        *config["table_columns"],
        *(m["name"] for m in config["metrics_config"]["must_have"]),
        *(m["name"] for m in config["metrics_config"]["nice_to_have"]),
    ]
    assert set(needed) <= set(drive.METRIC_COLUMNS)

    monkeypatch.setattr(sheet_reader_tool, "read_google_sheet", _sheet_values(book))
    result = json.loads(sheet_reader_tool.fetch_top_and_bottom_performing_stores("sample"))

    assert result["status"] == "success", result
    assert len(result["bottom_5_18mo_stores"]) == 5
    assert len(result["top_5_18mo_stores"]) == 5
    bottom_15 = {s["Kitchen Name"] for s in result["bottom_3_15mo_stores"]}
    assert bottom_15 == {s[0] for s in drive.NEWER_STORES}
    assert not bottom_15 & {s["Kitchen Name"] for s in result["bottom_5_18mo_stores"]}
    stores = result["bottom_5_weather_agent_input"]
    assert len(stores) == 8
    assert all(s["lat"] and s["target_date"] == "2026-10-09" for s in stores)
    evaluation = result["tldr_store_evaluations"][0]
    core = {m["metric"]: m for m in evaluation["core_performance_metrics"]}
    assert core["Google Rating"]["benchmark_value"] is not None
    assert core["Google Rating"]["owner_tag"] == "@cx"


def test_a_sheet_with_its_own_headers_reads_through_column_aliases(monkeypatch):
    """A client sheet's headers map onto the canonical names through settings alone."""
    import json

    from growth_analysis_workflow.tools import sheet_reader_tool

    book = drive.performance_workbook(as_of="2026-10-09")
    renamed = {"Kitchen Name": "Store", "Google Rating": "Rating (Google)"}
    for title in drive.COHORT_TABS:
        for cell in book[title][11]:
            if cell.value in renamed:
                cell.value = renamed[cell.value]
    monkeypatch.setattr(sheet_reader_tool, "read_google_sheet", _sheet_values(book))

    monkeypatch.delenv("GROWTH_SETTINGS_OVERRIDE", raising=False)
    without = json.loads(sheet_reader_tool.fetch_top_and_bottom_performing_stores("sample"))
    assert not without.get("bottom_5_18mo_stores"), "unmapped headers should find no stores"

    override = {"sheet_reader_agent": {"column_aliases": renamed}}
    monkeypatch.setenv("GROWTH_SETTINGS_OVERRIDE", json.dumps(override))
    result = json.loads(sheet_reader_tool.fetch_top_and_bottom_performing_stores("sample"))
    assert len(result["bottom_5_18mo_stores"]) == 5
    core = {m["metric"]: m for m in result["tldr_store_evaluations"][0]["core_performance_metrics"]}
    assert core["Google Rating"]["benchmark_value"] is not None


def test_master_dictionary_matches_what_vendor_match_reads(tmp_path):
    written = drive.write_files(tmp_path)
    assert {p.name for p in written} == set(drive.FILES)
    import pandas as pd

    frame = pd.read_excel(
        tmp_path / "master_vendor_dictionary.xlsx", sheet_name="Master Dictionary"
    )
    assert list(frame.columns) == ["Standardized Vendor Name", "Raw Vendor Variant"]
    incoming = pd.read_excel(tmp_path / "incoming_vendors_sample.xlsx")
    assert "Vendor Name" in incoming.columns
