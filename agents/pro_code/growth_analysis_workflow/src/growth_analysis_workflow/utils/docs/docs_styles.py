"""Google Docs report styling constants and brand palette."""

from typing import Dict

# Default report palette (RGB normalized 0.0 - 1.0)
DEFAULT_PALETTE: Dict[str, Dict[str, float]] = {
    "cream_bg": {"red": 0.961, "green": 0.953, "blue": 0.914},  # #F5F3E9
    "header_green": {"red": 0.298, "green": 0.706, "blue": 0.451},  # #4CB473
    "title_green": {"red": 0.129, "green": 0.322, "blue": 0.208},  # #215235
    "cell_bg": {"red": 0.980, "green": 0.976, "blue": 0.961},  # #FAF9F5
    "white": {"red": 1.0, "green": 1.0, "blue": 1.0},
    "charcoal": {"red": 0.133, "green": 0.133, "blue": 0.133},
    "faded_gray": {"red": 0.4, "green": 0.4, "blue": 0.4},
}
