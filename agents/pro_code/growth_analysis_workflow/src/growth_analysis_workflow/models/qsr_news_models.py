"""Pydantic schemas for QSR Industry Publications Data Models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class StoreInput(BaseModel):
    """Input payload representing store metadata."""

    store_id: str = Field(..., description="Unique store identifier.")
    city: str = Field(..., description="City location.")
    state: str = Field(..., description="Two-letter state abbreviation.")
    target_date: Optional[str] = Field(
        None, description="Target end date for the L6W window (e.g., '10/4/26')."
    )  # ADD THIS LINE


class NewsArticle(BaseModel):
    """Individual industry news article model."""

    title: str = Field(..., description="Article headline title.")
    link: str = Field(..., description="URL link to full article.")
    published: str = Field(default="2026", description="Publication date string.")
    source: str = Field(..., description="Publisher source name (e.g., 'QSR Magazine').")


class QsrNewsSummary(BaseModel):
    """Aggregated QSR industry news summary."""

    total_articles_ingested: int = Field(
        default=0, description="Count of articles parsed across RSS feeds."
    )
    articles: List[NewsArticle] = Field(
        default_factory=list, description="List of parsed article objects."
    )
    parsed_sources: List[str] = Field(
        default_factory=list, description="List of publication feed sources checked."
    )
