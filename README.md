# WFH Perturbation Module

Post-generation behavioral perturbation framework for the uTECH-Cities project. This module takes baseline commute flows (from Deep Gravity or similar models) and produces perturbed flows that reflect a Work-From-Home scenario, parameterized by a single scaling factor $\alpha$.

The core idea: different education-by-industry segments have different WFH propensities. A hex with many college-educated professional-services workers will see a larger reduction in commute trips than a hex dominated by retail and food-service employment. This module computes those segment-specific adjustments and aggregates them into a single symmetric perturbation factor $P$ for each origin-destination pair, such that the perturbed flow $G = T \times P$.

## Installation

Clone the repo and install in editable mode:

```bash
git clone https://github.com/meluso/utech-wfh-analyzer.git
cd utech-wfh-analyzer
pip install -e .
```

This installs all dependencies including geopandas and h3 (required for H3 spatial conversion from Census tracts). If pip has trouble building the geo stack, you can install those two via conda first:

```bash
conda install -c conda-forge geopandas h3
pip install -e .
```

### Census API Key

Education data comes from the Census Bureau's ACS API, which requires a free API key. Get one at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html). Then make it available in one of three ways (checked in this order):

1. Pass it directly: `api_key="your_key"` in function calls
2. Set an environment variable: `export CENSUS_API_KEY=your_key`
3. Save it to a file: `wfh_perturbation/config/api_key.txt`

## Quick Start

The module runs in two modes, and the choice depends on which quantity your scenario specifies. Use **target-X mode** when the outcome is specified: "model a 15% reduction in total trips," with the behavioral intensity $\alpha$ solved per region to achieve it. Use **fixed-alpha mode** when the behavioral scenario is specified and the outcome should vary by region: "WFH propensity rises 25% above baseline everywhere," applying the same shock to every city and letting each city's aggregate change $X$ emerge as the result. For cross-city comparisons, note these are different experimental designs: matching cities on $X$ imposes a different behavioral shock in each city, while matching on $\alpha$ holds the behavior constant and compares outcomes.

### Hex-native workflow

This is the workflow for integration with the uTECH pipeline. Deep Gravity outputs hex-level flows, and this module perturbs them at hex level. Shown here in fixed-alpha mode; the target-X form follows below.

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
    alpha=0.25,                     # WFH intensity: 0 = no change; max varies by region
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

### Target-based mode (recommended): choosing X instead of alpha

For scenario analysis you usually know the desired aggregate percent change in trips (X), not the $\alpha$ value, and the solver will find $\alpha$ for you. Each study area has its own achievable range of X, fixed by its labor mix, baseline WFH rates, and structural ceilings; a target outside that range raises `InfeasibleTargetError` rather than returning a nonsensical $\alpha$. The recommended pattern — for one city or many — is therefore to build the aggregate model first, read its feasible range, and solve targets against the model:

```python
import numpy as np
from wfh_perturbation import build_aggregate_model, load_default_params, SpatialData

sd = SpatialData(edu_shares=hex_edu, ind_shares=hex_ind, commute_weights=hex_commute)
model = build_aggregate_model(load_default_params(), sd, deep_gravity_flows)

x_min, x_max = model.feasible_X_range()  # e.g. (-0.45, +1.38); differs by city
targets = np.linspace(x_min * 0.95, x_max * 0.95, 50)

for target in targets:
    alpha = model.solve(float(target))  # cheap: reuses the one-pass aggregate model
    result = perturb_flows(
        alpha=alpha,
        baseline_flows=deep_gravity_flows,
        edu_shares=hex_edu,
        ind_shares=hex_ind,
        commute_weights=hex_commute,
    )
```

Building the model is a single pass over the baseline flows, and `model.solve` is pure arithmetic afterward, so a sweep costs one full pipeline run per target and nothing more. The per-city `feasible_X_range` is also worth reporting in its own right, since it characterizes how much WFH-induced change each region can structurally absorb. See `examples/hex_pipeline_example.py` for the full pattern.

For a single target you already know is feasible, `solve_and_perturb` wraps the same solve in one call:

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

**1. Joint WFH propensity matrix ($5 \times 20$).** For each education level *e* and industry sector *o*, the joint baseline WFH rate is $w_{eo} = 1 - (1-w_e)(1-w_o)$, combining education-level and industry-level WFH rates from CPS data.

**2. Bounded perturbation deltas.** The change in WFH rate for each segment is $\Delta w_{eo} = \max(-w_{eo},\, \min(\alpha\,w_{eo},\, u_{eo} - w_{eo}))$. This ensures WFH rates stay between 0 and the structural upper bound $u_{eo}$ (from Dingel-Neiman 2020). Positive $\alpha$ increases WFH (reducing commute trips); negative $\alpha$ decreases WFH (increasing trips).

**3. Perturbation weights.** The trip-reduction factor for each segment is $W_{eo} = 1 - \Delta w_{eo} / (1 - w_{eo})$. This is the fraction of non-WFH commuters who remain after the perturbation.

**4. Directional Omega.** For a given origin *i* and destination *j*, the directional perturbation factor $\Omega_{ij} = \sum_e E_{ie} \cdot \theta_e(j)$, where $E_{ie}$ is the education share at residence *i* and $\theta_e(j) = \sum_o W_{eo} \cdot O_{jo}$ is a precomputed vector combining industry shares at workplace *j* with the perturbation weights. (This per-workplace vector is named `theta` in the code and the supplement to avoid colliding with the segment sensitivity $\phi_{eo}$.) This precomputation (computing $\theta$ once per workplace, then dotting with education shares per pair) reduces the per-pair work from O(100) multiplications to O(5).

**5. Symmetric P.** The final perturbation factor is $P_{ij} = (L_{ij}\,\Omega_{ij} + L_{ji}\,\Omega_{ji}) / (L_{ij} + L_{ji})$, a commute-weighted average of the two directional factors. This guarantees $P_{ij} = P_{ji}$. When no commute data exists for a pair ($L_{ij} + L_{ji} = 0$), the fallback is an equal-weight average: $P = (\Omega_{ij} + \Omega_{ji}) / 2$.

The perturbed flow is then $G_{ij} = T_{ij} \times P_{ij}$.

## Module Structure

```
wfh_perturbation/
├── __init__.py          # Public API: perturb_flows(), solve_and_perturb()
├── types.py             # Data types: WFHParams, SpatialData, PerturbationResult
├── config.py            # Default WFH parameters (CPS/Dingel-Neiman), B15003 crosswalk
├── computation.py       # Core math: joint propensity, deltas, weights, omega, P
├── solver.py            # Aggregate scenario solver (closed-form X(α); bisection)
├── spatial.py           # Tract-to-hex conversion, prepare_hex_data()
├── data_acquisition.py  # Census API (ACS B15003), LODES WAC/OD fetching
├── geo.py               # TIGER shapefiles, block centroids, H3 hex assignment
├── fips.py              # FIPS code parsing and state/county utilities
└── cache.py             # Plain-function file cache for API responses and downloads

tests/
├── test_validation.py   # 36 tests validating math against spec (hardcoded data, no API)
└── test_integration.py  # Live API tests: education, WAC, OD, end-to-end, H3 hex pipeline
```

## Key Parameters

**$\alpha$ (alpha):** The WFH intensity scaling factor. At $\alpha = 0$, no perturbation occurs ($P = 1$ everywhere). At $\alpha = 0.25$, each segment's WFH rate increases by 25% of its baseline rate (bounded by the structural ceiling). Negative $\alpha$ decreases WFH rates, which increases commute trips ($P > 1$). In the visualization tool, the slider operates in percent-change space (the WFH-induced change in aggregate travel demand) rather than $\alpha$ directly; $\alpha$ is solved internally and shown as a secondary readout.

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
Compute perturbed flows for a given $\alpha$. Returns a `PerturbationResult` with P, G, omega, theta, and metadata. All inputs must use the same spatial keys (H3 hex IDs).

**`solve_and_perturb(target_percent_change, baseline_flows, edu_shares, ind_shares, commute_weights, ...)`**
Find the $\alpha$ that achieves a target aggregate percent change in trips, then compute perturbed flows. Solves $\alpha$ from the closed-form relationship $X(\alpha) = -\sum m_{eo} \cdot \min(\alpha\,\phi_{eo},\, c_{eo})$ by bisection (the full pipeline runs once, after $\alpha$ is found), and raises `InfeasibleTargetError` if the target exceeds the feasible range. An exact breakpoint-walk alternative is available as `solve_for_alpha_exact`.

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
- `G`: dict mapping (i, j) -> perturbed flow ($G = T \times P$)
- `omega`: dict mapping (i, j) -> directional Omega
- `theta`: dict mapping unit_id -> ndarray(5,) precomputed per-workplace vector $\theta_e(s)$
- `alpha`: the $\alpha$ value used
- `percent_change`: aggregate percent change in total flow (property)
- `metadata`: dict with run info, data vintages, etc.
