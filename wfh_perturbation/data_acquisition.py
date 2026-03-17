"""Data acquisition layer (Spec Section 4.A).

Fetches educational attainment from the Census Bureau API (DA-1),
LODES WAC industry data (DA-2), and LODES OD commute flows (DA-3/DA-4).
Supports local file caching (DA-6) and records data vintages (DA-7).

Census API key must be provided via environment variable CENSUS_API_KEY,
a config file (wfh_perturbation/config/api_key.txt), or as a function
argument. Keys are free: https://api.census.gov/data/key_signup.html
"""

from __future__ import annotations

import io
import gzip
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import requests

from .cache import cache_get_json, cache_put_json, cache_get_path, cache_put_bytes
from .config import (
    B15003_CROSSWALK,
    B15003_VARIABLES,
    EDUCATION_BIN_ORDER,
    LODES_WAC_INDUSTRY_COLS,
    LODES_WAC_TOTAL_COL,
)
from .fips import (
    get_state_abbr,
    get_states_for_tracts,
    group_tracts_by_state_county,
    parse_tract_fips,
    block_to_tract,
)

logger = logging.getLogger(__name__)

# LODES OD files can be hundreds of megabytes per state. We read them in
# chunks of 100k rows to avoid loading the entire file into memory at once.
# This is the default chunk size for pandas chunked reading (DP-5).
OD_CHUNK_SIZE = 100_000


# ============================================================
# Census API key management (DA-1)
#
# Three-tier lookup: explicit argument > env var > config file.
# This is intentionally kept as-is for flexibility across
# different deployment environments (local dev, CI, HPC).
# ============================================================

def get_census_api_key(api_key: Optional[str] = None) -> str:
    """Retrieve Census API key from argument, environment, or config file.

    Priority: explicit argument > CENSUS_API_KEY env var > config file.

    Raises:
        RuntimeError: If no API key is available.
    """
    if api_key:
        return api_key
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        return key
    config_path = Path(__file__).parent / "config" / "api_key.txt"
    if config_path.exists():
        return config_path.read_text().strip()
    raise RuntimeError(
        "No Census API key configured. Set CENSUS_API_KEY environment "
        "variable, place your key in wfh_perturbation/config/api_key.txt, "
        "or pass api_key= to the function. "
        "Free keys: https://api.census.gov/data/key_signup.html"
    )


# ============================================================
# DA-1: Education data from Census API (ACS B15003)
# ============================================================

def fetch_education_data(
    tract_fips: List[str],
    year: int = 2024,
    api_key: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> Dict[str, np.ndarray]:
    """Fetch ACS B15003 educational attainment and collapse to 5 bins (DP-1).

    The Census ACS table B15003 reports educational attainment for the
    population 25 years and over. It has 25 detailed categories (from
    "no schooling completed" through "doctorate degree"). We collapse
    those 25 categories into 5 bins that match the WFH parameter vectors:
      0 = Less than high school (B15003_002E through _016E)
      1 = High school diploma/GED (_017E, _018E)
      2 = Some college or associate's degree (_019E through _021E)
      3 = Bachelor's degree (_022E)
      4 = Advanced degree (master's, professional, doctorate; _023E through _025E)

    This 25-to-5 collapse is defined in config.B15003_CROSSWALK.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        year: ACS 5-Year vintage (e.g., 2024).
        api_key: Census API key. If None, reads from config.
        cache_dir: Optional cache directory path.

    Returns:
        Dict mapping tract FIPS -> np.ndarray(5,) of education shares.
    """
    key = get_census_api_key(api_key)
    tract_set = set(tract_fips)
    result: Dict[str, np.ndarray] = {}

    # Request all 26 B15003 variables (1 total + 25 detail lines) in one call
    variables = ",".join(B15003_VARIABLES)

    # Group tracts by (state, county) for efficient batching. The Census API
    # returns all tracts in a county in one response, so we batch by county.
    groups = group_tracts_by_state_county(tract_fips)

    for (state_fips, county_fips), group_tracts in groups.items():
        cache_key = f"acs_b15003_{year}_{state_fips}_{county_fips}"

        # Check if we already have this county's data cached
        cached = cache_get_json(cache_key, cache_dir=cache_dir)

        if cached is not None:
            logger.debug(f"Cache hit: {cache_key}")
            raw_data = cached
        else:
            # Query Census API for all tracts in this county
            url = (
                f"https://api.census.gov/data/{year}/acs/acs5"
                f"?get={variables}"
                f"&for=tract:*"
                f"&in=state:{state_fips}&in=county:{county_fips}"
                f"&key={key}"
            )
            logger.info(f"Fetching ACS B15003: state={state_fips}, county={county_fips}")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

            # The Census API sometimes returns HTTP 200 with an HTML error page
            # (e.g., for invalid keys or unavailable vintages) instead of JSON.
            # We check the content type to catch this before json() fails.
            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type and "html" in content_type.lower():
                body_preview = resp.text[:500]
                if "Invalid Key" in body_preview:
                    raise RuntimeError(
                        f"Census API rejected the API key. Verify your key is "
                        f"valid at https://api.census.gov/data/key_signup.html "
                        f"— keys can expire or be deactivated."
                    )
                elif "not available" in body_preview.lower():
                    raise RuntimeError(
                        f"Census API says ACS {year} data is not available. "
                        f"Try an earlier year (e.g., year=2022)."
                    )
                else:
                    raise RuntimeError(
                        f"Census API returned HTML instead of JSON. "
                        f"Response preview: {body_preview}"
                    )

            raw_data = resp.json()
            cache_put_json(cache_key, raw_data, cache_dir=cache_dir)

        # Parse the response. Census API returns a list of lists where the
        # first row is column headers and subsequent rows are data.
        headers = raw_data[0]
        for row in raw_data[1:]:
            row_dict = dict(zip(headers, row))
            tract_code = row_dict["tract"]
            full_fips = f"{state_fips}{county_fips}{tract_code}"

            if full_fips not in tract_set:
                continue

            # Apply the B15003 crosswalk: sum the raw counts for each bin,
            # then divide by the total to get shares.
            total = float(row_dict.get("B15003_001E", 0))
            if total == 0:
                result[full_fips] = np.zeros(5)
                continue

            shares = np.zeros(5)
            for bin_idx, bin_name in enumerate(EDUCATION_BIN_ORDER):
                bin_vars = B15003_CROSSWALK[bin_name]
                bin_total = sum(float(row_dict.get(v, 0)) for v in bin_vars)
                shares[bin_idx] = bin_total / total

            result[full_fips] = shares

    # Warn about any tracts we couldn't find in the API response.
    missing = tract_set - set(result.keys())
    if missing:
        logger.warning(f"No ACS data found for tracts: {missing}")

    return result


# ============================================================
# DA-2: LODES WAC industry data
# ============================================================

def _download_lodes_file(
    state_abbr: str,
    file_type: str,
    year: int,
    cache_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Download and cache a LODES file (WAC or OD).

    LODES files are gzipped CSVs hosted at lehd.ces.census.gov. WAC files
    are typically 10-50 MB; OD files can be 100-500 MB per state.

    Args:
        state_abbr: Lowercase state abbreviation (e.g., 'ny').
        file_type: 'wac' or 'od'.
        year: LODES vintage year.
        cache_dir: Optional cache directory path.

    Returns:
        pandas DataFrame of the file contents.
    """
    if file_type == "wac":
        url = (
            f"https://lehd.ces.census.gov/data/lodes/LODES8/"
            f"{state_abbr}/wac/{state_abbr}_wac_S000_JT00_{year}.csv.gz"
        )
    elif file_type == "od":
        url = (
            f"https://lehd.ces.census.gov/data/lodes/LODES8/"
            f"{state_abbr}/od/{state_abbr}_od_main_JT00_{year}.csv.gz"
        )
    else:
        raise ValueError(f"Unknown LODES file type: {file_type}")

    cache_key = f"lodes_{file_type}_{state_abbr}_{year}.csv.gz"

    # Check if the file is already cached on disk
    cached_path = cache_get_path(cache_key, cache_dir=cache_dir)
    if cached_path is not None:
        logger.debug(f"Cache hit: {cache_key}")
        return pd.read_csv(cached_path, compression="gzip", dtype=str)

    # Not cached: download the full file
    logger.info(f"Downloading LODES {file_type}: {url}")
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    raw_bytes = resp.content

    # Save to cache for next time
    cache_put_bytes(cache_key, raw_bytes, cache_dir=cache_dir)

    return pd.read_csv(io.BytesIO(raw_bytes), compression="gzip", dtype=str)


def fetch_wac_data(
    tract_fips: List[str],
    year: int = 2023,
    cache_dir: Optional[str] = None,
    return_block_level: bool = False,
) -> Dict[str, np.ndarray]:
    """Fetch LODES WAC data and compute industry shares (DP-2).

    Downloads WAC (Workplace Area Characteristics) files for all states in
    the study area. WAC files report employment counts by industry sector
    at the Census block level. We aggregate blocks up to tracts and compute
    the share of employment in each of the 20 LODES CNS sectors.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        year: LODES vintage year.
        cache_dir: Optional cache directory path.
        return_block_level: If True, also returns block-level total job counts
            (needed for computing H3 allocation weights).

    Returns:
        Dict mapping tract FIPS -> np.ndarray(20,) of industry shares.
        If return_block_level=True, returns (tract_shares, block_jobs) where
        block_jobs maps block_fips -> total_jobs (int).
    """
    tract_set = set(tract_fips)
    states = get_states_for_tracts(tract_fips)

    # Accumulate block-level industry counts by tract
    tract_industry_counts: Dict[str, np.ndarray] = defaultdict(lambda: np.zeros(20))
    block_jobs: Dict[str, int] = {}

    for state_fips in states:
        state_abbr = get_state_abbr(state_fips)
        df = _download_lodes_file(state_abbr, "wac", year, cache_dir)

        # Each row is one Census block. w_geocode is the 15-digit block FIPS.
        for _, row in df.iterrows():
            block_fips = str(row["w_geocode"]).zfill(15)
            tract = block_to_tract(block_fips)
            if tract not in tract_set:
                continue

            # Sum CNS01-CNS20 job counts (20 industry sectors) at the tract level
            cns_values = np.array(
                [float(row.get(col, 0)) for col in LODES_WAC_INDUSTRY_COLS]
            )
            tract_industry_counts[tract] += cns_values

            # Keep block-level totals for H3 allocation weighting
            if return_block_level:
                c000 = float(row.get(LODES_WAC_TOTAL_COL, 0))
                block_jobs[block_fips] = block_jobs.get(block_fips, 0) + int(c000)

    # Convert raw job counts to shares (each tract sums to 1.0)
    tract_shares: Dict[str, np.ndarray] = {}
    for tract, counts in tract_industry_counts.items():
        total = counts.sum()
        if total == 0:
            # DP-3: Tracts with zero employment get a zero vector. This is
            # correct because they contribute nothing to the industry mix.
            tract_shares[tract] = np.zeros(20)
        else:
            tract_shares[tract] = counts / total

    # Fill in missing tracts with zeros (no WAC data found for them)
    for fips in tract_fips:
        if fips not in tract_shares:
            tract_shares[fips] = np.zeros(20)

    if return_block_level:
        return tract_shares, block_jobs
    return tract_shares


# ============================================================
# DA-3, DA-4: LODES OD commute flows
# ============================================================

def fetch_od_data(
    tract_fips: List[str],
    year: int = 2023,
    cache_dir: Optional[str] = None,
) -> Dict[Tuple[str, str], float]:
    """Fetch LODES OD flows and aggregate to tract level (DP-4).

    Downloads OD (Origin-Destination) files for all residence states (DA-4).
    OD files are large (100-500 MB per state), so we read them in chunks
    to avoid loading the entire file into memory (DP-5). Each row in the
    OD file is a block-to-block commute flow; we truncate block FIPS to
    tract FIPS and sum, producing tract-to-tract commute counts.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        year: LODES vintage year.
        cache_dir: Optional cache directory path.

    Returns:
        Dict mapping (residence_tract, workplace_tract) -> commute count.
    """
    tract_set = set(tract_fips)
    states = get_states_for_tracts(tract_fips)

    # Accumulate tract-level flows across all states
    flows: Dict[Tuple[str, str], float] = defaultdict(float)

    for state_fips in states:
        state_abbr = get_state_abbr(state_fips)
        cache_key = f"lodes_od_{state_abbr}_{year}.csv.gz"

        # Check if the raw gzipped file is already cached on disk
        cached_path = cache_get_path(cache_key, cache_dir=cache_dir)

        if cached_path is not None:
            logger.debug(f"Cache hit: {cache_key}")
            source = cached_path
        else:
            url = (
                f"https://lehd.ces.census.gov/data/lodes/LODES8/"
                f"{state_abbr}/od/{state_abbr}_od_main_JT00_{year}.csv.gz"
            )
            logger.info(f"Downloading LODES OD: {url}")
            resp = requests.get(url, timeout=600, stream=True)
            resp.raise_for_status()

            # Save to cache and read from the cached file
            dest = cache_put_bytes(cache_key, resp.content, cache_dir=cache_dir)
            source = dest

        # Read in chunks to keep memory usage bounded. A single state OD
        # file can have tens of millions of rows; loading it all at once
        # would use several GB of RAM.
        logger.info(f"Processing OD file for state {state_abbr} in chunks...")
        reader = pd.read_csv(
            source,
            compression="gzip",
            dtype=str,
            usecols=["w_geocode", "h_geocode", "S000"],
            chunksize=OD_CHUNK_SIZE,
        )

        for chunk in reader:
            # Truncate 15-digit block FIPS to 11-digit tract FIPS (DP-4)
            chunk["res_tract"] = chunk["w_geocode"].str[:11]
            chunk["work_tract"] = chunk["h_geocode"].str[:11]

            # Keep only rows where both residence and workplace tracts are
            # in our study area
            mask = (
                chunk["res_tract"].isin(tract_set)
                & chunk["work_tract"].isin(tract_set)
            )
            filtered = chunk[mask]

            if filtered.empty:
                continue

            # Aggregate block-level flows up to tract pairs
            for _, row in filtered.iterrows():
                pair = (row["res_tract"], row["work_tract"])
                flows[pair] += float(row["S000"])

    return dict(flows)


# ============================================================
# Block population from Census Decennial API
# ============================================================

def fetch_block_population(
    tract_fips: List[str],
    year: int = 2020,
    api_key: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> Dict[str, int]:
    """Fetch block-level population from the decennial census.

    We need block-level population to compute allocation weights for
    distributing tract-level education data across H3 hexes. A tract
    may overlap several hexes, and the population in each block tells
    us how to split the tract's education profile across those hexes.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        year: Decennial census year (2020 or 2010).
        api_key: Census API key.
        cache_dir: Optional cache directory path.

    Returns:
        Dict mapping 15-digit block FIPS -> population count (int).
    """
    key = get_census_api_key(api_key)
    block_pop: Dict[str, int] = {}

    groups = group_tracts_by_state_county(tract_fips)
    tract_set = set(tract_fips)

    for (state_fips, county_fips), group_tracts in groups.items():
        # The Census API requires county-level queries for block data.
        # We fetch all blocks in the county and then filter to our tracts.
        cache_key = f"decennial_blocks_{year}_{state_fips}_{county_fips}"
        cached = cache_get_json(cache_key, cache_dir=cache_dir)

        if cached is not None:
            logger.debug(f"Cache hit: {cache_key}")
            raw_data = cached
        else:
            # Use the DHC (Demographic and Housing Characteristics) dataset
            url = (
                f"https://api.census.gov/data/{year}/dec/dhc"
                f"?get=P1_001N"
                f"&for=block:*"
                f"&in=state:{state_fips}&in=county:{county_fips}"
                f"&key={key}"
            )
            logger.info(f"Fetching block population: state={state_fips}, county={county_fips}")
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            raw_data = resp.json()

            cache_put_json(cache_key, raw_data, cache_dir=cache_dir)

        # Parse response: first row is headers, rest is data
        headers = raw_data[0]
        for row in raw_data[1:]:
            row_dict = dict(zip(headers, row))
            tract_code = row_dict["tract"]
            block_code = row_dict["block"]
            full_tract = f"{state_fips}{county_fips}{tract_code}"

            if full_tract not in tract_set:
                continue

            full_block = f"{state_fips}{county_fips}{tract_code}{block_code}"
            pop = int(float(row_dict.get("P1_001N", 0)))
            block_pop[full_block] = pop

    return block_pop


# ============================================================
# Convenience: fetch all study-area data at once
# ============================================================

def fetch_study_area_data(
    tract_fips: List[str],
    api_key: Optional[str] = None,
    acs_year: int = 2024,
    lodes_year: int = 2023,
    cache_dir: Optional[str] = None,
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[Tuple[str, str], float]]:
    """Fetch all demographic and commute data for a set of tracts.

    Convenience function that calls fetch_education_data, fetch_wac_data,
    and fetch_od_data in sequence, sharing the same cache directory.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        api_key: Census API key.
        acs_year: ACS 5-Year vintage.
        lodes_year: LODES vintage year.
        cache_dir: Optional cache directory path.

    Returns:
        Tuple of (edu_shares, ind_shares, commute_weights).
    """
    edu = fetch_education_data(tract_fips, acs_year, api_key, cache_dir)
    ind = fetch_wac_data(tract_fips, lodes_year, cache_dir)
    commute = fetch_od_data(tract_fips, lodes_year, cache_dir)
    return edu, ind, commute


# ============================================================
# DA-7: Metadata record
# ============================================================

def create_metadata_record(
    acs_year: int = 2024,
    lodes_year: int = 2023,
    params_source: str = "built-in defaults",
) -> Dict:
    """Create a metadata record for reproducibility (DA-7)."""
    return {
        "acs_vintage": f"ACS 5-Year {acs_year}",
        "acs_table": "B15003",
        "lodes_vintage": f"LODES 8, year {lodes_year}",
        "lodes_wac": "S000, JT00",
        "lodes_od": "Main, S000, JT00",
        "parameter_source": params_source,
        "education_wfh_source": "CPS Q1 2024",
        "industry_wfh_source": "CPS August 2024",
        "upper_bound_source": "Dingel-Neiman 2020",
    }
