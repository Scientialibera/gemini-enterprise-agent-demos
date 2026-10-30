"""Domain Data Models for Growth Analytics Multi-Agent System.

This package defines structured Pydantic models contractually shared between
tools, agent stages, and external reporting facades.
"""

from growth_analysis_workflow.models.agent_models import AgentViewContract
from growth_analysis_workflow.models.greview_models import ReviewItem, StoreReviewSummary
from growth_analysis_workflow.models.local_news_models import LocalNewsArticle, LocalNewsSummary
from growth_analysis_workflow.models.macro_models import (
    BlsMacroDetails,
    FredRetailSalesDetails,
    MacroLaborSummary,
    StateUnemploymentDetail,
)
from growth_analysis_workflow.models.qsr_news_models import NewsArticle, QsrNewsSummary
from growth_analysis_workflow.models.weather_models import (
    DailyWeatherRecord,
    LocationQuery,
    StoreWeatherSummary,
)

__all__ = [
    "AgentViewContract",
    "ReviewItem",
    "StoreReviewSummary",
    "LocalNewsArticle",
    "LocalNewsSummary",
    "FredRetailSalesDetails",
    "StateUnemploymentDetail",
    "BlsMacroDetails",
    "MacroLaborSummary",
    "NewsArticle",
    "QsrNewsSummary",
    "LocationQuery",
    "DailyWeatherRecord",
    "StoreWeatherSummary",
]
