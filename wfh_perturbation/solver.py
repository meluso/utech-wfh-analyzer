"""Aggregate scenario solver (Spec Section 4.E: AS-1 through AS-4).

Given a target signed fractional change X in total flows, solves for the
scaling intensity alpha. The default path uses the closed-form relationship
from the WFH scenario supplement:

    X(alpha) = - sum_eo  m_eo * max(-phi_eo, min(alpha * phi_eo, c_eo))

where, per segment (e, o),

    phi_eo   = w_eo / (1 - w_eo)            (baseline WFH sensitivity)
    c_eo     = (u_eo - w_eo) / (1 - w_eo)   (saturated contribution at the cap)
    alpha_eo = (u_eo - w_eo) / w_eo         (upper breakpoint)
    m_eo     = trip-weighted share of segment (e, o) across all zone pairs.

The segment shares m_eo are accumulated in a single pass over the baseline
flows; after that, evaluating X(alpha) and solving for alpha are O(100) and
independent of the number of zone pairs. The full perturbation pipeline
(`run_perturbation`) then runs exactly once, at the call site, to produce the
perturbed flows for the solved alpha.

The sign convention matches the WFH scenario supplement: X = (sum G - sum T) / sum T, so a
reduction in travel is negative and increasing WFH (alpha > 0) makes X negative.

An exact breakpoint-walk implementation (`solve_for_alpha_exact`) is provided
as an optional alternative; it is derived in Derivation_Aggregate_Solver_Slope.md.
The bisection-on-closed-form path is the default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np
from scipy.optimize import brentq

from .types import SpatialData, SpatialPair, WFHParams
from .computation import (
    compute_joint_propensity,
    compute_joint_upper_bound,
)


class InfeasibleTargetError(Exception):
    """Raised when the target percent change exceeds the feasible range (AS-3)."""
    pass


# ---------------------------------------------------------------------------
# Closed-form aggregate model
# ---------------------------------------------------------------------------

@dataclass
class AggregateModel:
    """Closed-form relationship X(alpha) for one study area (WFH scenario supplement).

    All per-segment arrays are shaped (5, 20): education level by industry sector.

    Attributes:
        m_eo: Trip-weighted segment shares (sum over all pairs of T_ij * h_ij^eo,
            divided by total flow). These carry all the spatial information.
        phi_eo: Baseline WFH sensitivity w_eo / (1 - w_eo).
        c_eo: Saturated contribution (u_eo - w_eo) / (1 - w_eo); the value of
            1 - W_eo once the segment has reached its upper bound.
        alpha_eo: Upper breakpoint (u_eo - w_eo) / w_eo at which segment (e, o)
            saturates. np.inf where w_eo == 0 (the segment never saturates).
    """

    m_eo: np.ndarray
    phi_eo: np.ndarray
    c_eo: np.ndarray
    alpha_eo: np.ndarray

    @property
    def phi_bar(self) -> float:
        """Flow-weighted regional average sensitivity, Phi-bar = sum_eo phi_eo * m_eo."""
        return float(np.sum(self.phi_eo * self.m_eo))

    @property
    def X_max(self) -> float:
        """Largest achievable increase, X_max = Phi-bar, reached at alpha = -1."""
        return self.phi_bar

    @property
    def X_min(self) -> float:
        """Largest achievable reduction, X_min = -sum_eo c_eo * m_eo (full saturation)."""
        return -float(np.sum(self.c_eo * self.m_eo))

    @property
    def alpha_full_saturation(self) -> float:
        """Smallest alpha at which every contributing segment has saturated."""
        contributing = self.m_eo > 0
        if not np.any(contributing & np.isfinite(self.alpha_eo)):
            return 1.0  # No segment ever saturates (no telework); alpha is irrelevant.
        finite = self.alpha_eo[contributing & np.isfinite(self.alpha_eo)]
        return float(np.max(finite)) if finite.size else 1.0

    def feasible_X_range(self) -> Tuple[float, float]:
        """Return the feasibility domain [X_min, X_max] for the target."""
        return (self.X_min, self.X_max)

    def X_of_alpha(self, alpha: float) -> float:
        """Evaluate the signed aggregate change X at a given alpha.

        Uses the fully bounded form 1 - W_eo = max(-phi_eo, min(alpha*phi_eo, c_eo)),
        which reproduces the lower floor (alpha <= -1), the linear interior, and the
        upper caps in a single expression and matches the per-pair pipeline exactly.
        """
        one_minus_W = np.maximum(-self.phi_eo, np.minimum(alpha * self.phi_eo, self.c_eo))
        return -float(np.sum(self.m_eo * one_minus_W))

    def segment_breakpoints(self) -> List[Tuple[float, int, int]]:
        """Per-segment upper breakpoints (alpha_eo, e, o) for contributing segments.

        Sorted ascending by alpha_eo. Only segments with positive trip-weighted
        share and a finite breakpoint are included (others never bind in practice).
        """
        out: List[Tuple[float, int, int]] = []
        n_e, n_o = self.alpha_eo.shape
        for e in range(n_e):
            for o in range(n_o):
                a = self.alpha_eo[e, o]
                if self.m_eo[e, o] > 0 and np.isfinite(a):
                    out.append((float(a), e, o))
        out.sort(key=lambda t: t[0])
        return out

    def solve(self, target_percent_change: float, tol: float = 1e-4) -> float:
        """Solve for the alpha achieving a target signed change X (AS-2, AS-3).

        X(alpha) is continuous and strictly decreasing across the feasible domain,
        so any feasible target has a unique alpha. Uses bisection on the closed-form
        X(alpha); no flow pipeline is evaluated here.

        Raises:
            InfeasibleTargetError: If the target lies outside [X_min, X_max].
        """
        X_min, X_max = self.feasible_X_range()

        if target_percent_change > X_max + tol:
            raise InfeasibleTargetError(
                f"Target {target_percent_change:.4f} exceeds maximum achievable "
                f"increase {X_max:.4f} (at alpha = -1.0, all WFH eliminated)."
            )
        if target_percent_change < X_min - tol:
            raise InfeasibleTargetError(
                f"Target {target_percent_change:.4f} exceeds maximum achievable "
                f"reduction {X_min:.4f} (all segments saturated)."
            )

        if abs(target_percent_change) < tol:
            return 0.0

        alpha_max = self.alpha_full_saturation

        # Clamp targets sitting at (or just past) the feasible endpoints.
        if target_percent_change >= X_max - tol:
            return -1.0
        if target_percent_change <= X_min + tol:
            return alpha_max

        f = lambda a: self.X_of_alpha(a) - target_percent_change
        try:
            return float(brentq(f, -1.0, alpha_max, xtol=tol, rtol=min(tol, 1e-8)))
        except ValueError as e:
            raise InfeasibleTargetError(
                f"Root-finder failed: {e}. Target may be at the boundary of the feasible range."
            )


def _segment_coefficients(params: WFHParams) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute (phi_eo, c_eo, alpha_eo) from the WFH parameter vectors.

    phi_eo   = w_eo / (1 - w_eo)
    c_eo     = (u_eo - w_eo) / (1 - w_eo)
    alpha_eo = (u_eo - w_eo) / w_eo        (np.inf where w_eo == 0)
    """
    w_eo = compute_joint_propensity(params.w_e, params.w_o)
    u_eo = compute_joint_upper_bound(params.u_e, params.u_o)

    one_minus_w = 1.0 - w_eo
    safe_one_minus_w = np.where(one_minus_w == 0, 1.0, one_minus_w)
    phi_eo = np.where(one_minus_w == 0, 0.0, w_eo / safe_one_minus_w)
    c_eo = np.where(one_minus_w == 0, 0.0, (u_eo - w_eo) / safe_one_minus_w)

    safe_w = np.where(w_eo == 0, 1.0, w_eo)
    alpha_eo = np.where(w_eo == 0, np.inf, (u_eo - w_eo) / safe_w)
    return phi_eo, c_eo, alpha_eo


def build_aggregate_model(
    params: WFHParams,
    spatial_data: SpatialData,
    baseline_flows: Dict[SpatialPair, float],
) -> AggregateModel:
    """Precompute the closed-form aggregate model in one pass over the flows.

    Accumulates the trip-weighted segment shares

        m_eo = ( sum_ij T_ij * h_ij^eo ) / ( sum_ij T_ij ),

        h_ij^eo = ( L_ij * E_ie * O_jo + L_ji * E_je * O_io ) / ( L_ij + L_ji ),

    with the equal-weight fallback h_ij^eo = (E_ie*O_jo + E_je*O_io)/2 when a pair
    has no observed commute counts (L_ij + L_ji == 0), matching `compute_symmetric_P`.

    The sum runs over exactly the directed pairs present in `baseline_flows`, with
    each weighted by its own T_ij, so X_of_alpha reproduces the pipeline's aggregate.
    """
    phi_eo, c_eo, alpha_eo = _segment_coefficients(params)

    n_e = params.w_e.shape[0]
    n_o = params.w_o.shape[0]
    accum = np.zeros((n_e, n_o), dtype=np.float64)
    total_T = 0.0

    edu_shares = spatial_data.edu_shares
    ind_shares = spatial_data.ind_shares
    commute = spatial_data.commute_weights

    zero_e = np.zeros(n_e)
    zero_o = np.zeros(n_o)

    for (i, j), T_ij in baseline_flows.items():
        if T_ij == 0:
            continue
        E_i = edu_shares.get(i, zero_e)
        E_j = edu_shares.get(j, zero_e)
        O_i = ind_shares.get(i, zero_o)
        O_j = ind_shares.get(j, zero_o)

        L_ij = commute.get((i, j), 0.0)
        L_ji = commute.get((j, i), 0.0)
        L_total = L_ij + L_ji
        if L_total > 0:
            lam_ij = L_ij / L_total
            lam_ji = L_ji / L_total
        else:
            lam_ij = lam_ji = 0.5  # equal-weight fallback (matches compute_symmetric_P)

        # h_ij^eo = lam_ij * outer(E_i, O_j) + lam_ji * outer(E_j, O_i)
        h = lam_ij * np.outer(E_i, O_j) + lam_ji * np.outer(E_j, O_i)
        accum += T_ij * h
        total_T += T_ij

    if total_T == 0:
        raise InfeasibleTargetError("No baseline flows; cannot build aggregate model.")

    m_eo = accum / total_T
    return AggregateModel(m_eo=m_eo, phi_eo=phi_eo, c_eo=c_eo, alpha_eo=alpha_eo)


# ---------------------------------------------------------------------------
# Public solver entry points
# ---------------------------------------------------------------------------

def compute_alpha_max(params: WFHParams) -> float:
    """Largest segment breakpoint (u_eo - w_eo) / w_eo over all segments.

    At this alpha, every segment with positive baseline WFH is saturated at its
    upper bound; beyond it, further increases have no effect. Depends only on the
    parameter vectors, not on the spatial data.
    """
    w_eo = compute_joint_propensity(params.w_e, params.w_o)
    u_eo = compute_joint_upper_bound(params.u_e, params.u_o)

    mask = w_eo > 0
    if not mask.any():
        return 1.0  # No telework at all; alpha doesn't matter.

    breakpoints = (u_eo[mask] - w_eo[mask]) / w_eo[mask]
    return float(np.max(breakpoints))


def solve_for_alpha(
    target_percent_change: float,
    params: WFHParams,
    spatial_data: SpatialData,
    baseline_flows: Dict[SpatialPair, float],
    tol: float = 1e-4,
) -> float:
    """AS-1, AS-2: Find alpha producing the target signed change in total flow.

    Default implementation: build the closed-form aggregate model in one pass over
    the flows, then bisect X(alpha) - X_target on [-1, alpha_max]. No call to the
    full perturbation pipeline is made here; the caller runs that once afterwards.

    Args:
        target_percent_change: Desired signed fractional change (e.g., -0.10).
        params: WFH parameter vectors.
        spatial_data: Demographic and commute data.
        baseline_flows: Deep Gravity baseline flows T_ij.
        tol: Tolerance for the root-finder and for the zero/boundary thresholds.

    Returns:
        The alpha value that achieves the target.

    Raises:
        InfeasibleTargetError: If the target is outside [X_min, X_max].
    """
    model = build_aggregate_model(params, spatial_data, baseline_flows)
    return model.solve(target_percent_change, tol)


def solve_for_alpha_exact(
    target_percent_change: float,
    params: WFHParams,
    spatial_data: SpatialData,
    baseline_flows: Dict[SpatialPair, float],
    tol: float = 1e-12,
) -> float:
    """Optional exact alpha via the breakpoint walk (Derivation_Aggregate_Solver_Slope.md).

    Walks the piecewise-linear X(alpha) between segment breakpoints, solving the
    correct linear piece in closed form rather than by root-finding. Returns the
    same value as `solve_for_alpha` up to floating point; `solve_for_alpha` (bisection)
    is the default and is preferred for its simplicity.

    Raises:
        InfeasibleTargetError: If the target is outside [X_min, X_max].
    """
    model = build_aggregate_model(params, spatial_data, baseline_flows)
    X_min, X_max = model.feasible_X_range()

    if target_percent_change > X_max + tol:
        raise InfeasibleTargetError(
            f"Target {target_percent_change:.4f} exceeds maximum achievable "
            f"increase {X_max:.4f}."
        )
    if target_percent_change < X_min - tol:
        raise InfeasibleTargetError(
            f"Target {target_percent_change:.4f} exceeds maximum achievable "
            f"reduction {X_min:.4f}."
        )
    if abs(target_percent_change) < tol:
        return 0.0

    # Increase side (target > 0): single linear piece X = -alpha * Phi-bar on [-1, 0].
    if target_percent_change > 0:
        phi_bar = model.phi_bar
        if phi_bar == 0:
            raise InfeasibleTargetError("Phi-bar is zero; no positive target is reachable.")
        return -target_percent_change / phi_bar

    # Reduction side (target < 0): walk forward through ascending breakpoints.
    # Slope magnitude starts at Phi-bar (all segments interior) and each crossed
    # breakpoint removes that segment's phi_eo * m_eo from the slope.
    breakpoints = model.segment_breakpoints()
    phi_m = model.phi_eo * model.m_eo
    slope = -float(np.sum(phi_m))  # dX/dalpha at alpha = 0 (negative)

    alpha_prev = 0.0
    X_prev = 0.0
    for alpha_bp, e, o in breakpoints:
        X_at_bp = X_prev + slope * (alpha_bp - alpha_prev)
        if X_at_bp <= target_percent_change:
            # Target lies in the current interval; solve the linear piece.
            return alpha_prev + (target_percent_change - X_prev) / slope
        # Cross this breakpoint: segment (e, o) saturates, slope flattens.
        X_prev = X_at_bp
        alpha_prev = alpha_bp
        slope += phi_m[e, o]
        if slope == 0:
            break

    # Beyond the last breakpoint the slope is ~0 and X has reached X_min.
    raise InfeasibleTargetError(
        f"Target {target_percent_change:.6f} not reached before full saturation "
        f"(X_min = {model.X_min:.6f})."
    )
