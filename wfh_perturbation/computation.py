"""Core perturbation computation layer (Spec Section 4.D: PC-1 through PC-11).

This module implements the geometry-agnostic perturbation math. All inputs
arrive as spatial-unit-indexed data (from the spatial conversion layer).
"""

from __future__ import annotations

from typing import Dict, Set, Tuple
import numpy as np

from .types import (
    PerturbationResult,
    SpatialData,
    SpatialPair,
    SpatialUnitID,
    WFHParams,
)


def compute_joint_propensity(
    w_e: np.ndarray, w_o: np.ndarray
) -> np.ndarray:
    """PC-1: Joint baseline WFH propensity w_eo = 1 - (1 - w_e)(1 - w_o).

    Returns:
        (5, 20) matrix where w_eo[e, o] is the joint propensity for
        education level e and industry sector o.
    """
    # Outer product: (5,1) * (1,20) via broadcasting
    return 1.0 - np.outer(1.0 - w_e, 1.0 - w_o)


def compute_joint_upper_bound(
    u_e: np.ndarray, u_o: np.ndarray
) -> np.ndarray:
    """PC-2: Joint upper bound u_eo = 1 - (1 - u_e)(1 - u_o).

    Returns:
        (5, 20) matrix.
    """
    return 1.0 - np.outer(1.0 - u_e, 1.0 - u_o)


def compute_bounded_deltas(
    alpha: float, w_eo: np.ndarray, u_eo: np.ndarray
) -> np.ndarray:
    """PC-3: Bounded perturbation deltas.

    dw_eo = max(-w_eo, min(alpha * w_eo, u_eo - w_eo))

    Enforces: (a) WFH rates >= 0, (b) proportional to baseline,
    (c) WFH rates <= structural upper bound.

    Returns:
        (5, 20) matrix of deltas.
    """
    return np.maximum(-w_eo, np.minimum(alpha * w_eo, u_eo - w_eo))


def compute_perturbation_weights(
    dw_eo: np.ndarray, w_eo: np.ndarray
) -> np.ndarray:
    """PC-4: Perturbation weights W_eo = 1 - dw_eo / (1 - w_eo).

    For segments where w_eo == 1 (100% baseline WFH), W_eo = 1
    (no perturbation possible since those workers already don't commute).

    Returns:
        (5, 20) matrix.
    """
    denominator = 1.0 - w_eo
    # Guard against division by zero when w_eo == 1
    safe_denom = np.where(denominator == 0, 1.0, denominator)
    W_eo = 1.0 - dw_eo / safe_denom
    # Where w_eo == 1, force W_eo = 1
    W_eo = np.where(denominator == 0, 1.0, W_eo)
    return W_eo


def compute_phi_vectors(
    W_eo: np.ndarray,
    ind_shares: Dict[SpatialUnitID, np.ndarray],
) -> Dict[SpatialUnitID, np.ndarray]:
    """PC-6: Precompute phi_e(s) for every workplace spatial unit s.

    phi_e(s) = sum_o W_eo[e, o] * O_so[o]

    Returns:
        Dict mapping spatial unit id -> np.ndarray(5,) phi vector.
    """
    phi = {}
    for unit_id, O_s in ind_shares.items():
        # W_eo is (5, 20), O_s is (20,) -> result is (5,)
        phi[unit_id] = W_eo @ O_s
    return phi


def compute_omega(
    edu_i: np.ndarray, phi_j: np.ndarray
) -> float:
    """PC-7: Directional aggregate perturbation factor.

    Omega_ij = sum_e E_ie * phi_e(s=j)

    Args:
        edu_i: Education share vector for residence unit i, shape (5,).
        phi_j: Phi vector for workplace unit j, shape (5,).

    Returns:
        Scalar Omega_ij.
    """
    return float(np.dot(edu_i, phi_j))


def compute_symmetric_P(
    omega_ij: float,
    omega_ji: float,
    L_ij: float,
    L_ji: float,
) -> float:
    """PC-8, PC-9: Symmetric perturbation factor.

    P_ij = (L_ij * Omega_ij + L_ji * Omega_ji) / (L_ij + L_ji)

    When L_ij + L_ji == 0 (no observed commute data for this pair),
    falls back to an equal-weight average: P = (Omega_ij + Omega_ji) / 2.

    Args:
        omega_ij: Directional factor, residence=i, workplace=j.
        omega_ji: Directional factor, residence=j, workplace=i.
        L_ij: Commute weight, residence=i, workplace=j.
        L_ji: Commute weight, residence=j, workplace=i.

    Returns:
        Symmetric perturbation factor P_ij.
    """
    L_total = L_ij + L_ji
    if L_total > 0:
        return (L_ij * omega_ij + L_ji * omega_ji) / L_total
    else:
        # Equal-weight fallback when no LODES commute data exists for this pair
        return (omega_ij + omega_ji) / 2.0


def run_perturbation(
    alpha: float,
    params: WFHParams,
    spatial_data: SpatialData,
    baseline_flows: Dict[SpatialPair, float],
) -> PerturbationResult:
    """Run the full perturbation computation pipeline (PC-1 through PC-10).

    This is the main computation entry point. It takes pre-processed spatial
    data and produces perturbed flows.

    Args:
        alpha: Proportional WFH scaling factor.
        params: WFH parameter vectors (w_e, u_e, w_o, u_o).
        spatial_data: Demographic and commute data in target spatial units.
        baseline_flows: Deep Gravity baseline flows T_ij, keyed by (i, j).

    Returns:
        PerturbationResult with all computed values.
    """
    # PC-1: Joint baseline propensity
    w_eo = compute_joint_propensity(params.w_e, params.w_o)

    # PC-2: Joint upper bound
    u_eo = compute_joint_upper_bound(params.u_e, params.u_o)

    # PC-3: Bounded deltas
    dw_eo = compute_bounded_deltas(alpha, w_eo, u_eo)

    # PC-4: Perturbation weights
    W_eo = compute_perturbation_weights(dw_eo, w_eo)

    # PC-6: Precompute phi vectors for all workplace units (PC-11: done once)
    phi = compute_phi_vectors(W_eo, spatial_data.ind_shares)

    # Collect all spatial units that appear in baseline flows
    all_pairs = set(baseline_flows.keys())

    # PC-7, PC-8, PC-9, PC-10: Compute Omega, P, and G for each pair
    omega_dict: Dict[SpatialPair, float] = {}
    P_dict: Dict[SpatialPair, float] = {}
    G_dict: Dict[SpatialPair, float] = {}

    # Process each unique unordered pair once to ensure symmetry
    processed_pairs: Set[Tuple[SpatialUnitID, SpatialUnitID]] = set()

    for (i, j), T_ij in baseline_flows.items():
        canonical = (min(i, j), max(i, j))
        if canonical in processed_pairs:
            # Already computed P for this pair; just compute G
            G_dict[(i, j)] = T_ij * P_dict.get((i, j), P_dict.get((j, i), 1.0))
            continue

        processed_pairs.add(canonical)

        # Get education shares for residence and industry phi for workplace
        edu_i = spatial_data.edu_shares.get(i, np.zeros(5))
        edu_j = spatial_data.edu_shares.get(j, np.zeros(5))
        phi_j = phi.get(j, np.zeros(5))
        phi_i = phi.get(i, np.zeros(5))

        # PC-7: Directional Omega values (PC-5: directionality convention)
        omega_ij = compute_omega(edu_i, phi_j)  # residence=i, workplace=j
        omega_ji = compute_omega(edu_j, phi_i)  # residence=j, workplace=i

        omega_dict[(i, j)] = omega_ij
        omega_dict[(j, i)] = omega_ji

        # Get commute weights
        L_ij = spatial_data.commute_weights.get((i, j), 0.0)
        L_ji = spatial_data.commute_weights.get((j, i), 0.0)

        # PC-8/PC-9: Symmetric P
        P_ij = compute_symmetric_P(omega_ij, omega_ji, L_ij, L_ji)
        P_dict[(i, j)] = P_ij
        P_dict[(j, i)] = P_ij  # Symmetry guaranteed

        # PC-10: Perturbed flow
        G_dict[(i, j)] = T_ij * P_ij
        # Also handle the reverse direction if it appears in baseline_flows
        if (j, i) in baseline_flows:
            G_dict[(j, i)] = baseline_flows[(j, i)] * P_ij

    return PerturbationResult(
        P=P_dict,
        G=G_dict,
        omega=omega_dict,
        phi=phi,
        alpha=alpha,
        W_eo=W_eo,
        w_eo=w_eo,
        u_eo=u_eo,
        metadata={
            "fallback_policy": "equal_weight",
            "num_pairs": len(baseline_flows),
            "num_spatial_units_edu": len(spatial_data.edu_shares),
            "num_spatial_units_ind": len(spatial_data.ind_shares),
        },
    )
