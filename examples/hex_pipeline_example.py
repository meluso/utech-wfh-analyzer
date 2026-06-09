"""Example: hex-native WFH perturbation pipeline.

This script demonstrates the recommended workflow for integrating the WFH
perturbation module with the uTECH Deep Gravity pipeline. It:

1. Converts tract-level Census demographics to H3 hex-level data
2. Creates synthetic hex-level baseline flows (replace with Deep Gravity output)
3. Queries the study area's feasible range and sweeps target X values
   (aggregate percent change in trips) within it — the primary workflow
4. Runs the perturbation directly at a chosen alpha and inspects results

Prerequisites:
    pip install -e .
    export CENSUS_API_KEY=your_key

Usage:
    python examples/hex_pipeline_example.py
"""

import os
import sys

# Ensure the package is importable when running from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from wfh_perturbation import (
    SpatialData,
    build_aggregate_model,
    load_default_params,
    perturb_flows,
    prepare_hex_data,
    solve_and_perturb,
)


def main():
    # --- Configuration ---
    # These tracts define the study area. In production, you'd pass all
    # tracts that overlap your hex grid.
    study_area_tracts = [
        "48453001101",  # Austin TX - downtown area
        "48453002422",  # Austin TX - east side
    ]
    resolution = 7  # H3 resolution (~5 km hexes)

    # Use a persistent cache directory so repeat runs don't re-download data
    cache_dir = "/tmp/wfh_perturbation_cache"

    # --- Step 1: Prepare hex-level demographic data ---
    # This is a one-time preprocessing step. It fetches ACS education data,
    # LODES industry/commute data, TIGER block shapefiles, and converts
    # everything from tract level to H3 hex level.
    print("Preparing hex-level demographic data...")
    hex_edu, hex_ind, hex_commute = prepare_hex_data(
        study_area_tracts,
        resolution=resolution,
        cache_dir=cache_dir,
    )

    print(f"  Education data for {len(hex_edu)} hexes")
    print(f"  Industry data for {len(hex_ind)} hexes")
    print(f"  Commute weights for {len(hex_commute)} hex pairs")

    # --- Step 2: Load baseline flows ---
    # In production, these come from your Deep Gravity model.
    # Here we create synthetic flows from the commute weight pattern.
    print("\nCreating synthetic baseline flows (replace with Deep Gravity output)...")
    baseline_flows = {}
    for (h_a, h_b), weight in hex_commute.items():
        baseline_flows[(h_a, h_b)] = weight * 10.0  # Scale up for illustration

    total_baseline = sum(baseline_flows.values())
    print(f"  {len(baseline_flows)} hex flow pairs, total = {total_baseline:.0f} trips")

    # --- Step 3: Sweep target X values (primary workflow) ---
    # Each study area has its own feasible range of aggregate change, fixed
    # by its labor mix and baseline WFH rates. Query it first so every target
    # in the sweep is solvable for THIS study area; a target outside the
    # range would raise InfeasibleTargetError. Building the model is one pass
    # over the flows, and model.solve() is pure arithmetic afterward, so the
    # expensive pipeline runs once per target and nothing more.
    print("\n--- Target-based mode (X sweep) ---")
    sd = SpatialData(
        edu_shares=hex_edu, ind_shares=hex_ind, commute_weights=hex_commute
    )
    model = build_aggregate_model(load_default_params(), sd, baseline_flows)
    x_min, x_max = model.feasible_X_range()
    print(f"  Feasible aggregate change for this study area: "
          f"{x_min:+.1%} to {x_max:+.1%}")

    for target in np.linspace(x_min * 0.95, x_max * 0.95, 5):
        alpha = model.solve(float(target))
        result = perturb_flows(
            alpha=alpha,
            baseline_flows=baseline_flows,
            edu_shares=hex_edu,
            ind_shares=hex_ind,
            commute_weights=hex_commute,
        )
        print(f"  target={target:+.1%}: solved alpha={alpha:.4f}, "
              f"achieved={result.percent_change:+.2%}")

    # For a single one-off target, solve_and_perturb does the same in one call:
    result = solve_and_perturb(
        target_percent_change=-0.10,
        baseline_flows=baseline_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
    print(f"  one-off target=-10%: solved alpha={result.alpha:.4f}, "
          f"achieved={result.percent_change:+.2%}")

    # --- Step 4: Perturb directly at a chosen alpha ---
    # Use this mode when alpha itself is the scenario parameter.
    print("\n--- Direct alpha mode ---")
    result = perturb_flows(
        alpha=0.25,
        baseline_flows=baseline_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
    print(f"  alpha=0.25: total trips = {result.total_perturbed_flow:.0f}, "
          f"change = {result.percent_change:+.2%}")

    # --- Step 5: Inspect individual hex pairs ---
    print("\n--- Sample hex pair details (alpha=0.25) ---")
    for pair, P in sorted(result.P.items(), key=lambda x: x[1])[:5]:
        T = baseline_flows.get(pair, 0)
        G = result.G.get(pair, 0)
        print(f"  {pair[0][:15]} <-> {pair[1][:15]}: P={P:.4f}, T={T:.0f} -> G={G:.0f}")


if __name__ == "__main__":
    main()
