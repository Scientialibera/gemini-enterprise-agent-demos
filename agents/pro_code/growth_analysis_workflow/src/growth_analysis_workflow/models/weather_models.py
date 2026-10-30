"""Pydantic schemas for Weather Data Models and Input Contracts."""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class StoreInput(BaseModel):
    """Input payload representing a store location for weather queries."""

    store_id: str = Field(..., description="Unique store identifier or store number.")
    store_name: Optional[str] = Field(
        None, description="Human-readable store name or location name."
    )
    city: Optional[str] = Field(None, description="City where the store is located.")
    state: Optional[str] = Field(None, description="Two-letter state abbreviation.")
    lat: float = Field(..., description="Latitude coordinate.")
    long: float = Field(..., description="Longitude coordinate.")
    target_date: Optional[str] = Field(
        None, description="Target end date for the L6W window (e.g., '10/4/26')."
    )  # ADD THIS LINE


class LocationQuery(BaseModel):
    """Query parameters for Open-Meteo API requests."""

    store_id: str
    lat: float
    long: float
    start_date: date
    end_date: date


class DailyWeatherRecord(BaseModel):
    """Daily weather observation log with computed anomaly flags."""

    date: str
    weather_condition: str
    temp_max_c: float
    temp_min_c: float
    temp_mean_c: float
    precipitation_in: float
    precipitation_hours: float
    snowfall_in: float
    wind_gust_max_mph: float
    anomaly_flags: List[str] = Field(default_factory=list)


class StoreWeatherSummary(BaseModel):
    """Complete aggregated weather metrics for a store (Pruned for LLM Context Efficiency)."""

    store_id: str
    latitude: float
    longitude: float
    analysis_period: str
    baseline_mean_temp_c: float
    total_anomalous_days: int
    total_rain_days: int
    total_snow_days: int
    key_storm_dates: List[str] = Field(default_factory=list)
    anomalous_daily_records: List[DailyWeatherRecord] = Field(default_factory=list)
