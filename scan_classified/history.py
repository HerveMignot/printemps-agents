"""Tracking of previously seen ads across runs."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gistfs import GistFS
from pydantic import BaseModel

GIST_FILENAME = "seen_ads.json"


class SeenAd(BaseModel):
    """Tracks a previously seen ad across runs."""
    ad_id: str
    date_added: datetime
    date_lastseen: datetime
    matched: bool
    reason: str
    version_matched: int
    date_emailed: Optional[datetime] = None
    city: str


def _parse_seen_ads(data: dict) -> dict[str, SeenAd]:
    return {ad_id: SeenAd.model_validate(entry) for ad_id, entry in data.items()}


def _serialize_seen_ads(seen_ads: dict[str, SeenAd]) -> dict:
    return {ad_id: ad.model_dump(mode="json") for ad_id, ad in seen_ads.items()}


# --- Local file backend ---

def load_seen_ads(path: Path) -> dict[str, SeenAd]:
    """Load seen ads from a local JSON file. Returns empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return _parse_seen_ads(json.load(f))


def save_seen_ads(path: Path, seen_ads: dict[str, SeenAd]) -> None:
    """Save seen ads to a local JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_serialize_seen_ads(seen_ads), f, indent=2, default=str)


# --- GitHub Gist backend ---

def load_seen_ads_gist(gist_id: str, token: str) -> dict[str, SeenAd]:
    """Load seen ads from a GitHub Gist. Returns empty dict if file not found."""
    gfs = GistFS(gist_id, token)
    if not gfs.exists(GIST_FILENAME):
        return {}
    data = gfs.read(GIST_FILENAME)
    return _parse_seen_ads(data)


def save_seen_ads_gist(gist_id: str, token: str, seen_ads: dict[str, SeenAd]) -> None:
    """Save seen ads to a GitHub Gist."""
    gfs = GistFS(gist_id, token)
    gfs.write(GIST_FILENAME, _serialize_seen_ads(seen_ads))


def discard_old_ads(seen_ads: dict[str, SeenAd], threshold_days: int) -> dict[str, SeenAd]:
    """Remove ads not seen for longer than threshold_days."""
    now = datetime.now(timezone.utc)
    return {
        ad_id: ad for ad_id, ad in seen_ads.items()
        if (now - ad.date_lastseen).days <= threshold_days
    }


def should_call_llm(ad_id: str, seen_ads: dict[str, SeenAd], prompt_version: int) -> bool:
    """Return True if this ad needs LLM evaluation (new or prompt version changed)."""
    if ad_id not in seen_ads:
        return True
    return seen_ads[ad_id].version_matched != prompt_version


def should_email(ad: SeenAd, cooldown_days: int) -> bool:
    """Return True if a matched ad should be included in the email."""
    if not ad.matched:
        return False
    if ad.date_emailed is None:
        return True
    now = datetime.now(timezone.utc)
    return (now - ad.date_emailed).days >= cooldown_days
