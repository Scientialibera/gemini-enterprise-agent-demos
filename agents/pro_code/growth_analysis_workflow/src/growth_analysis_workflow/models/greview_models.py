"""Pydantic schemas for Google Places Customer Reviews Data Models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class StoreInput(BaseModel):
    """Input payload representing a store location for reviews queries."""

    store_id: str = Field(..., description="Unique store identifier.")
    store_name: Optional[str] = Field(None, description="Human-readable store or brand name.")
    city: str = Field(..., description="City location.")
    state: str = Field("", description="Two-letter state abbreviation.")
    address: Optional[str] = Field(None, description="Full street address if available.")
    target_date: Optional[str] = Field(
        None, description="Target end date for the L6W window (e.g., '10/4/26')."
    )  # ADD THIS LINE


class ReviewItem(BaseModel):
    """Individual customer review model."""

    author_name: str = Field(default="Anonymous", description="Reviewer author name.")
    rating: float = Field(
        default=0.0, description="Star rating given by the reviewer (1.0 to 5.0)."
    )
    relative_time: str = Field(
        default="", description="Relative publication timeframe (e.g., '2 weeks ago')."
    )
    text: str = Field(default="", description="Textual body of the review.")


class StoreReviewSummary(BaseModel):
    """Aggregated customer review summary for a single store location."""

    store_id: str = Field(..., description="Unique store identifier.")
    place_id: Optional[str] = Field(None, description="Google Places unique identifier.")
    display_name: str = Field(default="", description="Resolved place name from Google Places API.")
    rating: float = Field(default=0.0, description="Overall Google star rating.")
    user_rating_count: int = Field(default=0, description="Total number of ratings submitted.")
    recent_reviews: List[ReviewItem] = Field(
        default_factory=list, description="List of recent customer reviews."
    )
    # negative_sentiment_triggers: List[str] = Field(
    #     default_factory=list,
    #     description="Identified operational execution keywords (e.g., wait time, cold food, missing items)."
    # )
