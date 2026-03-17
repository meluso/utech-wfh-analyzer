#!/usr/bin/env python3
"""Precomputation script for the WFH Perturbation Visualization Tool.

Fetches Census demographics and LODES commute flows for a study area defined
by one or more counties (default: Queens 36081 + Manhattan 36061), converts to
H3 hex level, runs an alpha sweep, and writes the output files needed by the
React frontend. Only flows between tracts within the specified counties are
included.

Output files (in viz_data/):
    hex_geometries.geojson  — H3 hex boundaries for map rendering / QGIS
    hex_metadata.json       — Per-hex demographics (education, industry)
    snapshots.json          — Alpha sweep results (P, G, Omega per pair per alpha)
    pairs_alpha_sweep.csv   — Flat CSV export (one row per pair × alpha)
    hex_summary.csv         — Flat CSV export (one row per hex × alpha)

Usage:
    python scripts/precompute_viz_data.py
    python scripts/precompute_viz_data.py --counties 36081 36061
    python scripts/precompute_viz_data.py --counties 48453 --resolution 7 --alpha-steps 50

Prerequisites:
    pip install -e .
    export CENSUS_API_KEY=your_key
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Ensure the package is importable when running from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wfh_perturbation import (
    load_default_params,
    perturb_flows,
    prepare_hex_data,
    fetch_od_data,
)
from wfh_perturbation.solver import compute_alpha_max
from wfh_perturbation.config import EDUCATION_LABELS, INDUSTRY_LABELS

logger = logging.getLogger(__name__)


# ============================================================
# Step 1: Identify tracts in the study area
# ============================================================

def fetch_county_tracts(
    state_fips: str,
    county_fips: str,
    api_key: str,
    year: int = 2024,
) -> List[str]:
    """Query the Census API for all tract FIPS codes in a county.

    Returns a list of 11-digit FIPS strings (state + county + tract).
    """
    import requests

    url = (
        f"https://api.census.gov/data/{year}/acs/acs5"
        f"?get=NAME"
        f"&for=tract:*"
        f"&in=state:{state_fips}&in=county:{county_fips}"
        f"&key={api_key}"
    )
    logger.info(f"Fetching tract list for state={state_fips}, county={county_fips}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    tracts = []
    headers = data[0]
    for row in data[1:]:
        row_dict = dict(zip(headers, row))
        fips = f"{row_dict['state']}{row_dict['county']}{row_dict['tract']}"
        tracts.append(fips)

    logger.info(f"Found {len(tracts)} tracts in county {state_fips}{county_fips}")
    return tracts


def fetch_multi_county_tracts(
    counties: List[Tuple[str, str]],
    api_key: str,
    year: int = 2024,
) -> List[str]:
    """Fetch all tract FIPS codes for a list of (state_fips, county_fips) pairs.

    The study area is defined explicitly by the counties you pass in.
    No automatic destination discovery is performed.
    """
    all_tracts = []
    for state_fips, county_fips in counties:
        tracts = fetch_county_tracts(state_fips, county_fips, api_key, year)
        all_tracts.extend(tracts)
    return sorted(set(all_tracts))


# ============================================================
# Step 2: H3 hex geometry generation
# ============================================================

def generate_hex_geojson(hex_ids: List[str]) -> dict:
    """Generate a GeoJSON FeatureCollection of H3 hex boundaries."""
    import h3

    features = []
    for hex_id in hex_ids:
        boundary = h3.cell_to_boundary(hex_id)
        # h3 returns (lat, lng) pairs; GeoJSON needs [lng, lat]
        coords = [[lng, lat] for lat, lng in boundary]
        coords.append(coords[0])  # close the ring

        centroid = h3.cell_to_latlng(hex_id)

        features.append({
            "type": "Feature",
            "properties": {
                "hex_id": hex_id,
                "centroid_lat": centroid[0],
                "centroid_lng": centroid[1],
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords],
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ============================================================
# Step 3: Build hex metadata (demographics)
# ============================================================

def build_hex_metadata(
    hex_edu: Dict[str, np.ndarray],
    hex_ind: Dict[str, np.ndarray],
    baseline_flows: Dict[Tuple[str, str], float],
) -> dict:
    """Build per-hex metadata for the inspect panel.

    For each hex, includes education shares, industry shares, the top-4
    industry breakdown (for the 4+1 bar chart), and total baseline flow.
    """
    # Strip the CNS prefix from industry labels for cleaner display
    ind_labels_short = [
        label.split(" ", 1)[1] if " " in label else label
        for label in INDUSTRY_LABELS
    ]

    # Precompute total inbound and outbound baseline flows per hex
    inbound: Dict[str, float] = {}
    outbound: Dict[str, float] = {}
    for (i, j), T in baseline_flows.items():
        outbound[i] = outbound.get(i, 0.0) + T
        inbound[j] = inbound.get(j, 0.0) + T

    all_hexes = sorted(set(hex_edu.keys()) | set(hex_ind.keys()))
    metadata = {}

    for hex_id in all_hexes:
        edu = hex_edu.get(hex_id, np.zeros(5))
        ind = hex_ind.get(hex_id, np.zeros(20))

        # Top 4 industries by share
        top4_indices = np.argsort(ind)[::-1][:4]
        top4 = []
        top4_share_sum = 0.0
        for idx in top4_indices:
            share = float(ind[idx])
            if share > 0:
                top4.append({
                    "index": int(idx),
                    "label": ind_labels_short[idx],
                    "share": round(share, 4),
                })
                top4_share_sum += share

        other_share = max(0.0, 1.0 - top4_share_sum)

        metadata[hex_id] = {
            "edu_shares": [round(float(x), 6) for x in edu],
            "ind_shares": [round(float(x), 6) for x in ind],
            "ind_top4": top4,
            "ind_other_share": round(other_share, 4),
            "total_inbound_T": round(inbound.get(hex_id, 0.0), 1),
            "total_outbound_T": round(outbound.get(hex_id, 0.0), 1),
        }

    return metadata


# ============================================================
# Step 4: Alpha sweep
# ============================================================

def run_alpha_sweep(
    alpha_values: np.ndarray,
    baseline_flows: Dict[Tuple[str, str], float],
    hex_edu: Dict[str, np.ndarray],
    hex_ind: Dict[str, np.ndarray],
    hex_commute: Dict[Tuple[str, str], float],
) -> dict:
    """Run perturbation at each alpha value and collect results.

    Returns a snapshots dict structured for the frontend JSON file.
    """
    params = load_default_params()

    # Establish a stable ordering of pairs
    pair_keys = sorted(baseline_flows.keys())
    pair_index = {pair: idx for idx, pair in enumerate(pair_keys)}
    n_pairs = len(pair_keys)

    # Baseline flows and commute weights (constant across alpha)
    T_values = [baseline_flows[pair] for pair in pair_keys]
    L_ij_values = [hex_commute.get(pair, 0.0) for pair in pair_keys]
    L_ji_values = [hex_commute.get((pair[1], pair[0]), 0.0) for pair in pair_keys]

    snapshots = []
    total_T = sum(T_values)

    for idx, alpha in enumerate(alpha_values):
        alpha_float = float(alpha)

        if idx % 10 == 0:
            logger.info(f"  Alpha sweep: {idx}/{len(alpha_values)} (alpha={alpha_float:.3f})")

        result = perturb_flows(
            alpha=alpha_float,
            baseline_flows=baseline_flows,
            edu_shares=hex_edu,
            ind_shares=hex_ind,
            commute_weights=hex_commute,
            params=params,
        )

        # Per-pair arrays (parallel to pair_keys)
        P_arr = []
        G_arr = []
        omega_ij_arr = []
        omega_ji_arr = []

        for pair in pair_keys:
            i, j = pair
            P_arr.append(round(result.P.get(pair, 1.0), 6))
            G_arr.append(round(result.G.get(pair, baseline_flows[pair]), 2))
            omega_ij_arr.append(round(result.omega.get((i, j), 1.0), 6))
            omega_ji_arr.append(round(result.omega.get((j, i), 1.0), 6))

        total_G = sum(G_arr)
        pct_change = (total_G - total_T) / total_T if total_T > 0 else 0.0

        # Per-hex net change (% change in total flow touching each hex)
        hex_inbound_T: Dict[str, float] = {}
        hex_outbound_T: Dict[str, float] = {}
        hex_inbound_G: Dict[str, float] = {}
        hex_outbound_G: Dict[str, float] = {}

        for k, pair in enumerate(pair_keys):
            i, j = pair
            t = T_values[k]
            g = G_arr[k]
            hex_outbound_T[i] = hex_outbound_T.get(i, 0.0) + t
            hex_inbound_T[j] = hex_inbound_T.get(j, 0.0) + t
            hex_outbound_G[i] = hex_outbound_G.get(i, 0.0) + g
            hex_inbound_G[j] = hex_inbound_G.get(j, 0.0) + g

        all_hexes = set(hex_inbound_T.keys()) | set(hex_outbound_T.keys())
        hex_net_change = {}
        hex_abs_change = {}
        for h in all_hexes:
            total_t = hex_inbound_T.get(h, 0.0) + hex_outbound_T.get(h, 0.0)
            total_g = hex_inbound_G.get(h, 0.0) + hex_outbound_G.get(h, 0.0)
            # Absolute change in trips (signed: negative = fewer trips)
            hex_abs_change[h] = round(total_g - total_t, 1)
            if total_t > 0:
                hex_net_change[h] = round((total_g - total_t) / total_t, 6)
            else:
                hex_net_change[h] = 0.0

        snapshots.append({
            "alpha": round(alpha_float, 6),
            "total_T": round(total_T, 1),
            "total_G": round(total_G, 1),
            "percent_change": round(pct_change, 6),
            "P": P_arr,
            "G": G_arr,
            "Omega_ij": omega_ij_arr,
            "Omega_ji": omega_ji_arr,
            "hex_net_change": hex_net_change,
            "hex_abs_change": hex_abs_change,
        })

    return {
        "alpha_values": [round(float(a), 6) for a in alpha_values],
        "pair_keys": [[pair[0], pair[1]] for pair in pair_keys],
        "L_ij": [round(v, 2) for v in L_ij_values],
        "L_ji": [round(v, 2) for v in L_ji_values],
        "T": [round(v, 2) for v in T_values],
        "snapshots": snapshots,
    }


# ============================================================
# Step 5: Write CSV exports
# ============================================================

def write_pairs_csv(
    snapshots_data: dict,
    output_path: Path,
) -> None:
    """Write pairs_alpha_sweep.csv — one row per (pair, alpha)."""
    pair_keys = snapshots_data["pair_keys"]
    L_ij = snapshots_data["L_ij"]
    L_ji = snapshots_data["L_ji"]
    T = snapshots_data["T"]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "origin_hex", "destination_hex", "alpha",
            "T_ij", "P_ij", "G_ij", "Omega_ij", "Omega_ji",
            "L_ij", "L_ji",
        ])

        for snap in snapshots_data["snapshots"]:
            alpha = snap["alpha"]
            for k, (origin, dest) in enumerate(pair_keys):
                writer.writerow([
                    origin, dest, alpha,
                    T[k], snap["P"][k], snap["G"][k],
                    snap["Omega_ij"][k], snap["Omega_ji"][k],
                    L_ij[k], L_ji[k],
                ])


def write_hex_summary_csv(
    snapshots_data: dict,
    hex_metadata: dict,
    output_path: Path,
) -> None:
    """Write hex_summary.csv — one row per (hex, alpha)."""
    pair_keys = snapshots_data["pair_keys"]
    T = snapshots_data["T"]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "hex_id", "alpha",
            "total_inbound_T", "total_inbound_G",
            "total_outbound_T", "total_outbound_G",
            "pct_change_inbound", "pct_change_outbound",
            "edu_top_bin", "ind_top_sector",
        ])

        edu_labels = ["Less than HS", "HS Diploma", "Some College", "Bachelor's", "Advanced"]

        for snap in snapshots_data["snapshots"]:
            alpha = snap["alpha"]

            # Accumulate per-hex flows for this snapshot
            inbound_T: Dict[str, float] = {}
            outbound_T: Dict[str, float] = {}
            inbound_G: Dict[str, float] = {}
            outbound_G: Dict[str, float] = {}

            for k, (origin, dest) in enumerate(pair_keys):
                t = T[k]
                g = snap["G"][k]
                outbound_T[origin] = outbound_T.get(origin, 0.0) + t
                inbound_T[dest] = inbound_T.get(dest, 0.0) + t
                outbound_G[origin] = outbound_G.get(origin, 0.0) + g
                inbound_G[dest] = inbound_G.get(dest, 0.0) + g

            all_hexes = sorted(set(inbound_T.keys()) | set(outbound_T.keys()))

            for h in all_hexes:
                in_t = inbound_T.get(h, 0.0)
                in_g = inbound_G.get(h, 0.0)
                out_t = outbound_T.get(h, 0.0)
                out_g = outbound_G.get(h, 0.0)

                pct_in = (in_g - in_t) / in_t if in_t > 0 else 0.0
                pct_out = (out_g - out_t) / out_t if out_t > 0 else 0.0

                # Top education bin and industry sector from metadata
                meta = hex_metadata.get(h, {})
                edu_shares = meta.get("edu_shares", [0] * 5)
                top_edu = edu_labels[int(np.argmax(edu_shares))] if any(s > 0 for s in edu_shares) else "N/A"
                ind_top4 = meta.get("ind_top4", [])
                top_ind = ind_top4[0]["label"] if ind_top4 else "N/A"

                writer.writerow([
                    h, alpha,
                    round(in_t, 1), round(in_g, 1),
                    round(out_t, 1), round(out_g, 1),
                    round(pct_in, 6), round(pct_out, 6),
                    top_edu, top_ind,
                ])


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Precompute visualization data for the WFH Perturbation Tool."
    )
    parser.add_argument(
        "--counties", nargs="+", default=["36081", "36061"],
        help=(
            "5-digit state+county FIPS codes defining the study area. "
            "Default: 36081 (Queens) and 36061 (Manhattan). "
            "Only flows between tracts in these counties are included."
        ),
    )
    parser.add_argument(
        "--resolution", type=int, default=7,
        help="H3 resolution (default: 7, ~5 km hexes)",
    )
    parser.add_argument(
        "--alpha-steps", type=int, default=100,
        help="Number of alpha values in the sweep (default: 100)",
    )
    parser.add_argument(
        "--output-dir", default="viz_data",
        help="Output directory for precomputed files (default: viz_data/)",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help="Cache directory (default: ~/.wfh_perturbation_cache)",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Census API key (or set CENSUS_API_KEY env var)",
    )
    parser.add_argument(
        "--lodes-year", type=int, default=2023,
        help="LODES vintage year (default: 2023)",
    )
    parser.add_argument(
        "--acs-year", type=int, default=2024,
        help="ACS 5-Year vintage (default: 2024)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    t_start = time.time()

    # Resolve API key
    from wfh_perturbation import get_census_api_key
    api_key = get_census_api_key(args.api_key)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: Identify tracts ----
    logger.info("=" * 60)
    logger.info("Step 1: Identifying tracts in the study area")
    logger.info("=" * 60)

    # Parse county FIPS codes (5-digit: 2 state + 3 county)
    counties = []
    for code in args.counties:
        if len(code) != 5:
            parser.error(f"County FIPS must be 5 digits (state+county), got: {code}")
        counties.append((code[:2], code[2:]))

    county_labels = ", ".join(args.counties)
    logger.info(f"Study area counties: {county_labels}")

    all_tracts = fetch_multi_county_tracts(
        counties, api_key, year=args.acs_year
    )

    # ---- Step 2: Prepare hex-level data ----
    logger.info("=" * 60)
    logger.info("Step 2: Preparing hex-level demographic data")
    logger.info("=" * 60)

    hex_edu, hex_ind, hex_commute = prepare_hex_data(
        all_tracts,
        resolution=args.resolution,
        api_key=api_key,
        acs_year=args.acs_year,
        lodes_year=args.lodes_year,
        cache_dir=args.cache_dir,
    )

    logger.info(
        f"Hex data ready: {len(hex_edu)} edu hexes, "
        f"{len(hex_ind)} ind hexes, {len(hex_commute)} commute pairs"
    )

    # ---- Step 3: Build baseline flows ----
    # Use LODES OD counts as proxy T_ij (spec Section 4.1, step 4)
    logger.info("=" * 60)
    logger.info("Step 3: Building baseline flows from LODES OD data")
    logger.info("=" * 60)

    # The hex_commute dict contains LODES-derived commute weights at hex level.
    # We use these as proxy baseline flows. The spec notes that P_ij values are
    # independent of flow magnitude, so the relative pattern is correct even if
    # absolute numbers are approximate.
    baseline_flows = {}
    for pair, weight in hex_commute.items():
        if weight > 0:
            baseline_flows[pair] = weight

    total_baseline = sum(baseline_flows.values())
    logger.info(
        f"Baseline flows: {len(baseline_flows)} pairs, "
        f"total = {total_baseline:.0f} (LODES proxy)"
    )

    # ---- Step 4: Generate hex geometries ----
    logger.info("=" * 60)
    logger.info("Step 4: Generating hex geometries")
    logger.info("=" * 60)

    all_hex_ids = sorted(
        set(hex_edu.keys()) | set(hex_ind.keys())
        | {pair[0] for pair in baseline_flows}
        | {pair[1] for pair in baseline_flows}
    )
    geojson = generate_hex_geojson(all_hex_ids)

    geojson_path = output_dir / "hex_geometries.geojson"
    with open(geojson_path, "w") as f:
        json.dump(geojson, f)
    logger.info(f"Wrote {geojson_path} ({len(all_hex_ids)} hexes, {geojson_path.stat().st_size / 1e6:.1f} MB)")

    # ---- Step 5: Build hex metadata ----
    logger.info("=" * 60)
    logger.info("Step 5: Building hex metadata")
    logger.info("=" * 60)

    hex_metadata = build_hex_metadata(hex_edu, hex_ind, baseline_flows)

    metadata_path = output_dir / "hex_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(hex_metadata, f)
    logger.info(f"Wrote {metadata_path} ({len(hex_metadata)} hexes, {metadata_path.stat().st_size / 1e6:.1f} MB)")

    # ---- Step 6: Alpha sweep ----
    logger.info("=" * 60)
    logger.info("Step 6: Running alpha sweep")
    logger.info("=" * 60)

    params = load_default_params()
    alpha_max = compute_alpha_max(params)
    alpha_values = np.linspace(-1.0, alpha_max, args.alpha_steps)
    logger.info(
        f"Alpha range: -1.0 to {alpha_max:.4f} "
        f"({args.alpha_steps} steps, step size = {(alpha_max + 1.0) / args.alpha_steps:.4f})"
    )

    t_sweep_start = time.time()
    snapshots_data = run_alpha_sweep(
        alpha_values, baseline_flows, hex_edu, hex_ind, hex_commute
    )
    t_sweep = time.time() - t_sweep_start
    logger.info(f"Alpha sweep completed in {t_sweep:.1f}s")

    snapshots_path = output_dir / "snapshots.json"
    with open(snapshots_path, "w") as f:
        json.dump(snapshots_data, f)
    logger.info(f"Wrote {snapshots_path} ({snapshots_path.stat().st_size / 1e6:.1f} MB)")

    # ---- Step 7: Write CSV exports ----
    logger.info("=" * 60)
    logger.info("Step 7: Writing CSV exports")
    logger.info("=" * 60)

    pairs_csv_path = output_dir / "pairs_alpha_sweep.csv"
    write_pairs_csv(snapshots_data, pairs_csv_path)
    logger.info(f"Wrote {pairs_csv_path} ({pairs_csv_path.stat().st_size / 1e6:.1f} MB)")

    hex_csv_path = output_dir / "hex_summary.csv"
    write_hex_summary_csv(snapshots_data, hex_metadata, hex_csv_path)
    logger.info(f"Wrote {hex_csv_path} ({hex_csv_path.stat().st_size / 1e6:.1f} MB)")

    # ---- Summary ----
    t_total = time.time() - t_start
    logger.info("=" * 60)
    logger.info("DONE — Precomputation summary")
    logger.info("=" * 60)
    logger.info(f"  Study area:     counties={county_labels}")
    logger.info(f"  Total tracts:   {len(all_tracts)}")
    logger.info(f"  H3 resolution:  {args.resolution}")
    logger.info(f"  Total hexes:    {len(all_hex_ids)}")
    logger.info(f"  OD pairs:       {len(baseline_flows)}")
    logger.info(f"  Alpha steps:    {args.alpha_steps}")
    logger.info(f"  Alpha range:    -1.0 to {alpha_max:.4f}")
    logger.info(f"  Output files:")
    for path in [geojson_path, metadata_path, snapshots_path, pairs_csv_path, hex_csv_path]:
        size_mb = path.stat().st_size / 1e6
        logger.info(f"    {path.name:30s} {size_mb:8.2f} MB")
    logger.info(f"  Total runtime:  {t_total:.1f}s")


if __name__ == "__main__":
    main()
