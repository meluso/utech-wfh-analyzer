"""Aggregate scenario solver (Spec Section 4.E: AS-1 through AS-4).

Given a target percent change X in total flows, solves for alpha using
root-finding on the monotone function X(alpha).
"""

from __future__ import annotations

from typing import Dict
import numpy as np
from scipy.optimize import brentq

from .types import SpatialData, SpatialPair, WFHParams
from .computation import (
    compute_joint_propensity,
    compute_joint_upper_bound,
    run_perturbation,
)


class InfeasibleTargetError(Exception):
    """Raised when the target percent change exceeds the feasible range (AS-3)."""
    pass


def compute_alpha_max(params: WFHParams) -> float:
    """Compute the maximum meaningful alpha: largest breakpoint (u_eo - w_eo) / w_eo.

    At this alpha, all segments are saturated at their upper bounds.
    Beyond this alpha, further increases have no effect.
    """
    w_eo = compute_joint_propensity(params.w_e, params.w_o)
    u_eo = compute_joint_upper_bound(params.u_e, params.u_o)

    # Only consider segments where w_eo > 0 (otherwise alpha * w_eo = 0 always)
    mask = w_eo > 0
    if not mask.any():
        return 1.0  # No telework at all; alpha doesn't matter

    breakpoints = (u_eo[mask] - w_eo[mask]) / w_eo[mask]
    return float(np.max(breakpoints))


def solve_for_alpha(
    target_percent_change: float,
    params: WFHParams,
    spatial_data: SpatialData,
    baseline_flows: Dict[SpatialPair, float],
    tol: float = 1e-4,
) -> float:
    """AS-1, AS-2: Find alpha that produces the target percent change in total flow.

    Uses Brent's method on the monotone function f(alpha) = X(alpha) - X_target.

    Args:
        target_percent_change: Desired percent change (e.g., -0.10 for 10% reduction).
        params: WFH parameter vectors.
        spatial_data: Demographic and commute data.
        baseline_flows: Deep Gravity baseline flows T_ij.
        tol: Convergence tolerance for alpha.

    Returns:
        The alpha value that achieves the target.

    Raises:
        InfeasibleTargetError: If the target is outside the achievable range.
    """
    total_T = sum(baseline_flows.values())
    if total_T == 0:
        raise InfeasibleTargetError("No baseline flows; cannot solve for alpha.")

    def percent_change_at_alpha(alpha: float) -> float:
        result = run_perturbation(alpha, params, spatial_data, baseline_flows)
        total_G = sum(result.G.values())
        return (total_G - total_T) / total_T

    # Determine the feasible range
    alpha_max = compute_alpha_max(params)

    # Evaluate at boundaries
    X_at_minus_1 = percent_change_at_alpha(-1.0)
    X_at_alpha_max = percent_change_at_alpha(alpha_max)

    # AS-3: Check feasibility
    # X(alpha) is monotonically decreasing (more WFH -> fewer trips)
    # So X(-1) is the maximum (most trips) and X(alpha_max) is the minimum
    X_max = X_at_minus_1
    X_min = X_at_alpha_max

    if target_percent_change > X_max + tol:
        raise InfeasibleTargetError(
            f"Target {target_percent_change:.4f} exceeds maximum achievable "
            f"increase {X_max:.4f} (at alpha = -1.0, all WFH eliminated)."
        )
    if target_percent_change < X_min - tol:
        raise InfeasibleTargetError(
            f"Target {target_percent_change:.4f} exceeds maximum achievable "
            f"reduction {X_min:.4f} (at alpha = {alpha_max:.4f}, all segments saturated)."
        )

    # Special case: target is zero change
    if abs(target_percent_change) < tol:
        return 0.0

    # AS-2: Root-finding with Brent's method
    f = lambda a: percent_change_at_alpha(a) - target_percent_change

    # Search domain: alpha in [-1, alpha_max]
    try:
        alpha_solution = brentq(f, -1.0, alpha_max, xtol=tol, rtol=tol)
    except ValueError as e:
        raise InfeasibleTargetError(
            f"Root-finder failed: {e}. Target may be at boundary of feasible range."
        )

    return float(alpha_solution)
