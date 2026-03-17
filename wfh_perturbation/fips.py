"""FIPS code utilities and state lookups.

Provides parsing of 11-digit tract FIPS codes and mappings between
state FIPS codes and postal abbreviations (needed for LODES URLs).
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple


# State FIPS -> lowercase postal abbreviation (for LODES URL construction)
STATE_FIPS_TO_ABBR: Dict[str, str] = {
    "01": "al", "02": "ak", "04": "az", "05": "ar", "06": "ca",
    "08": "co", "09": "ct", "10": "de", "11": "dc", "12": "fl",
    "13": "ga", "15": "hi", "16": "id", "17": "il", "18": "in",
    "19": "ia", "20": "ks", "21": "ky", "22": "la", "23": "me",
    "24": "md", "25": "ma", "26": "mi", "27": "mn", "28": "ms",
    "29": "mo", "30": "mt", "31": "ne", "32": "nv", "33": "nh",
    "34": "nj", "35": "nm", "36": "ny", "37": "nc", "38": "nd",
    "39": "oh", "40": "ok", "41": "or", "42": "pa", "44": "ri",
    "45": "sc", "46": "sd", "47": "tn", "48": "tx", "49": "ut",
    "50": "vt", "51": "va", "53": "wa", "54": "wv", "55": "wi",
    "56": "wy", "72": "pr",
}

ABBR_TO_STATE_FIPS: Dict[str, str] = {v: k for k, v in STATE_FIPS_TO_ABBR.items()}


def parse_tract_fips(fips: str) -> Tuple[str, str, str]:
    """Parse an 11-digit tract FIPS GEOID into (state, county, tract).

    Args:
        fips: 11-digit FIPS code like '36061000700'.

    Returns:
        Tuple of (state_fips='36', county_fips='061', tract_code='000700').
    """
    if len(fips) != 11:
        raise ValueError(f"Tract FIPS must be 11 digits, got {len(fips)}: '{fips}'")
    return fips[:2], fips[2:5], fips[5:]


def parse_block_fips(fips: str) -> Tuple[str, str, str, str]:
    """Parse a 15-digit block FIPS GEOID into (state, county, tract, block).

    Args:
        fips: 15-digit FIPS code.

    Returns:
        Tuple of (state_fips, county_fips, tract_code, block_code).
    """
    if len(fips) != 15:
        raise ValueError(f"Block FIPS must be 15 digits, got {len(fips)}: '{fips}'")
    return fips[:2], fips[2:5], fips[5:11], fips[11:]


def block_to_tract(block_fips: str) -> str:
    """Truncate a 15-digit block FIPS to its 11-digit tract FIPS."""
    return block_fips[:11]


def get_states_for_tracts(tract_fips: List[str]) -> Set[str]:
    """Return the set of state FIPS codes present in a list of tract FIPS codes."""
    return {parse_tract_fips(f)[0] for f in tract_fips}


def get_state_abbr(state_fips: str) -> str:
    """Convert a 2-digit state FIPS to a lowercase postal abbreviation."""
    abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    if abbr is None:
        raise ValueError(f"Unknown state FIPS: '{state_fips}'")
    return abbr


def group_tracts_by_state_county(tract_fips: List[str]) -> Dict[Tuple[str, str], List[str]]:
    """Group tract FIPS codes by (state, county) for efficient API batching.

    Returns:
        Dict mapping (state_fips, county_fips) -> list of full 11-digit tract FIPS.
    """
    groups: Dict[Tuple[str, str], List[str]] = {}
    for fips in tract_fips:
        st, co, _ = parse_tract_fips(fips)
        groups.setdefault((st, co), []).append(fips)
    return groups
