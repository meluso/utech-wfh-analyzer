# WFH Perturbation Module — Requirements Specification

**Project:** uTECH-Cities — Post-Generation Behavioral Perturbation Framework
**Version:** 0.1 (Draft)
**Date:** 2026-02-24
**Authors:** John Ameluso, with input from Claude (Anthropic)

## 1. Purpose

This document specifies the requirements for a software module that implements the Work-From-Home (WFH) post-generation behavioral perturbation framework described in the project methods section. The module shall automate the data acquisition, processing, and computation steps that were manually validated using the companion Excel workbook (`WFH_Perturbation_Framework_Test.xlsx`). Its primary function is to accept Deep Gravity baseline flows (defined over hex cells or another target spatial unit) and produce perturbed flows reflecting a WFH scenario parameterized by a scaling factor α. Because the source demographic data (ACS, LODES) is defined over census tracts while Deep Gravity operates on hex cells, the module must also manage the spatial conversion between these geographies.

## 2. Scope

The module covers five functional areas: (A) acquisition of demographic and commute data from public sources, (B) processing of raw data into tract-level input vectors, (C) spatial conversion of tract-level inputs to the target spatial units used by the flow model (e.g., H3 hex cells), (D) computation of perturbed flows for all spatial-unit pairs, and an optional fifth area (E) that implements the aggregate scenario solver to find α given a target percent change in total flows.

The module does **not** cover the Deep Gravity model itself, the internal logic of the spatial conversion (which is accepted as an external function), or any visualization/reporting of results.

## 3. Definitions

| Term | Meaning |
|------|---------|
| Tract | A census tract identified by an 11-digit FIPS GEOID. The native spatial unit for ACS and LODES data |
| Spatial unit | The geography over which the perturbation computation operates. During validation this is a census tract; in production this is typically an H3 hex cell or similar grid unit |
| Conversion function | An externally provided function that translates tract-level demographic vectors and commute weights to spatial-unit-level equivalents |
| Study area | The set of spatial units for which perturbation is computed |
| e | Education level index (1–5) |
| o | Industry sector index (1–20, corresponding to LODES CNS01–CNS20) |
| w_e, u_e | Baseline WFH rate and structural upper bound by education level |
| w_o, u_o | Baseline WFH rate and structural upper bound by industry sector |
| w_eo, u_eo | Joint baseline propensity and joint upper bound for segment (e, o) |
| E_re | Share of residents in spatial unit r with education level e. Derived from ACS tract data via the conversion function |
| O_so | Share of jobs in spatial unit s in industry sector o. Derived from LODES WAC tract data via the conversion function |
| L_ij | Commute weight: observed workers residing in spatial unit i, employed in spatial unit j. Derived from LODES OD tract data via the conversion function |
| T_ij | Deep Gravity baseline flow between spatial units i and j |
| α | Proportional WFH scaling factor (scenario parameter) |
| W_eo | Perturbation weight for segment (e, o) given α |
| Ω_ij | Aggregate perturbation factor for workers residing in i, working in j |
| P_ij | Symmetric perturbation factor for the spatial-unit pair (i, j) |
| G_ij | Perturbed flow: G_ij = T_ij × P_ij |

## 4. Requirements

Requirements are organized by functional area. Each requirement uses a unique identifier (e.g., DA-1 for Data Acquisition requirement 1). Verification methods are specified alongside each requirement.

---

### 4.A — Data Acquisition

**DA-1.** The module shall retrieve educational attainment data from the U.S. Census Bureau API (ACS 5-Year, Table B15003) for any set of tracts specified by their 11-digit FIPS GEOIDs. The module shall require a Census Bureau API key, which must be provided as a configuration input (e.g., environment variable or config file) and not hardcoded. API keys are free and can be obtained at `https://api.census.gov/data/key_signup.html`.

*Verification:* For each of the six tracts used in the Excel workbook (36061000700, 36061018400, 34003005000, 36061010000, 48453001101, 48453002422), query the API and confirm the returned counts match the values in the ACS data files downloaded during manual validation. Also confirm the module raises an informative error if no API key is configured.

**DA-2.** The module shall download LODES Workplace Area Characteristics (WAC) files from the LEHD public data directory for any state and year, using the predictable URL structure `https://lehd.ces.census.gov/data/lodes/LODES8/{state_abbr}/wac/{state_abbr}_wac_S000_JT00_{year}.csv.gz`.

*Verification:* Download the NY, NJ, and TX WAC files for 2023 and confirm file sizes and row counts match those of the manually downloaded copies.

**DA-3.** The module shall download LODES Origin-Destination (OD) main files from the LEHD public data directory for any state and year, using the URL structure `https://lehd.ces.census.gov/data/lodes/LODES8/{state_abbr}/od/{state_abbr}_od_main_JT00_{year}.csv.gz`.

*Verification:* Same approach as DA-2.

**DA-4.** The module shall identify which state OD file(s) to download based on the **residence** state of each tract in the study area, not the workplace state. For cross-state tract pairs, the module shall download OD files for every state that contains at least one residence tract.

*Context:* LODES OD files are organized by state of residence. A New Jersey resident commuting to New York appears in the NJ OD file. Failing to account for this produces missing cross-state flows.

*Verification:* For the Bergen NJ ↔ Midtown Manhattan pair, confirm the module queries both the NJ and NY OD files. Extract the flows and confirm they match the values obtained during chunked extraction (0 in both directions for this specific pair).

**DA-5.** The module shall accept the shared WFH parameter vectors (w_e, u_e, w_o, u_o) as versioned configuration inputs rather than fetching them on every run. The module shall ship with pre-populated default values (see Section 6, "Pre-Populated Defaults") so that users are not required to supply these vectors unless they wish to override them.

*Context:* Education-level telework rates (w_e, u_e) and industry-level telework rates (w_o, u_o) come from CPS and Dingel-Neiman (2020), respectively. These sources are updated infrequently and require manual interpretation (e.g., mapping CPS industry categories to LODES CNS codes). Treating them as configuration rather than live-fetched data avoids fragile scraping and ensures researchers consciously review updates. The pre-populated defaults reduce setup friction while still allowing overrides.

*Verification:* Confirm the module loads these vectors from a configuration file or explicit function arguments, and that changing the configuration produces different perturbation results. Confirm the module runs successfully with no user-supplied parameter vectors (using built-in defaults).

**DA-6.** The module shall support local caching of downloaded LODES files so that repeated runs against the same study area and year do not re-download multi-gigabyte files.

*Verification:* Run the module twice on the same study area. Confirm the second run does not issue HTTP requests for files already cached, and produces identical results.

**DA-7.** The module shall record the vintage (source and year) of each dataset used in a given run, producing a metadata record that enables reproducibility.

*Context:* ACS, LODES, and CPS are released on different schedules with different lag times. LODES 2023 is current as of early 2026 but will eventually be superseded. Pinning vintages is essential for reproducible research.

*Verification:* Inspect the metadata output of a run and confirm it lists specific vintage identifiers for all data sources.

---

### 4.B — Data Processing

**DP-1.** The module shall collapse the detailed ACS B15003 educational attainment categories into five bins: (1) Less than high school, (2) High school diploma or equivalent, (3) Some college or associate's degree, (4) Bachelor's degree, (5) Advanced degree (master's, professional, doctorate).

*Context:* Table B15003 contains approximately 25 line items. The crosswalk mapping these to five bins is defined as a configuration artifact per DP-6.

*Verification:* For each of the six validation tracts, compute education shares using the module's crosswalk and confirm they match the values in `real_data.py` (EDU_SHARES) to within ±0.001.

**DP-2.** The module shall compute industry shares for each tract by dividing each CNS01–CNS20 job count from the WAC file by the tract's total job count (C000 or the sum of CNS01–CNS20).

*Verification:* For the six validation tracts, confirm industry shares match `real_data.py` (IND_SHARES) to within ±0.001, and confirm shares sum to 1.0 ± 0.005 for each tract.

**DP-3.** The module shall handle tracts with zero total employment in the WAC file by producing a vector of twenty zeros for industry shares, rather than raising a division-by-zero error.

*Verification:* Introduce a tract FIPS known to have zero WAC employment. Confirm the module returns a zero vector and does not error.

**DP-4.** The module shall aggregate LODES OD block-level flows to tract-level flows by truncating the 15-digit w_geocode and h_geocode fields to their first 11 digits and summing the S000 column.

*Verification:* For the six directed tract pairs in the validation set, confirm aggregated counts match those obtained via chunked extraction: (36061018400 → 36061000700) = 23, (48453002422 → 48453001101) = 154, and all others = 0.

**DP-5.** The module shall process LODES OD files using chunked or streaming I/O, filtering to relevant tracts during read, rather than loading entire state files into memory.

*Context:* State-level OD files can exceed 1 GB uncompressed. A naive full-load approach caused an out-of-memory crash (exit code 137) during manual validation with the NY OD file.

*Verification:* Process the NY OD file on a machine with ≤4 GB available memory and confirm successful completion without OOM.

**DP-6.** The module shall define the B15003-to-five-bin crosswalk and the CPS-to-LODES industry mapping as a clearly documented configuration artifact (e.g., a YAML, JSON, or CSV file), not as inline code constants.

*Context:* The purpose of externalizing these mappings is scientific verifiability — a reviewer or collaborator should be able to inspect exactly which ACS line items map to which education bins, and which CPS categories correspond to which LODES industry codes, without reading processing logic. This is not a defensive measure against future Census table restructuring, which is unlikely to affect this project.

---

### 4.C — Spatial Conversion

**SC-1.** The module shall accept an externally provided spatial conversion function (or module) that translates tract-level data to the target spatial units used by the flow model. The module shall not implement the conversion logic itself.

*Context:* Census tracts and hex cells (e.g., H3) do not align — tracts have irregular boundaries while hexes tile the plane uniformly. The conversion involves areal interpolation, population-weighted allocation, or similar techniques whose design depends on decisions not yet finalized (see OD-5). By accepting the conversion as an external dependency, this module remains decoupled from those decisions.

*Verification:* Confirm the module accepts a conversion function as input and invokes it to transform tract-level vectors before computation. Confirm that substituting a different conversion function (e.g., identity for tract-to-tract validation vs. areal interpolation for tract-to-hex) produces appropriately different results.

**SC-2.** The conversion function shall, at minimum, accept tract-level education share vectors (E_re, 5 values per tract), industry share vectors (O_so, 20 values per tract), and commute weight matrices (L_ij, sparse) and return equivalent vectors and matrices indexed by the target spatial units.

*Context:* The conversion must preserve the semantic meaning of each input. Education shares must remain residence-based distributions that sum to 1 for each spatial unit. Industry shares must remain workplace-based distributions that sum to 1. Commute weights must remain non-negative and reflect the directional flow from residence to workplace.

*Verification:* After conversion, confirm that education shares sum to 1.0 ± 0.01 for each target spatial unit, industry shares sum to 1.0 ± 0.01, and commute weights are non-negative.

**SC-3.** For validation and testing purposes, the module shall support a **tract-to-tract identity conversion** — a trivial conversion function that passes tract-level data through unchanged, allowing the perturbation computation to operate directly on tracts.

*Context:* The Excel workbook validation operates entirely in tract space. The identity conversion allows the programmatic module to reproduce the workbook results exactly, without requiring a hex conversion implementation.

*Verification:* Using the identity conversion, confirm the module produces P_ij and G_ij values matching the Excel workbook test cases.

**SC-4.** The conversion function shall preserve the residence/workplace directionality of the source data. Education shares describe where people **live**; industry shares describe where people **work**. The conversion must maintain this distinction — a tract's education shares are allocated to spatial units based on residential population overlap, while industry shares are allocated based on workplace/employment overlap.

*Context:* If the conversion naively uses the same spatial allocation weights for both education and industry, it would conflate residence and workplace geographies. In areas where people live and work in different places (most areas), this would introduce systematic error.

*Verification:* For a study area where residential and employment distributions differ substantially (e.g., a downtown employment center adjacent to residential neighborhoods), confirm that the converted education and industry vectors differ in their spatial distribution — i.e., the conversion is not applying the same weights to both.

---

### 4.D — Perturbation Computation

*Note:* The requirements in this section are geometry-agnostic — the math is the same whether the spatial units are census tracts, hex cells, or any other geography. The inputs (E_re, O_so, L_ij) arrive from the spatial conversion layer (4.C) already expressed in the target spatial units. During validation against the Excel workbook, the identity conversion (SC-3) is used, so the spatial units are tracts. References to "tracts" in verification steps refer to this validation configuration.

**PC-1.** The module shall compute the joint baseline WFH propensity matrix w_eo as: `w_eo = 1 − (1 − w_e)(1 − w_o)` for all 5 × 20 education-industry segments.

*Verification:* Compare the 100 computed values against the Parameters sheet of the Excel workbook (Section 3, rows 38–57) to within ±0.0001.

**PC-2.** The module shall compute the joint upper bound matrix u_eo as: `u_eo = 1 − (1 − u_e)(1 − u_o)` for all segments.

*Verification:* Compare against the Parameters sheet (Section 4, rows 62–81) to within ±0.0001.

**PC-3.** Given a scalar α, the module shall compute bounded perturbation deltas as: `Δw_eo = max(−w_eo, min(α · w_eo, u_eo − w_eo))` for all segments.

*Context:* The three-way max/min enforces that (a) WFH rates cannot go below zero, (b) the change is proportional to the baseline, and (c) WFH rates cannot exceed the structural upper bound.

*Verification:* For α = 0.25, compare the 100 Δw_eo values against the Excel workbook's Step 2 tables to within ±0.0001. Also test with α = −0.5 (reduction scenario) and α = 2.0 (aggressive increase that should hit many upper bounds) and confirm bounds are respected: w_eo + Δw_eo ∈ [0, u_eo] for all segments.

**PC-4.** The module shall compute perturbation weights as: `W_eo = 1 − Δw_eo / (1 − w_eo)` for all segments where w_eo < 1. If w_eo = 1 for any segment (meaning 100% baseline WFH), the module shall set W_eo = 1 (no perturbation possible, since those workers already don't commute).

*Context:* The denominator (1 − w_eo) approaches zero as w_eo → 1. In practice, w_eo < 1 for all realistic parameter combinations since both w_e and w_o are strictly less than 1, but the guard is necessary for robustness against unusual configurations.

*Verification:* Compare against Step 3 tables in the Excel workbook to within ±0.0001. Additionally, test with an artificially constructed parameter set where w_e = 0.99 and w_o = 0.99 for one segment and confirm no division-by-zero error.

**PC-5.** The module shall enforce the directional convention that education shares (E_re) describe the **residence** tract and industry shares (O_so) describe the **workplace** tract. For a directed flow from residence i to workplace j, Ω_ij uses education shares from tract i and industry shares from tract j. For the reverse direction, Ω_ji uses education shares from tract j and industry shares from tract i.

*Context:* This directionality is fundamental to the framework and was a major point of clarification during methods development. Education attainment comes from ACS, which reports by place of residence. Industry composition comes from LODES WAC, which reports by place of work. Mixing these up (e.g., using workplace education or residence industry) would produce incorrect perturbation factors.

*Verification:* For Example 1 (Tract 7 ↔ Tract 184), confirm that Ω_ij uses Tract 7's education shares with Tract 184's industry shares, while Ω_ji uses Tract 184's education shares with Tract 7's industry shares. Swapping the assignments should produce detectably different Ω values.

**PC-6.** The module shall precompute the intermediate vector φ_e(s) for every tract s that appears as a workplace in the study area, defined as: `φ_e(s) = Σ_o W_eo · O_so` — the industry-weighted perturbation at workplace tract s for each education level e.

*Context:* This decomposition avoids redundant computation. The W_eo matrix is 5 × 20 and computed once. Each workplace tract s contributes a 5-element φ vector. Ω_ij is then a dot product between the residence education vector and the workplace φ vector, making the per-pair computation O(5) rather than O(100).

*Verification:* For the six tracts in the validation set, compare φ vectors against the Excel workbook's Step 4 φ rows to within ±0.0001.

**PC-7.** The module shall compute the directional aggregate perturbation factor as: `Ω_ij = Σ_e E_ie · φ_e(s=j)` for each directed pair where i is the residence tract and j is the workplace tract.

*Verification:* Compare Ω_ij and Ω_ji values for the three example pairs against the Excel workbook's Step 4 results to within ±0.0001.

**PC-8.** The module shall compute the symmetric perturbation factor as: `P_ij = (L_ij · Ω_ij + L_ji · Ω_ji) / (L_ij + L_ji)` when L_ij + L_ji > 0. The construction shall guarantee P_ij = P_ji (symmetry), meaning the perturbation factor is the same regardless of which direction a trip is labeled.

*Verification:* Compare P_ij for Examples 1 and 3 against the Excel workbook to within ±0.0001. Additionally, for each pair, verify P_ij = P_ji by computing both orderings and confirming equality.

**PC-9.** The module shall apply a configurable fallback policy when L_ij + L_ji = 0. The default fallback shall be equal weighting: `P_ij = (Ω_ij + Ω_ji) / 2`.

*Context:* LODES tract-to-tract flows are sparse. Many pairs for which Deep Gravity produces nonzero T_ij will have zero observed LODES commuters, especially for pairs with small flows or after LODES noise infusion. The fallback policy should be an explicit, documented design choice.

*Verification:* For Example 2 (Bergen ↔ Midtown, both L values = 0), confirm the module produces P_ij = (Ω_ij + Ω_ji) / 2 and that this matches the Excel workbook result (0.6598) to within ±0.001. Also confirm the fallback policy is configurable by substituting an alternative (e.g., employment-proportional weighting) and observing a different P_ij.

**PC-10.** The module shall compute perturbed flows as: `G_ij = T_ij × P_ij` for every tract pair with a nonzero Deep Gravity baseline flow.

*Verification:* Covered by the end-to-end test cases in Section 5.

**PC-11.** The module shall ensure that the W_eo matrix and φ vectors are computed once per run (not redundantly per tract pair), and that per-pair computation is limited to dot products and the P_ij combination step.

*Verification:* Profile the module on a study area with N ≥ 1,000 tracts. Confirm that wall-clock time scales approximately with the number of nonzero T_ij pairs, not with N² × 100.

---

### 4.E — Aggregate Scenario Solver (Optional)

**AS-1.** The module shall, given a target percent change X in total flows across the study area, solve for the scalar α that produces that target.

*Context:* This corresponds to Section 5 of the methods. A transportation planner may specify "I want to model a 10% reduction in total commute trips" rather than choosing α directly.

**AS-2.** The solver shall find α by applying a standard monotone root-finding method (e.g., bisection or Brent's method) to the function `f(α) = X(α) − X_target`, where X(α) is evaluated by running the full perturbation pipeline (Steps PC-1 through PC-10) for a given α and computing the resulting percent change in total flow. The search domain is `α ∈ [−1, α_max]`, where α_max is the largest breakpoint `(u_eo − w_eo) / w_eo` across all segments.

*Context:* X(α) is monotonically decreasing (more WFH → fewer trips) and piecewise linear, so any monotone root-finder will converge reliably. Bisection guarantees convergence in ~40 iterations for ±0.001 precision; Brent's method typically converges in 10–15. Each iteration evaluates the full pipeline once, which is fast once demographics are loaded. Most scientific computing libraries provide robust implementations (e.g., `scipy.optimize.brentq` in Python).

*Verification:* For a given study area, compute X(α) at α values of 0.0, 0.1, 0.2, ..., 2.0. Then use the solver to find α for each of those X values and confirm round-trip accuracy to within ±0.001.

**AS-3.** The solver shall report infeasibility when the target X exceeds the maximum achievable reduction (i.e., when all segments are saturated at their upper bounds) or the maximum achievable increase (all segments at their lower bound of zero WFH).

*Verification:* Request a target X that exceeds the feasible range. Confirm the solver returns an informative error rather than a nonsensical α.

**AS-4.** The solver does not require an analytical slope formula. Each evaluation of X(α) runs the full perturbation pipeline, which correctly handles saturation bounds at every α value. The root-finder treats X(α) as a black-box monotone function.

*Context:* A closed-form expression for dX/dα exists and is documented in the companion file `Derivation_Aggregate_Solver_Slope.md` for reference. It confirms that X(α) is piecewise linear and monotonically decreasing, which justifies the use of a simple root-finder. However, implementing the closed-form slope is not required — the root-finding approach is simpler, uses well-validated library code, and converges quickly enough for research use.

---

### 4.F — Interface and Integration

**IE-1.** The module's primary interface shall accept: (a) a list of tract FIPS codes defining the study area, (b) a vintage year for LODES and ACS data, (c) the shared parameter vectors w_e, u_e, w_o, u_o, (d) a scalar α or a target X with a flag indicating which mode to use, (e) a set of Deep Gravity baseline flows T_ij (as a sparse structure indexed by spatial-unit pairs), and (f) a spatial conversion function conforming to SC-1/SC-2 (defaulting to the identity conversion of SC-3 if none is provided).

*Verification:* Confirm that omitting the conversion function defaults to identity (tract-to-tract) mode and produces results matching the Excel workbook test cases.

**IE-2.** The module shall return, at minimum: (a) the perturbed flows G_ij for every input pair, (b) the P_ij values for every input pair, and (c) the metadata record described in DA-7.

**IE-3.** The data acquisition layer shall be separable from the computation layer, so that a user can run acquisition once, cache results locally, and iterate on computation parameters (α, fallback policy, etc.) without re-downloading.

*Verification:* Run acquisition for a study area, then run computation five times with different α values. Confirm no network requests occur during the computation-only runs.

**IE-4.** The module shall not assume a specific programming language. Requirements are specified in terms of mathematical operations, data formats, and interface contracts, not language-specific constructs.

*Context:* The implementation language will be determined by the development team based on existing project infrastructure.

---

## 5. Validation Test Cases

The following test cases, drawn from the companion Excel workbook, shall serve as the primary validation suite. All use α = 0.25 and the shared parameter vectors defined in the workbook's Parameters sheet.

| Test Case | Zone i | Zone j | Expected P_ij | Expected % Change |
|-----------|--------|--------|----------------|-------------------|
| Ex1: NYC Intra-City | 36061000700 | 36061018400 | 0.6814 | −31.86% |
| Ex2: NYC Metro | 34003005000 | 36061010000 | 0.6598 | −34.02% |
| Ex3: Austin TX | 48453001101 | 48453002422 | 0.6933 | −30.67% |

Additional edge-case tests:

| Condition | Expected Behavior |
|-----------|-------------------|
| α = 0 | P_ij = 1.0 for all pairs (no perturbation) |
| α > 0, all segments saturate | Δw_eo = u_eo − w_eo for all (e, o) |
| α < 0 | WFH decreases; P_ij > 1.0 (more trips) |
| L_ij + L_ji = 0 | Fallback policy applies |
| Tract with zero WAC employment | Industry shares = zero vector; Ω contributions from that workplace are zero |
| Single-tract study area (i = j) | Module handles self-loops without error |

## 6. Data Source Reference

| Dataset | Source | Access Method | Key Fields |
|---------|--------|---------------|------------|
| Education by residence | ACS 5-Year, Table B15003 | Census API (`api.census.gov`) | ~25 attainment categories → 5 bins |
| Industry by workplace | LODES WAC (S000, JT00) | LEHD file server (HTTPS) | CNS01–CNS20 job counts |
| Commute flows | LODES OD Main (S000, JT00) | LEHD file server (HTTPS) | h_geocode, w_geocode, S000 |
| Telework by education | CPS supplements | Versioned config input | 5 rates + 5 upper bounds |
| Telework by industry | CPS supplements | Versioned config input | 20 rates + 20 upper bounds |
| Task feasibility bounds | Dingel-Neiman (2020) | Versioned config input | Upper bounds by education and industry |

### Manual Data Source Links

The following URLs were used during manual validation to download the data that populates the Excel workbook. They are recorded here for reproducibility and to guide future data updates.

- **ACS Educational Attainment (B15003):** https://data.census.gov/table/ACSDT5Y2024.B15003
- **LODES WAC and OD files:** https://lehd.ces.census.gov/data/ (LODES 8, by state, WAC and OD directories, job type JT00, year 2023)
- **CPS Telework Rates (August 2024):** https://www.bls.gov/news.release/archives/empsit_09062024.htm

### Pre-Populated Defaults

The following values were extracted during manual validation and should ship as built-in defaults in the module's configuration. They may be overridden by the user but do not need to be re-derived on every run.

**Education-level WFH parameters (w_e, u_e):** These 5-element vectors are derived from CPS and Dingel-Neiman (2020). They change only when new CPS supplements are published or the education bin definitions are revised.

| Education Level | Baseline w_e | Upper Bound u_e |
|----------------|-------------|-----------------|
| Less than HS | 0.035 | 0.098 |
| HS Diploma | 0.085 | 0.183 |
| Some College/Assoc. | 0.183 | 0.317 |
| Bachelor's | 0.384 | 0.556 |
| Advanced | 0.436 | 0.674 |

**Industry-level WFH parameters (w_o, u_o):** These 20-element vectors map CPS telework rates (August 2024) and Dingel-Neiman upper bounds to LODES CNS codes. They change only when CPS publishes updated telework supplements.

| LODES Code | Industry | Baseline w_o | Upper Bound u_o |
|-----------|----------|-------------|-----------------|
| CNS01 | Agriculture, Forestry, Fishing | 0.123 | 0.20 |
| CNS02 | Mining, Quarrying, Oil/Gas | 0.162 | 0.25 |
| CNS03 | Utilities | 0.277 | 0.37 |
| CNS04 | Construction | 0.089 | 0.19 |
| CNS05 | Manufacturing | 0.196 | 0.22 |
| CNS06 | Wholesale Trade | 0.234 | 0.52 |
| CNS07 | Retail Trade | 0.110 | 0.14 |
| CNS08 | Transportation & Warehousing | 0.080 | 0.19 |
| CNS09 | Information | 0.500 | 0.72 |
| CNS10 | Finance & Insurance | 0.595 | 0.76 |
| CNS11 | Real Estate & Rental/Leasing | 0.421 | 0.60 |
| CNS12 | Professional, Scientific, Tech | 0.597 | 0.80 |
| CNS13 | Management of Companies | 0.199 | 0.79 |
| CNS14 | Admin/Support/Waste Mgmt | 0.199 | 0.31 |
| CNS15 | Educational Services | 0.197 | 0.83 |
| CNS16 | Healthcare & Social Assistance | 0.181 | 0.25 |
| CNS17 | Arts, Entertainment, Recreation | 0.187 | 0.30 |
| CNS18 | Accommodation & Food Services | 0.043 | 0.08 |
| CNS19 | Other Services | 0.177 | 0.31 |
| CNS20 | Public Administration | 0.271 | 0.41 |

**B15003 education crosswalk:** The mapping from ACS Table B15003 line items to the five education bins is a fixed configuration artifact. The module should ship with the current crosswalk as a default (see DP-1, DP-6).

## 7. Known Limitations and Assumptions

**KL-1. ACS education data covers population 25 and older.** Table B15003 reports educational attainment for the population aged 25+. Workers under 25 are excluded from the education distribution used in this framework. This is standard practice in labor economics (educational attainment is unstable for younger workers still in school), but it means the framework slightly misrepresents the education mix of the commuting workforce in areas with large under-25 working populations (e.g., college towns, service-heavy districts).

**KL-2. CPS industry grouping is coarser than LODES.** The CPS telework tables combine NAICS 55 (Management of Companies) and NAICS 56 (Administrative/Support/Waste Management) into a single reporting category. As a result, CNS13 and CNS14 currently share the same baseline telework rate (19.9%). These are substantively different industries — Management of Companies (CNS13) likely has higher telework potential than Admin/Waste (CNS14). If a more granular source becomes available, the configuration should be updated.

**KL-3. Upper bounds are approximate.** The structural upper bounds (u_e, u_o) derive from Dingel-Neiman (2020) O*NET task classifications, which estimate whether a job *can* be done from home. These are occupation-level estimates mapped to education and industry categories, introducing aggregation error. The joint upper bound formula u_eo = 1 − (1 − u_e)(1 − u_o) assumes independence between education and industry feasibility, which is an approximation.

**KL-4. LODES noise infusion affects small flows.** LODES applies noise infusion for disclosure avoidance. At the tract-to-tract level, this means small true flows (1–5 workers) may be reported as zero. The framework's fallback policy (PC-9) handles the zero case, but slightly distorted nonzero counts are used at face value.

**KL-5. Spatial conversion introduces approximation error.** Translating tract-level demographics to hex-level demographics is inherently approximate because the two geographies do not align. Any allocation method (areal, population-weighted, or otherwise) distributes a tract's aggregate shares across overlapping hexes using assumptions about within-tract homogeneity. In reality, demographics vary within tracts — a tract that is 50% bachelor's-degree holders overall may have one neighborhood at 70% and another at 30%. This within-tract heterogeneity is lost in the conversion. The magnitude of this error depends on the resolution of the hex grid relative to tract size; finer hex grids (higher H3 resolution) reduce the error by averaging over smaller areas.

**KL-6. Deep Gravity flows T_ij are undirected.** The perturbation framework treats T_ij as a symmetric baseline flow (T_ij = T_ji). The directional asymmetry of commuting is captured through the LODES-weighted P_ij computation, not through T_ij itself.

## 8. Open Decisions

The following items require determination by the project team before or during implementation. They are flagged here because the spreadsheet validation did not resolve them.

**OD-1. CPS-to-LODES mapping for CNS13/CNS14.** Accept the shared rate (19.9% for both) or seek an alternative source to distinguish Management of Companies from Admin/Waste? Possibilities include BLS Occupational Employment Statistics or American Time Use Survey microdata, but these would add complexity to the data pipeline. These sectors are small shares of most tracts' employment, so the impact on P_ij is likely modest.

**OD-2. Spatial conversion approach.** The module accepts the tract-to-hex conversion as an external function (SC-1), but the design of that function is not yet determined. Key questions include: (a) What allocation method — areal interpolation (simple area-weighted), population-weighted (using a gridded population surface), or employment-weighted (using a separate employment raster)? (b) Should education shares and industry shares use *different* allocation weights (residential population for education, employment density for industry) to preserve the residence/workplace distinction (see SC-4)? (c) How are LODES commute weights (L_ij) allocated — proportionally across all hex pairs that overlap the source tract pair, or concentrated in the hex pair with the most overlap? These decisions affect the accuracy of the perturbation at the hex level and should be made in consultation with whoever is building the Deep Gravity pipeline.

**OD-3. Aggregate solver in hex space.** The root-finding approach (AS-2) evaluates X(α) by running the full pipeline at each candidate α. At hex resolution, each evaluation iterates over all hex pairs, which may be substantially more expensive than at tract resolution. The team should assess whether the solver is needed at full hex resolution or whether a tract-level approximation of α is sufficient (find α using tract-level aggregates, then apply it at hex resolution for the per-pair G_ij computation). Since α is a global scalar, the tract-level approximation may be adequate.
