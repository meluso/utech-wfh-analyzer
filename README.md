# WFH Perturbation Module

Post-generation behavioral perturbation framework for the uTECH-Cities project. This module takes baseline commute flows (from Deep Gravity or similar models) and produces perturbed flows that reflect a Work-From-Home scenario, parameterized by a single scaling factor α.

The core idea: different education×industry segments have different WFH propensities. A hex with many college-educated professional-services workers will see a larger reduction in commute trips than a hex dominated by retail and food-service employment. This module computes those segment-specific adjustments and aggregates them into a single symmetric perturbation factor P for each origin-destination pair, such that the perturbed flow G = T × P.

## Installation

Clone the repo and install in editable mode with geo dependencies (required for H3 spatial conversion from Census tracts):

```bash
git clone git@github.com:johnameluso/utech-wfh-perturbation.git
cd utech-wfh-perturbation
pip install -e ".[hex]"
```

If you prefer conda for the geo stack:

```bash
pip install -e .
conda install -c conda-forge geopandas h3
```

### Census API Key

Education data comes from the Census Bureau's ACS API, which requires a free API key. Get one at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html). Then make it available in one of three ways (checked in this order):

1. Pass it directly: `api_key="your_key"` in function calls
2. Set an environment variable: `export CENSUS_API_KEY=your_key`
3. Save it to a file: `wfh_perturbation/config/api_key.txt`

## Quick Start

### Hex-native workflow

This is the workflow for integration with the uTECH pipeline. Deep Gravity outputs hex-level flows, and this module perturbs them at hex level.

```python
from wfh_perturbation import prepare_hex_data, perturb_flows

# Step 1: One-time preprocessing — converts tract-level Census demographics
# to H3 hex-level education shares, industry shares, and commute weights.
# This downloads ACS, LODES, and TIGER data (cached after first run).
study_area_tracts = ["48453001101", "48453002422", ...]  # all tracts covering your hex grid

hex_edu, hex_ind, hex_commute = prepare_hex_data(
    study_area_tracts,
    resolution=7,           # H3 resolution (7 ≈ 5 km hexes)
    api_key="your_key",     # or set CENSUS_API_KEY env var
)

# Step 2: Load your Deep Gravity hex-level baseline flows
# These are dict mappings from (hex_origin, hex_destination) -> flow_count
deep_gravity_flows = {
    ("872830828ffffff", "87283082effffff"): 1450.0,
    ("87283082effffff", "872830828ffffff"): 320.0,
    ...
}

# Step 3: Perturb
result = perturb_flows(
    alpha=0.25,                     # WFH intensity: 0 = no change, 1 = max WFH
    baseline_flows=deep_gravity_flows,
    edu_shares=hex_edu,
    ind_shares=hex_ind,
    commute_weights=hex_commute,
)

# Access results
for (origin, dest), G in result.G.items():
    P = result.P[(origin, dest)]
    print(f"{origin} -> {dest}: P={P:.4f}, G={G:.1f}")

print(f"Aggregate change: {result.percent_change:.2%}")
```

### Target-based mode

If you know the desired aggregate percent change in trips (e.g., -15%) but not the α value, the solver will find it:

```python
from wfh_perturbation import solve_and_perturb

result = solve_and_perturb(
    target_percent_change=-0.15,    # -15% total trips
    baseline_flows=deep_gravity_flows,
    edu_shares=hex_edu,
    ind_shares=hex_ind,
    commute_weights=hex_commute,
)

print(f"Solved α = {result.alpha:.4f}")
print(f"Achieved change: {result.percent_change:.2%}")
```

## How It Works

The perturbation proceeds in five stages for each origin-destination pair:

**1. Joint WFH propensity matrix (5×20).** For each education level *e* and industry sector *o*, the joint baseline WFH rate is w\_eo = 1 − (1−w\_e)(1−w\_o), combining education-level and industry-level WFH rates from CPS data.

**2. Bounded perturbation deltas.** The change in WFH rate for each segment is Δw\_eo = max(−w\_eo, min(α·w\_eo, u\_eo − w\_eo)). This ensures WFH rates stay between 0 and the structural upper bound u\_eo (from Dingel-Neiman 2020). Positive α increases WFH (reducing commute trips); negative α decreases WFH (increasing trips).

**3. Perturbation weights.** The trip-reduction factor for each segment is W\_eo = 1 − Δw\_eo / (1−w\_eo). This is the fraction of non-WFH commuters who remain after the perturbation.

**4. Directional Omega.** For a given origin *i* and destination *j*, the directional perturbation factor Ω\_ij = Σ\_e E\_ie · φ\_e(j), where E\_ie is the education share at residence *i* and φ\_e(j) = Σ\_o W\_eo · O\_jo is a precomputed vector combining industry shares at workplace *j* with the perturbation weights. This precomputation (computing φ once per workplace, then dotting with education shares per pair) reduces the per-pair work from O(100) multiplications to O(5).

**5. Symmetric P.** The final perturbation factor is P\_ij = (L\_ij·Ω\_ij + L\_ji·Ω\_ji) / (L\_ij + L\_ji), a commute-weighted average of the two directional factors. This guarantees P\_ij = P\_ji. When no commute data exists for a pair (L\_ij + L\_ji = 0), the fallback is an equal-weight average: P = (Ω\_ij + Ω\_ji) / 2.

The perturbed flow is then G\_ij = T\_ij × P\_ij.

## Module Structure

```
wfh_perturbation/
├── __init__.py          # Public API: perturb_flows(), solve_and_perturb()
├── types.py             # Data types: WFHParams, SpatialData, PerturbationResult
├── config.py            # Default WFH parameters (CPS/Dingel-Neiman), B15003 crosswalk
├── computation.py       # Core math: joint propensity, deltas, weights, omega, P
├── solver.py            # Aggregate scenario solver (Brent's method root-finding)
├── spatial.py           # Tract-to-hex conversion, prepare_hex_data()
├── data_acquisition.py  # Census API (ACS B15003), LODES WAC/OD fetching
├── geo.py               # TIGER shapefiles, block centroids, H3 hex assignment
├── fips.py              # FIPS code parsing and state/county utilities
└── cache.py             # Plain-function file cache for API responses and downloads

tests/
├── test_validation.py   # 30 tests validating math against spec (hardcoded data, no API)
└── test_integration.py  # Live API tests: education, WAC, OD, end-to-end, H3 hex pipeline
```

## Key Parameters

**α (alpha):** The WFH intensity scaling factor. At α=0, no perturbation occurs (P=1 everywhere). At α=0.25, each segment's WFH rate increases by 25% of its baseline rate (bounded by the structural ceiling). Negative α decreases WFH rates, which increases commute trips (P > 1). In the visualization tool, the slider operates in percent-change space (the WFH-induced change in aggregate travel demand) rather than α directly; α is solved internally and shown as a secondary readout.

**Education shares (5 bins):** Less than HS, HS Diploma, Some College/Associate's, Bachelor's, Advanced degree. Derived from ACS table B15003 at the residence location.

**Industry shares (20 sectors):** LODES CNS01 through CNS20, covering all NAICS-based industry sectors. Derived from LODES Workplace Area Characteristics at the workplace location.

**Commute weights:** LODES Origin-Destination flows, used to weight the directional Omega factors into the symmetric P. These represent observed commute patterns between spatial units.

**H3 resolution:** Default 7 (~5 km hexes). Configurable via the `resolution` parameter in `prepare_hex_data()`. Higher resolutions give finer spatial granularity but increase computation.

## Data Sources

All data is fetched automatically and cached locally after the first download.

| Data | Source | Access |
|------|--------|--------|
| Education attainment | ACS 5-Year, Table B15003 | Census API (requires free key) |
| Industry employment | LODES WAC (Workplace Area Characteristics) | Direct CSV download from lehd.ces.census.gov |
| Commute flows | LODES OD (Origin-Destination) | Direct CSV download from lehd.ces.census.gov |
| Block population | Decennial Census P1 | Census API (requires free key) |
| Block/tract boundaries | TIGER/Line Shapefiles | Direct download from census.gov |

## Running Tests

The validation tests run without any API key or network access:

```bash
python -m pytest tests/test_validation.py -v
```

The integration tests require a Census API key and network access:

```bash
CENSUS_API_KEY=your_key python -m pytest tests/test_integration.py -v -s
```

The first integration run downloads LODES and TIGER files, which takes a few minutes. Subsequent runs use the cache and complete in under a minute.

## Custom WFH Parameters

The built-in WFH rates come from CPS Q1/Aug 2024 supplements, and the upper bounds from Dingel-Neiman (2020). You can override them:

```python
from wfh_perturbation import WFHParams, perturb_flows
import numpy as np

custom_params = WFHParams(
    w_e=np.array([0.02, 0.06, 0.15, 0.35, 0.40]),   # baseline WFH by education
    u_e=np.array([0.08, 0.15, 0.28, 0.50, 0.65]),    # upper bounds by education
    w_o=np.array([...]),  # 20 values for CNS01-CNS20
    u_o=np.array([...]),  # 20 values for CNS01-CNS20
)

result = perturb_flows(alpha=0.25, ..., params=custom_params)
```

## API Reference

### Primary Functions

**`perturb_flows(alpha, baseline_flows, edu_shares, ind_shares, commute_weights, ...)`**
Compute perturbed flows for a given α. Returns a `PerturbationResult` with P, G, omega, phi, and metadata. All inputs must use the same spatial keys (H3 hex IDs).

**`solve_and_perturb(target_percent_change, baseline_flows, edu_shares, ind_shares, commute_weights, ...)`**
Find the α that achieves a target aggregate percent change in trips, then compute perturbed flows. Uses Brent's method root-finding on the monotone X(α) function. Raises `InfeasibleTargetError` if the target exceeds the feasible range.

### Data Preparation

**`prepare_hex_data(tract_fips, resolution=7, api_key=None, ...)`**
All-in-one function: fetches Census data for the given tracts and converts to H3 hex-level education shares, industry shares, and commute weights. Returns `(hex_edu, hex_ind, hex_commute)`.

**`convert_tract_data_to_hexes(edu_shares, ind_shares, commute_weights, residential_weights, employment_weights)`**
Lower-level preprocessing: converts tract-level data to hex level using pre-computed block-to-hex allocation weights. Useful when you've already fetched the data separately.

**`fetch_study_area_data(tract_fips, api_key=None, ...)`**
Fetch tract-level education, industry, and commute data. Returns `(edu, ind, commute)` dicts at tract level.

### Result Object

`PerturbationResult` has these attributes:
- `P`: dict mapping (i, j) -> perturbation factor
- `G`: dict mapping (i, j) -> perturbed flow (G = T × P)
- `omega`: dict mapping (i, j) -> directional Omega
- `phi`: dict mapping unit_id -> ndarray(5,) precomputed phi vector
- `alpha`: the α value used
- `percent_change`: aggregate percent change in total flow (property)
- `metadata`: dict with run info, data vintages, etc.
