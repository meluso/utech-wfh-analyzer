"""Spatial conversion layer (Spec Section 4.C: SC-1 through SC-4).

Provides functions for converting tract-level Census demographics to H3
hex-level data, ready for the perturbation engine.

- convert_tract_data_to_hexes (SC-1, SC-2, SC-4): One-time preprocessing
  that converts tract-level Census demographics to H3 hex-level data using
  block-level population and employment weights. The output dicts can be
  fed directly to perturb_flows() alongside hex-level Deep Gravity flows.

- prepare_hex_data: All-in-one convenience that fetches Census data,
  downloads TIGER shapefiles, and returns hex-level edu/ind/commute dicts
  ready for use with perturb_flows().

Typical hex-native workflow:
    hex_edu, hex_ind, hex_commute = prepare_hex_data(tracts, ...)
    result = perturb_flows(alpha, deep_gravity_hex_flows, hex_edu, hex_ind, hex_commute)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from .fips import block_to_tract

logger = logging.getLogger(__name__)


# ============================================================
# SC-1, SC-2, SC-4: Tract-to-hex demographic conversion
# ============================================================

def convert_tract_data_to_hexes(
    edu_shares: Dict[str, np.ndarray],
    ind_shares: Dict[str, np.ndarray],
    commute_weights: Dict[Tuple[str, str], float],
    residential_weights: Dict[Tuple[str, str], float],
    employment_weights: Dict[Tuple[str, str], float],
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[Tuple[str, str], float]]:
    """Convert tract-level demographics to H3 hex-level data.

    This is a one-time preprocessing step. The returned dicts are keyed by
    H3 hex IDs and can be passed directly to perturb_flows() alongside
    hex-level baseline flows from Deep Gravity.

    Education shares are allocated by residential population weights (SC-1).
    Industry shares are allocated by employment weights (SC-2).
    Commute weights are allocated proportionally: residence_weight(i, hex_a) *
    employment_weight(j, hex_b) for each tract pair (i, j) (SC-4).

    Args:
        edu_shares: Tract-level education shares. Maps tract_fips -> ndarray(5,).
        ind_shares: Tract-level industry shares. Maps tract_fips -> ndarray(20,).
        commute_weights: Tract-level LODES commute weights. Maps (tract_i, tract_j) -> float.
        residential_weights: Maps (tract_fips, hex_id) -> weight (sums to 1.0 per tract).
            Based on block-level residential population.
        employment_weights: Maps (tract_fips, hex_id) -> weight (sums to 1.0 per tract).
            Based on block-level employment.

    Returns:
        (hex_edu, hex_ind, hex_commute) tuple:
            hex_edu: Maps hex_id -> ndarray(5,) education shares.
            hex_ind: Maps hex_id -> ndarray(20,) industry shares.
            hex_commute: Maps (hex_a, hex_b) -> float commute weight.
    """
    # --- Step 1: Allocate education shares to hexes (SC-1) ---
    hex_edu_accum: Dict[str, np.ndarray] = defaultdict(lambda: np.zeros(5))

    for (tract, hex_id), w in residential_weights.items():
        if tract in edu_shares and w > 0:
            hex_edu_accum[hex_id] += w * edu_shares[tract]

    hex_edu: Dict[str, np.ndarray] = {}
    for hex_id, accum in hex_edu_accum.items():
        total = accum.sum()
        if total > 0:
            hex_edu[hex_id] = accum / total  # Renormalize to sum to 1
        else:
            hex_edu[hex_id] = np.zeros(5)

    # --- Step 2: Allocate industry shares to hexes (SC-2) ---
    hex_ind_accum: Dict[str, np.ndarray] = defaultdict(lambda: np.zeros(20))

    for (tract, hex_id), w in employment_weights.items():
        if tract in ind_shares and w > 0:
            hex_ind_accum[hex_id] += w * ind_shares[tract]

    hex_ind: Dict[str, np.ndarray] = {}
    for hex_id, accum in hex_ind_accum.items():
        total = accum.sum()
        if total > 0:
            hex_ind[hex_id] = accum / total  # Renormalize to sum to 1
        else:
            hex_ind[hex_id] = np.zeros(20)

    # --- Step 3: Allocate commute weights to hex pairs (SC-4) ---
    # Build lookup tables: tract -> list of (hex_id, weight)
    res_lookup: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    emp_lookup: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    for (tract, hex_id), w in residential_weights.items():
        if w > 0:
            res_lookup[tract].append((hex_id, w))
    for (tract, hex_id), w in employment_weights.items():
        if w > 0:
            emp_lookup[tract].append((hex_id, w))

    hex_commute: Dict[Tuple[str, str], float] = defaultdict(float)

    for (tract_i, tract_j), L_ij in commute_weights.items():
        if L_ij <= 0:
            continue
        res_hexes = res_lookup.get(tract_i, [])
        emp_hexes = emp_lookup.get(tract_j, [])
        if not res_hexes or not emp_hexes:
            continue

        for hex_a, w_a in res_hexes:
            for hex_b, w_b in emp_hexes:
                hex_commute[(hex_a, hex_b)] += L_ij * w_a * w_b

    return hex_edu, hex_ind, dict(hex_commute)


# ============================================================
# All-in-one convenience: fetch + convert to hex level
# ============================================================

def prepare_hex_data(
    tract_fips: List[str],
    resolution: int = 7,
    api_key: Optional[str] = None,
    acs_year: int = 2024,
    lodes_year: int = 2023,
    cache_dir: Optional[str] = None,
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[Tuple[str, str], float]]:
    """Fetch Census data and convert to H3 hex-level demographics.

    This is the recommended all-in-one entry point for hex-native workflows.
    It fetches tract-level education, industry, and commute data from Census
    APIs, downloads TIGER block shapefiles, computes block-to-hex allocation
    weights, and returns hex-level dicts ready for perturb_flows().

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs covering the study area.
        resolution: H3 resolution (default 7, ~5 km hexes).
        api_key: Census API key. If None, reads from env/config.
        acs_year: ACS 5-year vintage for education data (default 2024).
        lodes_year: LODES vintage for industry/commute data (default 2023).
        cache_dir: Optional directory path for caching downloads.

    Returns:
        (hex_edu, hex_ind, hex_commute) tuple:
            hex_edu: Maps hex_id -> ndarray(5,) education shares.
            hex_ind: Maps hex_id -> ndarray(20,) industry shares.
            hex_commute: Maps (hex_a, hex_b) -> float commute weight.
    """
    from .geo import (
        fetch_block_centroids,
        assign_blocks_to_hexes,
        compute_tract_hex_weights,
    )
    from .data_acquisition import (
        fetch_education_data,
        fetch_wac_data,
        fetch_od_data,
        fetch_block_population,
    )

    # --- Fetch tract-level demographic data ---
    logger.info("Fetching tract-level education data (ACS B15003)...")
    tract_edu = fetch_education_data(
        tract_fips, year=acs_year, api_key=api_key, cache_dir=cache_dir
    )

    logger.info("Fetching tract-level industry data (LODES WAC)...")
    tract_ind, block_jobs = fetch_wac_data(
        tract_fips, year=lodes_year, cache_dir=cache_dir, return_block_level=True
    )

    logger.info("Fetching tract-level commute flows (LODES OD)...")
    tract_commute = fetch_od_data(tract_fips, year=lodes_year, cache_dir=cache_dir)

    # --- Build block-to-hex allocation weights ---
    logger.info("Fetching block centroids from TIGER shapefiles...")
    block_centroids = fetch_block_centroids(tract_fips, cache_dir=cache_dir)

    logger.info(f"Assigning {len(block_centroids)} blocks to H3 resolution {resolution}...")
    block_hex = assign_blocks_to_hexes(block_centroids, resolution)

    logger.info("Fetching block population from Census decennial API...")
    block_pop = fetch_block_population(
        tract_fips, api_key=api_key, cache_dir=cache_dir
    )
    block_pop_float = {k: float(v) for k, v in block_pop.items()}
    block_jobs_float = {k: float(v) for k, v in block_jobs.items()}

    logger.info("Computing allocation weights...")
    residential_weights = compute_tract_hex_weights(
        block_hex, block_pop_float, tract_fips
    )
    employment_weights = compute_tract_hex_weights(
        block_hex, block_jobs_float, tract_fips
    )

    n_res_hexes = len(set(h for _, h in residential_weights))
    n_emp_hexes = len(set(h for _, h in employment_weights))
    logger.info(
        f"H3 conversion ready: {n_res_hexes} residential hexes, "
        f"{n_emp_hexes} employment hexes"
    )

    # --- Convert tract data to hex level ---
    return convert_tract_data_to_hexes(
        tract_edu, tract_ind, tract_commute,
        residential_weights, employment_weights,
    )
