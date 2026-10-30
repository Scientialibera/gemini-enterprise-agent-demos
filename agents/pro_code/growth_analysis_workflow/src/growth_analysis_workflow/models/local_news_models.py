"""Pydantic schemas for Local News & Metro Market Data Models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class StoreInput(BaseModel):
    """Input payload representing store location metadata for local market news queries."""

    store_id: str = Field(..., description="Unique store identifier.")
    city: str = Field(..., description="City location.")
    state: str = Field(..., description="Two-letter state abbreviation.")
    dma: Optional[str] = Field(None, description="Designated Market Area / Metro region.")
    target_date: Optional[str] = Field(
        None, description="Target end date for the L6W window (e.g., '10/4/26')."
    )  # ADD THIS LINE


class LocalNewsArticle(BaseModel):
    """Individual local market or regional competitor article model."""

    headline: str = Field(..., description="Article headline title.")
    snippet: str = Field(default="", description="Brief article excerpt or summary snippet.")
    source: str = Field(..., description="Publisher name (e.g., 'New York Times', 'Eater Philly').")
    pub_date: str = Field(
        default="", description="Publication date string (YYYY-MM-DD or ISO format)."
    )
    url: Optional[str] = Field(None, description="Direct URL link to full article.")


class LocalNewsSummary(BaseModel):
    """Aggregated local news and metro market summary across all store locations."""

    cities_searched: List[str] = Field(
        default_factory=list, description="Unique list of target cities queried."
    )
    total_articles_found: int = Field(
        default=0, description="Total count of relevant local news items retrieved."
    )
    articles: List[LocalNewsArticle] = Field(
        default_factory=list, description="Parsed local article records."
    )
