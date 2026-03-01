"""Public config API: unauthenticated config for the frontend (e.g. analytics scripts)."""
import json
from typing import Any

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["public-config"])


@router.get("/api/public-config")
async def get_public_config() -> dict[str, Any]:
    """
    Return public configuration for the frontend (no auth required).
    Used to inject optional analytics scripts (Plausible, Google Analytics, custom) from env.
    """
    analytics: dict[str, Any] = {}

    if settings.plausible_domain:
        analytics["plausible"] = {
            "domain": settings.plausible_domain,
            "scriptSrc": settings.plausible_script_src
            or "https://plausible.io/js/script.file-downloads.hash.outbound-links.js",
        }
    else:
        analytics["plausible"] = None

    if settings.ga_measurement_id:
        analytics["gaMeasurementId"] = settings.ga_measurement_id
    else:
        analytics["gaMeasurementId"] = None

    custom_scripts: list[dict[str, Any]] = []
    if settings.analytics_custom_scripts:
        try:
            raw = json.loads(settings.analytics_custom_scripts)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and ("src" in item or "inline" in item):
                        custom_scripts.append(item)
        except (json.JSONDecodeError, TypeError):
            pass
    analytics["customScripts"] = custom_scripts

    return {"analytics": analytics}
