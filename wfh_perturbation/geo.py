"""Geographic utilities for tract boundaries, block centroids, and H3 operations.

Downloads TIGER/Line shapefiles for tract boundaries and block geometries,
computes block centroids, and provides H3 hex operations for the spatial
conversion layer.

Dependencies: geopandas, shapely, h3
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from .cache import cache_get_path, cache_put_path
from .fips import get_states_for_tracts, parse_tract_fips, block_to_tract

logger = logging.getLogger(__name__)


def _require_geopandas():
    """Lazy import geopandas with helpful error message."""
    try:
        import geopandas as gpd
        return gpd
    except ImportError:
        raise ImportError(
            "geopandas is required for H3 spatial conversion. "
            "Install it with: pip install geopandas"
        )


def _require_h3():
    """Lazy import h3 with helpful error message."""
    try:
        import h3
        return h3
    except ImportError:
        raise ImportError(
            "h3 is required for H3 spatial conversion. "
            "Install it with: pip install h3"
        )


# ============================================================
# TIGER/Line shapefile downloads
# ============================================================

def fetch_tract_geometries(
    tract_fips: List[str],
    tiger_year: int = 2024,
    cache_dir: Optional[str] = None,
) -> Dict[str, "shapely.geometry.Polygon"]:
    """Download TIGER tract boundaries and return geometries for study-area tracts.

    Downloads state-level tract shapefiles from the Census TIGER/Line FTP.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        tiger_year: TIGER/Line vintage year.
        cache_dir: Optional cache directory path.

    Returns:
        Dict mapping tract FIPS -> shapely Polygon geometry (in WGS84).
    """
    gpd = _require_geopandas()
    tract_set = set(tract_fips)
    states = get_states_for_tracts(tract_fips)
    geometries: Dict[str, object] = {}

    for state_fips in states:
        cache_key = f"tiger_tract_{tiger_year}_{state_fips}"
        cached_path = cache_get_path(cache_key, suffix=".gpkg", cache_dir=cache_dir)

        if cached_path is not None:
            logger.debug(f"Cache hit: {cache_key}")
            gdf = gpd.read_file(cached_path)
        else:
            url = (
                f"https://www2.census.gov/geo/tiger/TIGER{tiger_year}/"
                f"TRACT/tl_{tiger_year}_{state_fips}_tract.zip"
            )
            logger.info(f"Downloading TIGER tract shapefile: state={state_fips}")
            gdf = gpd.read_file(url)

            # Cache as GeoPackage for faster re-reads
            dest = cache_put_path(cache_key, suffix=".gpkg", cache_dir=cache_dir)
            gdf.to_file(dest, driver="GPKG")

        # Extract geometries for study-area tracts
        geoid_col = "GEOID" if "GEOID" in gdf.columns else "GEOID20"
        for _, row in gdf.iterrows():
            fips = str(row[geoid_col])
            if fips in tract_set:
                geometries[fips] = row.geometry

    missing = tract_set - set(geometries.keys())
    if missing:
        logger.warning(f"No TIGER geometry found for tracts: {missing}")

    return geometries


def fetch_block_centroids(
    tract_fips: List[str],
    tiger_year: int = 2024,
    cache_dir: Optional[str] = None,
) -> Dict[str, Tuple[float, float]]:
    """Download TIGER block shapefiles and return block centroids.

    Downloads state-level block (tabblock20) shapefiles and computes
    the centroid (lat, lon) of each block that falls within the
    study-area tracts.

    Args:
        tract_fips: List of 11-digit tract FIPS GEOIDs.
        tiger_year: TIGER/Line vintage year.
        cache_dir: Optional cache directory path.

    Returns:
        Dict mapping 15-digit block FIPS -> (latitude, longitude).
    """
    gpd = _require_geopandas()
    tract_set = set(tract_fips)
    states = get_states_for_tracts(tract_fips)
    centroids: Dict[str, Tuple[float, float]] = {}

    for state_fips in states:
        cache_key = f"tiger_block_{tiger_year}_{state_fips}"
        cached_path = cache_get_path(cache_key, suffix=".gpkg", cache_dir=cache_dir)

        if cached_path is not None:
            logger.debug(f"Cache hit: {cache_key}")
            gdf = gpd.read_file(cached_path)
        else:
            url = (
                f"https://www2.census.gov/geo/tiger/TIGER{tiger_year}/"
                f"TABBLOCK20/tl_{tiger_year}_{state_fips}_tabblock20.zip"
            )
            logger.info(
                f"Downloading TIGER block shapefile: state={state_fips} "
                f"(this file is large and may take a few minutes)"
            )
            gdf = gpd.read_file(url)

            # Cache as GeoPackage
            dest = cache_put_path(cache_key, suffix=".gpkg", cache_dir=cache_dir)
            gdf.to_file(dest, driver="GPKG")

        # Extract centroids for blocks in study-area tracts
        geoid_col = "GEOID20" if "GEOID20" in gdf.columns else "GEOID"
        for _, row in gdf.iterrows():
            block_fips = str(row[geoid_col])
            tract = block_to_tract(block_fips)
            if tract in tract_set:
                centroid = row.geometry.centroid
                centroids[block_fips] = (centroid.y, centroid.x)  # (lat, lon)

    return centroids


# ============================================================
# H3 hex operations
# ============================================================

def assign_blocks_to_hexes(
    block_centroids: Dict[str, Tuple[float, float]],
    resolution: int = 7,
) -> Dict[str, str]:
    """Assign each block to its containing H3 hex cell.

    Args:
        block_centroids: Dict mapping block FIPS -> (lat, lon).
        resolution: H3 resolution (default 7, ~5 km).

    Returns:
        Dict mapping block FIPS -> H3 hex index string.
    """
    h3 = _require_h3()
    return {
        block_fips: h3.latlng_to_cell(lat, lon, resolution)
        for block_fips, (lat, lon) in block_centroids.items()
    }


def compute_tract_hex_weights(
    block_hex_assignments: Dict[str, str],
    block_values: Dict[str, float],
    tract_fips_list: List[str],
) -> Dict[Tuple[str, str], float]:
    """Compute allocation weights from tracts to hexes based on block-level values.

    Groups blocks by (tract, hex) and sums the block values to produce
    a weight for each (tract, hex) pair. These weights are then normalized
    so they sum to 1.0 for each tract.

    Args:
        block_hex_assignments: Dict mapping block FIPS -> H3 hex index.
        block_values: Dict mapping block FIPS -> numeric value
            (population for education, employment for industry).
        tract_fips_list: List of study-area tract FIPS codes.

    Returns:
        Dict mapping (tract_fips, hex_id) -> normalized weight in [0, 1].
        Weights sum to 1.0 for each tract.
    """
    tract_set = set(tract_fips_list)

    # Accumulate values by (tract, hex)
    tract_hex_sums: Dict[Tuple[str, str], float] = defaultdict(float)
    tract_totals: Dict[str, float] = defaultdict(float)

    for block_fips, hex_id in block_hex_assignments.items():
        tract = block_to_tract(block_fips)
        if tract not in tract_set:
            continue
        val = block_values.get(block_fips, 0.0)
        tract_hex_sums[(tract, hex_id)] += val
        tract_totals[tract] += val

    # Normalize to weights that sum to 1 per tract
    weights: Dict[Tuple[str, str], float] = {}
    for (tract, hex_id), val in tract_hex_sums.items():
        total = tract_totals[tract]
        if total > 0:
            weights[(tract, hex_id)] = val / total
        else:
            # Tract has zero population/employment in all blocks.
            # Fall back to uniform distribution across hexes for this tract.
            pass

    # Handle tracts with zero total by distributing uniformly across hexes
    for tract in tract_fips_list:
        if tract_totals.get(tract, 0) == 0:
            # Find all hexes that contain blocks from this tract
            hex_ids = {
                hex_id for bf, hex_id in block_hex_assignments.items()
                if block_to_tract(bf) == tract
            }
            if hex_ids:
                uniform_w = 1.0 / len(hex_ids)
                for hex_id in hex_ids:
                    weights[(tract, hex_id)] = uniform_w

    return weights


def get_hexes_for_tracts(
    tract_hex_weights: Dict[Tuple[str, str], float],
) -> Set[str]:
    """Extract the set of all H3 hex IDs from tract-hex weight mappings."""
    return {hex_id for (_, hex_id) in tract_hex_weights.keys()}
