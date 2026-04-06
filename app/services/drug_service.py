"""Drug interaction service — NLM RxNorm API client.

Authoritative source for drug-drug interactions. Gemini is ONLY used
to explain interactions in plain language, never as the source of truth.

API docs: https://lhncbc.nlm.nih.gov/RxNav/APIs/InteractionAPIs.html
"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)

RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
INTERACTION_BASE_URL = "https://rxnav.nlm.nih.gov/REST/interaction"

# Simple in-memory cache for RxCUI lookups (24-hour TTL handled by app restart)
_rxcui_cache: dict[str, int | None] = {}
_interaction_cache: dict[str, str] = {}


async def get_rxcui(drug_name: str) -> int | None:
    """Look up the RxCUI identifier for a drug name.

    Args:
        drug_name: Drug name in English (e.g., "metformin", "lisinopril").

    Returns:
        RxCUI integer identifier, or None if not found.
    """
    cache_key = drug_name.lower().strip()
    if cache_key in _rxcui_cache:
        return _rxcui_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{RXNORM_BASE_URL}/rxcui.json",
                params={"name": drug_name, "search": 1},
            )
            response.raise_for_status()
            data = response.json()

            id_group = data.get("idGroup", {})
            rxnorm_id = id_group.get("rxnormId")

            if rxnorm_id:
                rxcui = int(rxnorm_id[0]) if isinstance(rxnorm_id, list) else int(rxnorm_id)
                _rxcui_cache[cache_key] = rxcui
                return rxcui

    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        logger.warning("RxNorm lookup failed for drug: %s", drug_name)

    _rxcui_cache[cache_key] = None
    return None


async def check_interaction(rxcui_a: int, rxcui_b: int) -> str:
    """Check for interactions between two drugs by their RxCUI identifiers.

    Args:
        rxcui_a: RxCUI of the first drug.
        rxcui_b: RxCUI of the second drug.

    Returns:
        JSON string of interaction data, or '{"interactions": []}' if none found.
    """
    cache_key = f"{min(rxcui_a, rxcui_b)}_{max(rxcui_a, rxcui_b)}"
    if cache_key in _interaction_cache:
        return _interaction_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{INTERACTION_BASE_URL}/list.json",
                params={"rxcuis": f"{rxcui_a}+{rxcui_b}"},
            )
            response.raise_for_status()
            data = response.json()

            interactions = data.get("fullInteractionTypeGroup", [])
            if interactions:
                result = json.dumps(interactions, ensure_ascii=False)
                _interaction_cache[cache_key] = result
                return result

    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning(
            "RxNorm interaction check failed for RxCUI pair: %d, %d",
            rxcui_a,
            rxcui_b,
        )

    no_interaction = '{"interactions": []}'
    _interaction_cache[cache_key] = no_interaction
    return no_interaction


async def check_drug_interaction(drug_a: str, drug_b: str) -> str:
    """Check for interactions between two drugs by name.

    Convenience function that resolves names to RxCUI then checks interactions.

    Args:
        drug_a: First drug name in English.
        drug_b: Second drug name in English.

    Returns:
        JSON string of interaction data.
    """
    rxcui_a = await get_rxcui(drug_a)
    rxcui_b = await get_rxcui(drug_b)

    if rxcui_a is None or rxcui_b is None:
        missing = []
        if rxcui_a is None:
            missing.append(drug_a)
        if rxcui_b is None:
            missing.append(drug_b)
        return json.dumps(
            {
                "interactions": [],
                "note": f"Could not find RxCUI for: {', '.join(missing)}",
            },
            ensure_ascii=False,
        )

    return await check_interaction(rxcui_a, rxcui_b)


def clear_cache() -> None:
    """Clear the RxCUI and interaction caches. Useful for testing."""
    _rxcui_cache.clear()
    _interaction_cache.clear()
