"""Utility functions for the scan_classified agent."""

import yaml
from datetime import datetime
from typing import Optional


def load_config(yaml_path: str) -> dict:
    """Load cities and recipients from YAML file."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_ad_id(url: str) -> str:
    """Extract the ad ID from the URL (last segment of the path)."""
    return url.rstrip("/").split("/")[-1]


def extract_land_surface(ad) -> Optional[int]:
    """Extract land_plot_surface from ad attributes."""
    if not hasattr(ad, 'attributes') or not ad.attributes:
        return None
    for attr in ad.attributes:
        if attr.key == "land_plot_surface":
            try:
                return int(attr.value)
            except (ValueError, TypeError):
                return None
    return None


def extract_tenure(ad) -> Optional[str]:
    """Extract tenure from first_publication_date and format as days or months."""
    if not hasattr(ad, 'first_publication_date') or not ad.first_publication_date:
        return None
    try:
        pub_date = datetime.strptime(ad.first_publication_date, "%Y-%m-%d %H:%M:%S")
        days = (datetime.now() - pub_date).days
        if days < 45:
            return f"{days} jour" + ("s" if days > 1 else "")
        else:
            months = round(days / 30)
            return f"{months} mois"
    except (ValueError, TypeError):
        print(f"Error extracting tenure from {ad.first_publication_date}")
        return None


def format_number_fr(value: float, decimals: int = 0) -> str:
    """Format number with French locale (space as thousand sep, comma as decimal sep)."""
    if decimals > 0:
        formatted = f"{value:,.{decimals}f}"
    else:
        formatted = f"{value:,.0f}"
    return formatted.replace(",", " ").replace(".", ",")
