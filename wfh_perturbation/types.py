"""Data types for the WFH perturbation module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


# Type aliases
SpatialUnitID = str  # FIPS code for tracts, H3 index for hexes, etc.
SpatialPair = Tuple[SpatialUnitID, SpatialUnitID]


@dataclass
class WFHParams:
    """Baseline WFH rates and structural upper bounds by education and industry.

    Attributes:
        w_e: Baseline WFH rates by education level (length 5).
        u_e: Structural upper bounds by education level (length 5).
        w_o: Baseline WFH rates by industry sector (length 20, CNS01-CNS20).
        u_o: Structural upper bounds by industry sector (length 20).
    """
    w_e: np.ndarray  # (5,)
    u_e: np.ndarray  # (5,)
    w_o: np.ndarray  # (20,)
    u_o: np.ndarray  # (20,)

    def __post_init__(self):
        self.w_e = np.asarray(self.w_e, dtype=np.float64)
        self.u_e = np.asarray(self.u_e, dtype=np.float64)
        self.w_o = np.asarray(self.w_o, dtype=np.float64)
        self.u_o = np.asarray(self.u_o, dtype=np.float64)
        assert self.w_e.shape == (5,), f"w_e must have 5 elements, got {self.w_e.shape}"
        assert self.u_e.shape == (5,), f"u_e must have 5 elements, got {self.u_e.shape}"
        assert self.w_o.shape == (20,), f"w_o must have 20 elements, got {self.w_o.shape}"
        assert self.u_o.shape == (20,), f"u_o must have 20 elements, got {self.u_o.shape}"


@dataclass
class SpatialData:
    """Demographic and commute data expressed in target spatial units.

    After spatial conversion, all vectors are indexed by spatial unit IDs
    (which may be tract FIPS codes, H3 hex indices, or any other identifier).

    Attributes:
        edu_shares: Education shares by residence. Maps spatial_unit_id -> np.ndarray(5,).
        ind_shares: Industry shares by workplace. Maps spatial_unit_id -> np.ndarray(20,).
        commute_weights: Observed commute weights L_ij. Maps (i, j) -> float.
            Directional: (i, j) means residence=i, workplace=j.
    """
    edu_shares: Dict[SpatialUnitID, np.ndarray]
    ind_shares: Dict[SpatialUnitID, np.ndarray]
    commute_weights: Dict[SpatialPair, float]


@dataclass
class PerturbationResult:
    """Output of the perturbation computation.

    Attributes:
        P: Symmetric perturbation factors. Maps (i, j) -> float.
            Guaranteed P_ij == P_ji.
        G: Perturbed flows. Maps (i, j) -> float.
            G_ij = T_ij * P_ij.
        omega: Directional aggregate perturbation factors. Maps (i, j) -> float.
            Omega_ij where i=residence, j=workplace.
        phi: Industry-weighted perturbation vectors by workplace.
            Maps spatial_unit_id -> np.ndarray(5,).
        alpha: The alpha value used (input or solver-determined).
        W_eo: The 5x20 perturbation weight matrix.
        w_eo: The 5x20 joint baseline propensity matrix.
        u_eo: The 5x20 joint upper bound matrix.
        metadata: Run metadata for reproducibility.
    """
    P: Dict[SpatialPair, float]
    G: Dict[SpatialPair, float]
    omega: Dict[SpatialPair, float]
    phi: Dict[SpatialUnitID, np.ndarray]
    alpha: float
    W_eo: np.ndarray  # (5, 20)
    w_eo: np.ndarray  # (5, 20)
    u_eo: np.ndarray  # (5, 20)
    metadata: Dict = field(default_factory=dict)

    @property
    def total_baseline_flow(self) -> float:
        """Sum of all T_ij (recoverable from G/P)."""
        total = 0.0
        for pair, g in self.G.items():
            p = self.P[pair]
            if p != 0:
                total += g / p
        return total

    @property
    def total_perturbed_flow(self) -> float:
        """Sum of all G_ij."""
        return sum(self.G.values())

    @property
    def percent_change(self) -> float:
        """Percent change in total flow: (sum G - sum T) / sum T."""
        t_total = self.total_baseline_flow
        if t_total == 0:
            return 0.0
        return (self.total_perturbed_flow - t_total) / t_total


