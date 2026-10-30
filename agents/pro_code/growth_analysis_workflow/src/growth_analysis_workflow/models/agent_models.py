"""Pydantic schemas for Specialized ADK Agent Outputs."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class AgentViewContract(BaseModel):
    """Standard Dual-View Contract schema enforced across all agents."""

    concise_view: List[str] = Field(
        ...,
        description="Short, crisp, high-impact bullet points highlighting core executive takeaways.",
    )
    detailed_view: Dict[str, Any] = Field(
        ...,
        description="Executive-level structured information dictionary organizing data from the tool.",
    )
