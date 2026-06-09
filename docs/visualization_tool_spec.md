# WFH Perturbation Visualization Tool — Specification

## 1. Purpose

This tool demonstrates the WFH perturbation framework for the uTECH-Cities project. It targets two audiences in the same meeting:

- **Oliver (advisor):** Wants to see how WFH scenarios change commute flows across a real region. Cares about spatial patterns — which corridors lose the most traffic, which are barely affected, and how the pattern shifts as the WFH scenario intensifies.
- **Cafer (collaborator):** Wants the underlying data in formats he can plug into his own pipeline. Cares about CSVs and GeoJSON he can load into pandas or QGIS without touching the visualization.

The tool consists of two parts: a **Python precomputation pipeline** that runs once to produce all necessary data, and a **static React frontend** that loads the precomputed data and renders an interactive map. No running server is required at demo time.


## 2. Study Area

Queens County, New York (FIPS 36081), plus Manhattan and other destination tracts that Queens residents commute to.

- Queens has approximately 670 Census tracts.
- At H3 resolution 7, this produces roughly 300–500 hexes covering Queens.
- Destination hexes in Manhattan and elsewhere are included based on LODES OD data (any tract that Queens residents commute to).
- The total number of OD pairs will be in the low thousands.

This scope is chosen because it is large enough to show meaningful spatial variation but small enough to precompute comfortably on a laptop (MacBook M3 Pro, 36 GB unified memory).


## 3. Architecture Overview

```
┌─────────────────────────────┐
│  Python Precomputation      │
│  (runs once, ~5–10 min)     │
│                             │
│  1. Data acquisition        │
│     (Census API + LODES)    │
│  2. Hex conversion          │
│     (prepare_hex_data)      │
│  3. X sweep                 │
│     (solve α per X target)  │
│  4. Export JSON + CSV        │
│                             │
└──────────┬──────────────────┘
           │ writes
           ▼
┌─────────────────────────────┐
│  Static Output Files        │
│                             │
│  viz_data/                  │
│  ├── hex_geometries.geojson │
│  ├── snapshots.json         │
│  ├── hex_metadata.json      │
│  ├── pairs_x_sweep.csv      │
│  └── hex_summary.csv        │
│                             │
└──────────┬──────────────────┘
           │ loaded by
           ▼
┌─────────────────────────────┐
│  React Frontend             │
│  (single-page, static)      │
│                             │
│  - Mapbox + deck.gl         │
│  - WFH scenario slider      │
│  - Hex choropleth layer     │
│  - Flow arc layer           │
│  - Summary stats panel      │
│  - Click-to-inspect panel   │
│                             │
└─────────────────────────────┘
```


## 4. Precomputation Pipeline

### 4.1 Data Acquisition

Use the existing module functions:

```python
from wfh_perturbation import (
    prepare_hex_data,
    fetch_od_data,
    perturb_flows,
    load_default_params,
)
from wfh_perturbation import build_aggregate_model, SpatialData
```

Note: `build_aggregate_model` builds the closed-form aggregate model once. Its `feasible_X_range()` gives the X-sweep endpoints `[X_min, X_max]`, and `model.solve(X)` returns the α for a target X.

Steps:

1. Identify all Census tracts in Queens County (FIPS 36081). The Census API can list tracts in a county: `https://api.census.gov/data/2024/acs/acs5?get=NAME&for=tract:*&in=state:36+county:081&key=YOUR_KEY`. Parse the FIPS codes as 11-digit strings (state + county + tract).
2. Fetch LODES OD data for New York state to identify destination tracts. Filter to pairs where at least one endpoint is a Queens tract. Include the destination tracts (e.g., Manhattan tracts) in the study area so their demographics are fetched too.
3. Call `prepare_hex_data(all_tracts, resolution=7, ...)` to get hex-level education shares, industry shares, and commute weights.
4. Use LODES OD counts as proxy baseline flows (T_ij). In production these come from Deep Gravity, but for this demo LODES is the best available public approximation. Scale the LODES counts if desired (they represent a sample, not total commuters), but document the scaling factor.

### 4.2 X Sweep

Build the closed-form aggregate model once with `build_aggregate_model`, read the feasible range `[X_min, X_max]` from `feasible_X_range()`, and choose 100 evenly spaced target values of X across that range. For each target X, solve for the scaling intensity with `model.solve(X)` (α is the byproduct, not the swept variable), then call `perturb_flows(α)` and store:

- Per-pair: `P_ij`, `G_ij`, `Omega_ij`, `Omega_ji`
- Per-hex: total inbound G, total outbound G, net change vs baseline
- Aggregate: total flow, percent change

### 4.3 Output Files

#### `hex_geometries.geojson`

H3 hex boundaries as GeoJSON polygons. Each feature includes:

- `hex_id`: H3 index string
- `centroid_lat`, `centroid_lng`: for arc endpoints

Generate hex boundaries using `h3.cell_to_boundary()`. This file is used by both the frontend (map rendering) and Cafer (QGIS).

#### `hex_metadata.json`

Per-hex demographic data, keyed by hex_id:

```json
{
  "872a1072dffffff": {
    "edu_shares": [0.06, 0.19, 0.08, 0.40, 0.27],
    "ind_shares": [0.00, 0.00, 0.02, ...],
    "ind_top4": [
      {"index": 11, "label": "Finance & Insurance", "share": 0.21},
      {"index": 9, "label": "Information", "share": 0.20},
      {"index": 15, "label": "Education", "share": 0.15},
      {"index": 6, "label": "Retail Trade", "share": 0.07}
    ],
    "ind_other_share": 0.37,
    "total_inbound_T": 4200.0,
    "total_outbound_T": 3800.0
  }
}
```

The `ind_top4` array and `ind_other_share` are precomputed for the inspect panel's 4+1 industry bar chart. Use the LODES CNS sector labels from `config.py`.

Education bin labels (from `config.py`): Less than HS, HS Diploma, Some College, Bachelor's, Advanced.

#### `snapshots.json`

The main data file for the frontend. Structure:

```json
{
  "x_values": [-0.45, -0.42, ..., 0.189],
  "alpha_values": [2.76, 2.10, ..., -1.0],
  "pair_keys": [["872a1072dffffff", "872a1073dffffff"], ...],
  "L_ij": [23.0, ...],
  "L_ji": [0.0, ...],
  "T": [2200.0, ...],
  "snapshots": [
    {
      "target_percent_change": 0.189,
      "alpha": -1.0,
      "total_T": 185000.0,
      "total_G": 220000.0,
      "percent_change": 0.189,
      "P": [1.12, 1.08, ...],
      "G": [2464.0, 1512.0, ...],
      "Omega_ij": [1.10, 1.05, ...],
      "Omega_ji": [1.14, 1.11, ...],
      "hex_net_change": {
        "872a1072dffffff": -0.15,
        ...
      }
    },
    ...
  ]
}
```

The `P`, `G`, `Omega_ij`, and `Omega_ji` arrays are parallel to `pair_keys`. The top-level `L_ij`, `L_ji`, and `T` arrays are also parallel to `pair_keys` and store the constant (operating-point-independent) commute weights and baseline flows. These are needed by the inspect panel's "Why This P Value" section. This structure avoids repeating hex ID strings 100 times and keeps the file compact.

`hex_net_change` maps each hex to its percent change in total flow (inbound + outbound) at that operating point, used for the choropleth.

Target file size: 10–30 MB for a borough-scale study area. This loads comfortably in browser memory.

#### `pairs_x_sweep.csv` (for Cafer)

Flat CSV with one row per (pair, operating point) combination. Each operating point is identified by `target_pct_change` (the swept X target) and `alpha` (the intensity solved to reach it):

```
origin_hex,destination_hex,target_pct_change,alpha,T_ij,P_ij,G_ij,Omega_ij,Omega_ji,L_ij,L_ji
872a1072dffffff,872a1073dffffff,0.189,-1.0,2200.0,1.12,2464.0,1.10,1.14,23.0,0.0
872a1072dffffff,872a1073dffffff,0.170,-0.93,2200.0,1.11,2442.0,1.09,1.13,23.0,0.0
...
```

This is the "Cafer export." He can filter to a single operating point (a target X or its α), join with his own hex data, or compute custom aggregations.

#### `hex_summary.csv` (for Cafer)

Flat CSV with one row per (hex, operating point) combination:

```
hex_id,target_pct_change,alpha,total_inbound_T,total_inbound_G,total_outbound_T,total_outbound_G,pct_change_inbound,pct_change_outbound,edu_top_bin,ind_top_sector
872a1072dffffff,0.189,-1.0,4200.0,4704.0,3800.0,4256.0,0.12,0.12,Bachelor's,Finance & Insurance
...
```


## 5. Frontend

### 5.1 Tech Stack

- **React** (single-page app, single `.jsx` file is fine for a demo)
- **react-map-gl** (Mapbox GL JS wrapper) for the base map
- **deck.gl** for the H3 hex layer and arc layer
- **Mapbox** basemap style: `mapbox://styles/mapbox/dark-v11` (dark theme makes the data layers pop)

The app loads the precomputed JSON files on startup. No API calls at runtime.

A free Mapbox token is sufficient for demo use.

### 5.2 Map View

Initial viewport: centered on Queens, zoomed to show the full borough plus Manhattan.

```
center: [-73.85, 40.71]
zoom: 10.5
pitch: 30 (slight tilt for arc visibility)
```

### 5.3 Hex Choropleth Layer

Each hex is filled based on its `hex_net_change` value at the current operating point.

Color scale: diverging blue-white-red.

- Blue (negative change): corridors where WFH reduces traffic. Darker blue = larger reduction.
- White/light gray (near zero): minimal change.
- Red (positive change): corridors where reduced WFH increases traffic (negative alpha scenarios).

Use a symmetric color scale anchored at 0. The domain should be fixed across all operating points (use the global min/max across the full sweep) so that colors are comparable as the slider moves.

Hex opacity: 0.7 (so the basemap is faintly visible beneath).

Hex border: thin white line (0.5px) for hex edge visibility.

### 5.4 Flow Arc Layer

Show the top N most-changed OD pairs at the current operating point. N = 75 is a reasonable starting point (enough to see the pattern, not so many that it becomes visual noise).

"Most changed" = largest absolute value of `(P_ij - 1) * T_ij`, i.e., the largest absolute change in flow volume. This emphasizes corridors that matter in aggregate, not just corridors with extreme P values on tiny flows.

Arc properties:

- **Source/target:** hex centroids from the GeoJSON.
- **Color:** same diverging scale as the choropleth (blue for reduction, red for increase).
- **Width:** proportional to baseline flow T_ij, mapped to a 1–6 pixel range.
- **Height:** 0.3 (slight curve for visual separation when arcs overlap).
- **Opacity:** 0.6.

Arcs update when the scenario slider moves (the top-N set may change).

### 5.5 WFH Scenario Slider

A horizontal slider across the top of the viewport. The slider operates in percent-change space: the user drags to select the WFH-induced change in aggregate travel demand, and the app snaps to the nearest precomputed snapshot.

- Range: the feasible percent-change domain derived from the precomputed snapshots (from maximum WFH on the right to minimum WFH on the left). The display is negated so that positive values correspond to more WFH (dragging right = more WFH = fewer trips).
- Default position: 0 (no change from baseline).
- Step size: snaps to the nearest precomputed snapshot by `percent_change`.
- Label: shows the WFH-induced change in travel demand (e.g., "+8.3% WFH-induced change in travel demand"), α as a secondary readout, and a plain-English scenario description.
- Endpoint labels: "Less WFH" on the left, "More WFH" on the right.

Moving the slider updates the hex colors, arc colors/widths, and summary stats in real time (just an array swap in the precomputed data, no computation).

### 5.6 Summary Stats Panel

A small panel in the top-right corner showing aggregate numbers for the current operating point:

- **Baseline flow:** sum of T_ij (constant, doesn't change with the scenario).
- **Perturbed flow:** sum of G_ij at the current scenario.
- **Flow change:** aggregate percent change in total flow, displayed with explicit +/- sign and color-coded (blue for reduction, red for increase).
- **Trip multiplier distribution:** a small histogram (20 bins from 0.5 to 1.5) showing the spread of P_ij values across all pairs. This communicates that the effect is heterogeneous. At the baseline the histogram is a spike at 1.0; as WFH increases it fans out below 1.0.

### 5.7 Click-to-Inspect Panel

When the user clicks a hex on the map, a panel slides in from the right side of the screen (approximately 40% of viewport width). The map remains visible on the left with the selected hex highlighted.

The panel shows data for the clicked hex and its top commute partners. All content is programmatic (no LLM-generated text).

#### Panel Header

Hex ID (truncated) and a small locator showing the hex highlighted on a mini-map or just the lat/lng.

#### Section 1: Demographics

Two small horizontal bar charts side by side:

**Education Profile** (5 bars):
- Labels: Less than HS, HS Diploma, Some College, Bachelor's, Advanced
- Values: from `hex_metadata.json` `edu_shares`
- Highlight the largest bin

**Industry Profile** (5 bars, using the 4+1 grouping):
- 4 bars for the top industries by share (labeled with sector name)
- 1 bar for "Other" (sum of remaining 16 sectors)
- Values: from `hex_metadata.json` `ind_top4` and `ind_other_share`

#### Section 2: Top Commute Partners

A table showing the 5 OD pairs involving this hex with the largest absolute flow change at the current operating point:

| Partner Hex | Direction | T_ij | P_ij | Delta Flow |
|---|---|---|---|---|
| 872a...3df | Outbound | 2,200 | 0.68 | -704 |
| 872a...1af | Inbound | 1,800 | 0.71 | -522 |
| ... | | | | |

"Direction" indicates whether the clicked hex is the origin (outbound) or destination (inbound).

#### Section 3: Why This P Value

For the top partner (or whichever row the user hovers), show the mechanistic breakdown:

- **Omega_ij** and **Omega_ji** values with labels indicating which direction is which ("residents here -> jobs there" vs "residents there -> jobs here").
- **L_ij** and **L_ji** commute weights, and whether the weighted or equal-weight fallback was used.
- **P_ij** = the symmetric combination, shown as a formula with the actual numbers filled in. For weighted: `P = (L_ij * Omega_ij + L_ji * Omega_ji) / (L_ij + L_ji)`. For fallback: `P = (Omega_ij + Omega_ji) / 2`.

This replaces the natural-language explanation with a compact numeric breakdown that traces the result back to the inputs.

#### Close Button

An X in the top-right corner of the panel, or clicking elsewhere on the map, closes the panel.


## 6. Data Export Tab

A small "Export" button in the bottom-right corner. Clicking it opens a dropdown with links to download:

- `hex_geometries.geojson`
- `pairs_x_sweep.csv`
- `hex_summary.csv`

These are the same files produced by the precomputation pipeline. Since the app is static, these are just direct file links. This gives Cafer one-click access to the data during the demo without needing to find the files on disk.


## 7. Precomputation Script

The precomputation should be a single Python script, e.g., `scripts/precompute_viz_data.py`, that:

1. Accepts command-line arguments for: study area FIPS codes (default: Queens 36081), H3 resolution (default: 7), number of X steps (default: 100), output directory (default: `viz_data/`).
2. Runs the full data acquisition and hex conversion pipeline.
3. Performs the X sweep.
4. Writes all output files.
5. Prints a summary: number of hexes, number of pairs, file sizes, total runtime.

The script should use the existing cache (`~/.wfh_perturbation_cache`) so that repeated runs skip the download step.

### Expected Performance

On a MacBook M3 Pro (36 GB unified memory):

- Data acquisition (first run): 3–5 minutes (dominated by LODES file download).
- Data acquisition (cached): < 30 seconds.
- Hex conversion: 1–2 minutes (TIGER shapefile processing).
- X sweep (100 operating points, ~2000 pairs): < 60 seconds total.
- File writing: < 5 seconds.

Peak memory usage: 2–4 GB during shapefile processing. Well within 36 GB.


## 8. Implementation Notes

### Hex Geometry Generation

Use the `h3` Python library to generate hex boundaries:

```python
import h3

def hex_to_geojson_feature(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    # h3 returns (lat, lng) pairs; GeoJSON needs [lng, lat]
    coords = [[lng, lat] for lat, lng in boundary]
    coords.append(coords[0])  # close the ring
    return {
        "type": "Feature",
        "properties": {
            "hex_id": hex_id,
            "centroid_lat": h3.cell_to_latlng(hex_id)[0],
            "centroid_lng": h3.cell_to_latlng(hex_id)[1],
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [coords],
        },
    }
```

### Baseline Flow Proxy

LODES OD counts are a sample (not total commuters). For the visualization, this is acceptable because P_ij values are independent of flow magnitude. G_ij scales linearly with T_ij, so the relative pattern across corridors is correct even if absolute numbers are approximate. Document this caveat in the UI (a small footnote: "Baseline flows from LODES OD data; absolute magnitudes are approximate").

### Frontend Data Loading

Load JSON files with `fetch()` on app mount. The snapshots file is the largest (~10–30 MB). On a local filesystem this loads in under a second. If serving over a network, consider splitting snapshots into per-operating-point files, but for a Zoom demo from a local machine this is unnecessary.

### Color Scale

Use d3-scale's `scaleSequential` with the `interpolateRdBu` (reversed, so blue = negative) or a custom diverging scale. Anchor at 0. Fix the domain to the global min/max across all snapshots so that color meaning is stable as the slider moves.

### Mapbox Token

A free Mapbox token allows 50,000 map loads/month. For a demo tool this is more than sufficient. Store the token in a `.env` file that is not committed to git. The README should note that users need to supply their own token.


## 9. File Structure

```
utech-wfh-analyzer/
├── wfh_perturbation/        # existing module (no changes needed)
├── scripts/
│   └── precompute_viz_data.py
├── viz/
│   ├── index.html
│   ├── app.jsx              # single-file React app
│   ├── package.json
│   └── .env                 # MAPBOX_TOKEN (gitignored)
├── viz_data/                # generated by precompute script
│   ├── hex_geometries.geojson
│   ├── snapshots.json
│   ├── hex_metadata.json
│   ├── pairs_x_sweep.csv
│   └── hex_summary.csv
└── docs/
    └── visualization_tool_spec.md   # this file
```


## 10. Out of Scope

- Real-time computation in the browser. All perturbation math runs in Python during precomputation.
- Deep Gravity integration. Baseline flows use LODES OD data as a proxy.
- Multi-borough or full-metro-area scale. The tool is designed for one borough. Scaling to the full NYC metro area would increase the OD matrix significantly and may require chunked loading or server-side filtering.
- Authentication or deployment. This is a local demo tool, not a hosted service.
