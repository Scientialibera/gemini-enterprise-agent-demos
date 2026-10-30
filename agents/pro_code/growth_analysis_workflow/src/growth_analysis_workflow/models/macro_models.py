"""Pydantic schemas for Macroeconomic & Labor Data Models (BLS v2 & FRED APIs)."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class StoreInput(BaseModel):
    """Input payload representing store location metadata for macroeconomic regional matching."""

    store_id: str = Field(..., description="Unique store identifier.")
    city: str = Field(..., description="City location.")
    state: str = Field(..., description="Two-letter U.S. state abbreviation (e.g., 'PA', 'NY').")
    dma: Optional[str] = Field(None, description="Designated Market Area / Metro region.")
    target_date: Optional[str] = Field(
        None, description="Target end date for the L6W window (e.g., '10/4/26')."
    )  # ADD THIS LINE


class FredRetailSalesDetails(BaseModel):
    """Structured response details for FRED Advance Retail Sales (Food Services)."""

    source: str = Field(default="Federal Reserve Bank of St. Louis (FRED)")
    series_id: str = Field(default="RSFSDPN")
    series_title: str = Field(default="Advance Retail Sales: Food Services and Drinking Places")
    value_millions_usd: Optional[str] = Field(
        None, description="Latest monthly retail food sales in Millions of USD."
    )
    date: Optional[str] = Field(None, description="Observation date (YYYY-MM-DD).")
    error: Optional[str] = Field(None, description="Error message if API call failed.")


class StateUnemploymentDetail(BaseModel):
    """State-level unemployment metric details."""

    series_id: str = Field(..., description="Dynamically generated BLS LAUS Series ID.")
    series_title: str = Field(default="State Local Area Unemployment Statistics (LAUS) Rate")
    rate: str = Field(
        ..., description="Latest state unemployment rate string (e.g., '3.8% (July 2026)')."
    )


class BlsMacroDetails(BaseModel):
    """Structured response details for BLS CPI Inflation and Unemployment metrics."""

    source: str = Field(default="U.S. Bureau of Labor Statistics (BLS)")
    cpi_series_id: str = Field(default="CUUR0000SEFV")
    cpi_series_title: str = Field(default="Consumer Price Index: Food Away From Home")
    cpi_summary: Optional[str] = Field(None, description="Human-readable CPI inflation summary.")
    national_unemployment_series_id: str = Field(default="LNS14000000")
    national_unemployment_series_title: str = Field(
        default="Civilian Unemployment Rate (Seasonally Adjusted)"
    )
    national_unemployment_rate: Optional[str] = Field(
        None, description="Latest U.S. national civilian unemployment rate."
    )
    state_unemployment_rates: Dict[str, StateUnemploymentDetail] = Field(
        default_factory=dict,
        description="Map of state codes to their detailed unemployment metric records.",
    )
    error: Optional[str] = Field(None, description="Error message if API call failed.")


class MacroLaborSummary(BaseModel):
    """Aggregated macroeconomic & labor summary containing consumer spending, CPI, and employment data."""

    fred_retail_sales: FredRetailSalesDetails
    bls_macro_and_labor: BlsMacroDetails
    covered_states: List[str] = Field(
        default_factory=list, description="Unique state abbreviations analyzed in this batch."
    )
