# Derivation: Slope of X(α) for the Aggregate Scenario Solver

**Purpose:** Derive the exact slope dX/dα of the total-flow percent change X as a function of the scaling factor α. This slope is needed by the breakpoint-walk algorithm (AS-2 in the module specification) to find the α that achieves a target X.

**Companion documents:** Methods section (Sections 4–5), Module specification (Section 4.D), Excel workbook (Steps 1–5).

---

## 1. Setup and Notation

Let S = Σ_ij T_ij denote the total baseline flow across the network (a constant). The percent change in total flow is:

    X(α) = [ Σ_ij T_ij · P_ij(α) ] / S  −  1

So the slope we need is:

    dX/dα = (1/S) · Σ_ij T_ij · dP_ij/dα

The task is to compute dP_ij/dα by applying the chain rule through the computation pipeline:

    α  →  Δw_eo  →  W_eo  →  φ_e(s)  →  Ω_ij  →  P_ij

Between consecutive breakpoints, every step in this chain is linear in α, so the chain rule gives a constant slope within each interval.

---

## 2. Directional Weight Convention

Before proceeding, define the directional weight λ_ij to unify the standard case (L_ij + L_ji > 0) and the fallback case (L_ij + L_ji = 0):

    λ_ij = L_ij / (L_ij + L_ji)       when L_ij + L_ji > 0
    λ_ij = 1/2                          when L_ij + L_ji = 0  (equal-weight fallback)

By construction, λ_ij + λ_ji = 1 for all pairs. The symmetric perturbation factor is then:

    P_ij = λ_ij · Ω_ij  +  λ_ji · Ω_ji

This holds for both cases without branching.

---

## 3. Chain Rule, Step by Step

### Step 1: α → W_eo

Let U ⊆ {1,...,5} × {1,...,20} denote the set of **unsaturated** segments at the current value of α. A segment (e, o) is unsaturated when neither the upper nor lower bound is binding, i.e., when −w_eo < α · w_eo < u_eo − w_eo.

For unsaturated segments, Δw_eo = α · w_eo, so:

    W_eo = 1 − α · w_eo / (1 − w_eo) = 1 − α · c_eo

where we define the shorthand:

    c_eo = w_eo / (1 − w_eo)

For saturated segments, W_eo is constant (either at its upper-bound value or lower-bound value), so dW_eo/dα = 0. Therefore:

    dW_eo/dα  =  −c_eo    if (e, o) ∈ U
                   0        if (e, o) ∉ U

### Step 2: W_eo → φ_e(s)

For any workplace tract s:

    φ_e(s) = Σ_o  W_eo · O_so

Differentiating:

    dφ_e(s)/dα  =  Σ_o  (dW_eo/dα) · O_so
                =  Σ_{o: (e,o) ∈ U}  (−c_eo) · O_so
                = −Σ_{o: (e,o) ∈ U}  c_eo · O_so

### Step 3: φ_e(s) → Ω_ij

For a directed flow from residence tract i to workplace tract j:

    Ω_ij = Σ_e  E_ie · φ_e(s = j)

Differentiating:

    dΩ_ij/dα  =  Σ_e  E_ie · dφ_e(s = j)/dα
              =  Σ_e  E_ie · [ −Σ_{o: (e,o) ∈ U}  c_eo · O_jo ]
              = −Σ_{(e,o) ∈ U}  c_eo · E_ie · O_jo

This is the key intermediate result: the sensitivity of the directional perturbation factor Ω_ij to α is a weighted sum over unsaturated segments, where each segment's contribution depends on the **residence** tract's education share (E_ie) and the **workplace** tract's industry share (O_jo).

### Step 4: Ω_ij → P_ij

    P_ij = λ_ij · Ω_ij  +  λ_ji · Ω_ji

Since λ_ij and λ_ji are constants (they depend on LODES counts, not on α):

    dP_ij/dα  =  λ_ij · dΩ_ij/dα  +  λ_ji · dΩ_ji/dα

Substituting from Step 3:

    dP_ij/dα  = −λ_ij · Σ_{(e,o) ∈ U}  c_eo · E_ie · O_jo
                −λ_ji · Σ_{(e,o) ∈ U}  c_eo · E_je · O_io

              = −Σ_{(e,o) ∈ U}  c_eo · [ λ_ij · E_ie · O_jo  +  λ_ji · E_je · O_io ]

### Step 5: P_ij → X

    dX/dα  =  (1/S) · Σ_ij  T_ij · dP_ij/dα

           =  −(1/S) · Σ_ij  T_ij · Σ_{(e,o) ∈ U}  c_eo · [ λ_ij · E_ie · O_jo + λ_ji · E_je · O_io ]

Swapping the order of summation (Σ_ij and Σ_{(e,o)}):

    dX/dα  =  −Σ_{(e,o) ∈ U}  c_eo · [ (1/S) · Σ_ij  T_ij · ( λ_ij · E_ie · O_jo + λ_ji · E_je · O_io ) ]

---

## 4. The Network Weight

Define the **network weight** of segment (e, o):

    ω_eo  =  (1/S) · Σ_ij  T_ij · ( λ_ij · E_ie · O_jo  +  λ_ji · E_je · O_io )

Then the slope takes a compact form:

    ┌─────────────────────────────────────────────────┐
    │                                                 │
    │   dX/dα  =  − Σ_{(e,o) ∈ U}  c_eo · ω_eo     │
    │                                                 │
    │   where  c_eo = w_eo / (1 − w_eo)              │
    │          ω_eo = network weight (defined above)  │
    │          U = set of unsaturated segments         │
    │                                                 │
    └─────────────────────────────────────────────────┘

**Interpretation:** Each education-industry segment (e, o) contributes to the slope in proportion to two factors: c_eo captures how sensitive the perturbation weight is to changes in α (segments with higher baseline WFH are more responsive), and ω_eo captures how much influence that segment has on total network flow (segments that are demographically prevalent in high-flow corridors matter more).

---

## 5. Properties (Self-Checks)

### 5.1. Sign

c_eo > 0 for all segments (since 0 < w_eo < 1), and ω_eo ≥ 0 (since T_ij, E_ie, O_jo, λ_ij are all non-negative). Therefore dX/dα ≤ 0 whenever U is nonempty. This is correct: increasing α (more WFH) reduces total trips.

### 5.2. α = 0

At α = 0, no segments are saturated (U = all segments), W_eo = 1 for all, φ_e(s) = Σ_o O_so = 1, Ω_ij = Σ_e E_ie = 1, P_ij = 1, and X = 0. The slope at α = 0 is dX/dα = −Σ_{all (e,o)} c_eo · ω_eo. This is the steepest the slope can be (subsequent saturation can only remove terms from the sum, making the slope less negative).

### 5.3. Homogeneous demographics

If all tracts have identical education shares E_e and industry shares O_o, then Ω_ij = Ω_ji for all pairs, P_ij is the same everywhere, and X(α) = P(α) − 1. In this case:

    ω_eo = (1/S) · Σ_ij T_ij · E_e · O_o · (λ_ij + λ_ji)  =  E_e · O_o

since λ_ij + λ_ji = 1 and (1/S) · Σ_ij T_ij = 1. So:

    dX/dα = −Σ_{(e,o) ∈ U} c_eo · E_e · O_o

Meanwhile, direct computation gives P = Σ_e E_e · Σ_o W_eo · O_o, and differentiating:

    dP/dα = −Σ_{(e,o) ∈ U} c_eo · E_e · O_o

These match. ✓

### 5.4. Single pair

If the network has just one pair (i, j) with flow T_ij, then S = T_ij (or 2T_ij if we count both directions — but this cancels in the ratio). The ω_eo formula reduces to:

    ω_eo = λ_ij · E_ie · O_jo  +  λ_ji · E_je · O_io

This is exactly the "effective demographic share" of segment (e, o) for this pair, weighted by the directional split. This is consistent with the per-pair computation in the spreadsheet.  ✓

### 5.5. Breakpoint structure

At each breakpoint α* where segment (e*, o*) saturates, the slope changes by:

    Δ(slope) = +c_{e*o*} · ω_{e*o*}

The slope becomes less negative (closer to zero), which is correct: once a segment saturates, further increases in α don't affect that segment's contribution, so the marginal reduction in trips diminishes.

---

## 6. The Complete Algorithm

**Precomputation (once per study area):**

1. Compute c_eo = w_eo / (1 − w_eo) for all 100 segments.
2. Compute λ_ij for all tract pairs (from LODES counts and fallback policy).
3. Compute ω_eo = (1/S) · Σ_ij T_ij · (λ_ij · E_ie · O_jo + λ_ji · E_je · O_io) for all 100 segments.
4. Compute the upper breakpoints: α_eo^+ = (u_eo − w_eo) / w_eo for all segments.
5. Sort the positive breakpoints in ascending order. (There is also a single lower breakpoint at α = −1 where all segments simultaneously hit the zero-WFH floor.)

**Solver (given target X):**

6. Start at α = 0 where X = 0.
7. Initialize slope = −Σ_{all (e,o)} c_eo · ω_eo.
8. Walk forward (if target X < 0) or backward (if target X > 0) through breakpoints:
    - At each breakpoint α*, compute the X value at that breakpoint using the current slope:
      X(α*) = X(α_prev) + slope · (α* − α_prev)
    - If the target X falls within the current interval [X(α_prev), X(α*)], solve linearly:
      α_target = α_prev + (X_target − X(α_prev)) / slope
    - Otherwise, update the slope by removing the saturated segment:
      slope ← slope + c_{e*o*} · ω_{e*o*}
    - Continue to the next breakpoint.
9. If all breakpoints are exhausted without reaching the target, report infeasibility.

**Complexity:** The precomputation of ω_eo in step 3 is O(100 · |pairs|). The sort in step 5 is O(100 · log 100). The walk in steps 6–9 is O(100). Total: O(|pairs|), dominated by the network weight computation.

---

## 7. Implementation Note on ω_eo

The network weight ω_eo = (1/S) · Σ_ij T_ij · (λ_ij · E_ie · O_jo + λ_ji · E_je · O_io) requires iterating over all tract pairs for each of the 100 segments. This can be restructured as a matrix operation:

For each pair (i, j), define the 5 × 20 contribution matrix:

    M_ij[e, o] = T_ij · (λ_ij · E_ie · O_jo + λ_ji · E_je · O_io)

Then ω_eo = (1/S) · Σ_ij M_ij[e, o]. In practice, this sum can be accumulated incrementally while iterating over pairs, without storing all M_ij matrices. This makes the computation O(|pairs| × 100) in time and O(100) in space (just the running ω_eo accumulator).

Alternatively, note that the sum decomposes:

    S · ω_eo = Σ_ij T_ij · λ_ij · E_ie · O_jo  +  Σ_ij T_ij · λ_ji · E_je · O_io

The first term can be written as: Σ_i E_ie · [Σ_j T_ij · λ_ij · O_jo] and the second as: Σ_j E_je · [Σ_i T_ij · λ_ji · O_io]. If the inner sums are precomputed per tract, this further reduces the work — but the details depend on the implementation's data structures.
