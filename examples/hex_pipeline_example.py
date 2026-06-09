"""Example: hex-native WFH perturbation pipeline.

This script demonstrates the recommended workflow for integrating the WFH
perturbation module with the uTECH Deep Gravity pipeline. It:

1. Converts tract-level Census demographics to H3 hex-level data
2. Creates synthetic hex-level baseline flows (replace with Deep Gravity output)
3. Sweeps alpha — the uniform-shock pattern for cross-city scenario analysis —
   using the closed-form model for free aggregate response curves
4. Solves for a single target X value (aggregate percent change in trips)
5. Sweeps X for even resolution in outcome space (the visualizer's pattern)
6. Inspects per-pair results

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

    # Build the closed-form aggregate model once for this study area. It's a
    # single pass over the flows, and every pattern below reuses it.
    sd = SpatialData(
        edu_shares=hex_edu, ind_shares=hex_ind, commute_weights=hex_commute
    )
    model = build_aggregate_model(load_default_params(), sd, baseline_flows)

    # --- Step 3: Alpha sweep (uniform shock; primary cross-city pattern) ---
    # To model a nationwide exogenous shock or uniform policy, apply the SAME
    # alpha grid to every city and compare outcomes. X_of_alpha evaluates the
    # aggregate response without running the per-pair pipeline, so each city's
    # full response curve is essentially free. Run the expensive pipeline only
    # at the scenario alpha(s) you want flow maps for.
    print("\n--- Alpha sweep (uniform shock across cities) ---")
    alphas = np.linspace(0.0, 1.0, 101)
    X_curve = [model.X_of_alpha(float(a)) for a in alphas]
    for i in (0, 25, 50, 100):
        print(f"  X(alpha={alphas[i]:.2f}) = {X_curve[i]:+.2%}")

    scenario_alpha = 0.25  # e.g., a sustained ~50% fuel-price spike
    result = perturb_flows(
        alpha=scenario_alpha,
        baseline_flows=baseline_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
    print(f"  Pipeline at alpha={scenario_alpha}: "
          f"total trips = {result.total_perturbed_flow:.0f}, "
          f"change = {result.percent_change:+.2%}")
    scenario_result = result  # kept for Step 6

    # --- Step 4: Solve for a single target X ---
    # When the outcome is specified for THIS study area ("model a 10%
    # reduction in trips here"), solve for the alpha that achieves it.
    # Targets outside the feasible range raise InfeasibleTargetError,
    # so check the range first.
    print("\n--- Single X target ---")
    x_min, x_max = model.feasible_X_range()
    print(f"  Feasible aggregate change for this study area: "
          f"{x_min:+.1%} to {x_max:+.1%}")

    alpha = model.solve(-0.10)
    result = perturb_flows(
        alpha=alpha,
        baseline_flows=baseline_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
    print(f"  target=-10%: solved alpha={alpha:.4f}, "
          f"achieved={result.percent_change:+.2%}")

    # solve_and_perturb wraps the same solve + pipeline run in one call:
    result = solve_and_perturb(
        target_percent_change=-0.10,
        baseline_flows=baseline_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
    print(f"  one-call form: solved alpha={result.alpha:.4f}, "
          f"achieved={result.percent_change:+.2%}")

    # --- Step 5: X sweep (even resolution in outcome space) ---
    # Sweep X when the outcome axis is what a human will scan — this is the
    # visualizer's pattern (its slider operates in percent-change space).
    # Note this holds the outcome, not the behavior, constant across runs:
    # appropriate within one city, not for cross-city comparisons (Step 3).
    print("\n--- X sweep (outcome-resolution sampling) ---")
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

    # --- Step 6: Inspect individual hex pairs ---
    print(f"\n--- Sample hex pair details (alpha={scenario_alpha}) ---")
    for pair, P in sorted(scenario_result.P.items(), key=lambda x: x[1])[:5]:
        T = baseline_flows.get(pair, 0)
        G = scenario_result.G.get(pair, 0)
        print(f"  {pair[0][:15]} <-> {pair[1][:15]}: P={P:.4f}, T={T:.0f} -> G={G:.0f}")


if __name__ == "__main__":
    main()
