"""
Vendor Resolution Schema Module.

Defines the structured Pydantic schema for LLM-driven vendor resolution and clustering.
"""

from typing import List

from pydantic import BaseModel, Field


class VendorResolution(BaseModel):
    source_vendor: str = Field(
        description="The exact original 'Vendor Name' passed as the primary key in the input task."
    )
    standardized_vendor_name: str = Field(
        description="The cleanest, title-cased master parent brand name selected from the input strings."
    )
    unique_variants: List[str] = Field(
        description="A list of matching corporate variants and extensions from the contender pool belonging to this master entity."
    )


__all__ = ["VendorResolution"]
