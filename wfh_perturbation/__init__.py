"""WFH Perturbation Module — Post-Generation Behavioral Perturbation Framework.

Implements the Work-From-Home perturbation framework for the uTECH-Cities project.
Accepts Deep Gravity baseline flows (keyed by H3 hex pairs) and produces perturbed
flows reflecting a WFH scenario parameterized by a scaling factor alpha.

Primary interface:
    perturb_flows()       — direct alpha mode
    solve_and_perturb()   — target percent-change mode

Hex-native workflow:
    hex_edu, hex_ind, hex_commute = prepare_hex_data(tracts, ...)
    result = perturb_flows(alpha, hex_flows, hex_edu, hex_ind, hex_commute)

See WFH_Perturbation_Module_Specification.md for full requirements.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np

from .types import (
    PerturbationResult,
    SpatialData,
    SpatialPair,
    SpatialUnitID,
    WFHParams,
)
from .computation import (
    compute_joint_propensity,
    compute_joint_upper_bound,
    compute_bounded_deltas,
    compute_perturbation_weights,
    compute_phi_vectors,
    compute_omega,
    compute_symmetric_P,
    run_perturbation,
)
from .spatial import (
    convert_tract_data_to_hexes,
    prepare_hex_data,
)
from .solver import solve_for_alpha, InfeasibleTargetError
from .data_acquisition import (
    create_metadata_record,
    fetch_education_data,
    fetch_wac_data,
    fetch_od_data,
    fetch_block_population,
    fetch_study_area_data,
    get_census_api_key,
)
from .cache import (
    cache_has,
    cache_get_path,
    cache_put_path,
    cache_put_bytes,
    cache_put_json,
    cache_get_json,
)
from .config import (
    DEFAULT_W_E,
    DEFAULT_U_E,
    DEFAULT_W_O,
    DEFAULT_U_O,
    B15003_CROSSWALK,
    EDUCATION_BIN_ORDER,
    B15003_VARIABLES,
)


# ---- Configuration loading ----

def load_default_params() -> WFHParams:
    """Load the pre-populated default WFH parameter vectors (DA-5)."""
    return WFHParams(
        w_e=DEFAULT_W_E.copy(),
        u_e=DEFAULT_U_E.copy(),
        w_o=DEFAULT_W_O.copy(),
        u_o=DEFAULT_U_O.copy(),
    )


def load_b15003_crosswalk() -> Dict[str, List[str]]:
    """Load the B15003-to-five-bin education crosswalk (DP-6)."""
    return B15003_CROSSWALK


# ---- Public API ----

def perturb_flows(
    alpha: float,
    baseline_flows: Dict[SpatialPair, float],
    edu_shares: Dict[SpatialUnitID, np.ndarray],
    ind_shares: Dict[SpatialUnitID, np.ndarray],
    commute_weights: Dict[SpatialPair, float],
    params: Optional[WFHParams] = None,
) -> PerturbationResult:
    """Compute perturbed flows for a given alpha.

    All inputs must use the same spatial keys (H3 hex IDs). Use
    prepare_hex_data() or convert_tract_data_to_hexes() to convert
    tract-level Census data to hex-level data first.

    Args:
        alpha: Proportional WFH scaling factor. Positive = more WFH, fewer trips.
        baseline_flows: Deep Gravity flows T_ij, keyed by (hex_i, hex_j) pairs.
        edu_shares: Education shares by residence hex. Maps hex_id -> ndarray(5,).
        ind_shares: Industry shares by workplace hex. Maps hex_id -> ndarray(20,).
        commute_weights: LODES commute weights L_ij. Maps (hex_i, hex_j) -> float.
        params: WFH parameter vectors. If None, uses built-in defaults (DA-5).

    Returns:
        PerturbationResult with P_ij, G_ij, Omega_ij, phi, metadata.
    """
    if params is None:
        params = load_default_params()

    # Wrap the hex-keyed dicts into a SpatialData container for the
    # computation layer, which is geometry-agnostic.
    spatial_data = SpatialData(
        edu_shares={k: np.asarray(v, dtype=np.float64) for k, v in edu_shares.items()},
        ind_shares={k: np.asarray(v, dtype=np.float64) for k, v in ind_shares.items()},
        commute_weights=dict(commute_weights),
    )

    result = run_perturbation(alpha, params, spatial_data, baseline_flows)

    result.metadata.update(create_metadata_record())
    result.metadata["alpha"] = alpha
    result.metadata["mode"] = "direct_alpha"

    return result


def solve_and_perturb(
    target_percent_change: float,
    baseline_flows: Dict[SpatialPair, float],
    edu_shares: Dict[SpatialUnitID, np.ndarray],
    ind_shares: Dict[SpatialUnitID, np.ndarray],
    commute_weights: Dict[SpatialPair, float],
    params: Optional[WFHParams] = None,
    tol: float = 1e-4,
) -> PerturbationResult:
    """Find alpha for a target percent change, then compute perturbed flows.

    Args:
        target_percent_change: Desired percent change (e.g., -0.10 for -10%).
        baseline_flows: Deep Gravity flows T_ij.
        edu_shares: Education shares by residence hex.
        ind_shares: Industry shares by workplace hex.
        commute_weights: LODES commute weights L_ij.
        params: WFH parameter vectors. If None, uses built-in defaults.
        tol: Convergence tolerance for the solver.

    Returns:
        PerturbationResult (with alpha set to the solved value).

    Raises:
        InfeasibleTargetError: If the target exceeds the feasible range.
    """
    if params is None:
        params = load_default_params()

    # Wrap hex-keyed dicts into SpatialData
    spatial_data = SpatialData(
        edu_shares={k: np.asarray(v, dtype=np.float64) for k, v in edu_shares.items()},
        ind_shares={k: np.asarray(v, dtype=np.float64) for k, v in ind_shares.items()},
        commute_weights=dict(commute_weights),
    )

    alpha = solve_for_alpha(
        target_percent_change, params, spatial_data, baseline_flows, tol
    )

    result = run_perturbation(alpha, params, spatial_data, baseline_flows)

    result.metadata.update(create_metadata_record())
    result.metadata["alpha"] = alpha
    result.metadata["mode"] = "solve_for_alpha"
    result.metadata["target_percent_change"] = target_percent_change
    result.metadata["achieved_percent_change"] = result.percent_change

    return result


__all__ = [
    # Public API
    "perturb_flows",
    "solve_and_perturb",
    "load_default_params",
    "load_b15003_crosswalk",
    # Data acquisition
    "fetch_education_data",
    "fetch_wac_data",
    "fetch_od_data",
    "fetch_block_population",
    "fetch_study_area_data",
    "get_census_api_key",
    # Cache functions
    "cache_has",
    "cache_get_path",
    "cache_put_path",
    "cache_put_bytes",
    "cache_put_json",
    "cache_get_json",
    # Computation functions
    "compute_joint_propensity",
    "compute_joint_upper_bound",
    "compute_bounded_deltas",
    "compute_perturbation_weights",
    "compute_phi_vectors",
    "compute_omega",
    "compute_symmetric_P",
    "run_perturbation",
    # Spatial conversion / hex preprocessing
    "convert_tract_data_to_hexes",
    "prepare_hex_data",
    # Solver
    "solve_for_alpha",
    "InfeasibleTargetError",
    # Types
    "WFHParams",
    "SpatialData",
    "PerturbationResult",
]
