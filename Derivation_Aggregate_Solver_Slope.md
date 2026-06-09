# Derivation: Slope of $X(\alpha)$ for the Aggregate Scenario Solver

**Purpose:** Derive the exact slope $dX/d\alpha$ of the total-flow change $X$ as a function of the scaling factor $\alpha$. This slope drives the **optional** exact breakpoint-walk solver (`solve_for_alpha_exact`). The default solver, `solve_for_alpha`, instead bisects the closed-form $X(\alpha)$ directly and does not need this slope; both recover the same $\alpha$. The breakpoint walk is documented here for reference and as an independent cross-check on the closed form.

**Notation.** This derivation follows the WFH scenario supplement. Per segment $(e,o)$:

- $\phi_{eo} = \dfrac{w_{eo}}{1 - w_{eo}}$ — baseline WFH **sensitivity** (the supplement's $\phi_{eo}$).
- $c_{eo} = \dfrac{u_{eo} - w_{eo}}{1 - w_{eo}}$ — **saturated contribution**: the value of $1 - W_{eo}$ once the segment reaches its upper bound.
- $\alpha_{eo} = \dfrac{u_{eo} - w_{eo}}{w_{eo}} = \dfrac{c_{eo}}{\phi_{eo}}$ — the segment's **upper breakpoint**.

The per-workplace intermediate vector below is written $\theta_e(s)$ (theta), matching the variable named `theta` in the code. It is *not* the sensitivity $\phi_{eo}$; the two are distinct quantities that happened to share the letter $\phi$ in earlier drafts, which is why the code and this document use $\theta$ for the vector and reserve $\phi$ for the sensitivity.

**Companion documents:** the WFH scenario supplement and its derivation worksheet; the module specification (Section 4.D); the reference spreadsheet.

---

## 1. Setup and Notation

Let $S = \sum_{ij} T_{ij}$ denote the total baseline flow across the network (a constant). The change in total flow is:

$$X(\alpha) = \frac{\sum_{ij} T_{ij}\,P_{ij}(\alpha)}{S} - 1$$

So the slope we need is:

$$\frac{dX}{d\alpha} = \frac{1}{S} \sum_{ij} T_{ij}\,\frac{dP_{ij}}{d\alpha}$$

The task is to compute $dP_{ij}/d\alpha$ by applying the chain rule through the computation pipeline:

$$\alpha \;\to\; \Delta w_{eo} \;\to\; W_{eo} \;\to\; \theta_e(s) \;\to\; \Omega_{ij} \;\to\; P_{ij}$$

Between consecutive breakpoints, every step in this chain is linear in $\alpha$, so the chain rule gives a constant slope within each interval.

---

## 2. Directional Weight Convention

Before proceeding, define the directional weight $\lambda_{ij}$ to unify the standard case ($L_{ij} + L_{ji} > 0$) and the fallback case ($L_{ij} + L_{ji} = 0$):

$$\lambda_{ij} = \begin{cases} \dfrac{L_{ij}}{L_{ij} + L_{ji}} & L_{ij} + L_{ji} > 0 \\[6pt] \tfrac{1}{2} & L_{ij} + L_{ji} = 0 \quad\text{(equal-weight fallback)} \end{cases}$$

By construction, $\lambda_{ij} + \lambda_{ji} = 1$ for all pairs. The symmetric perturbation factor is then:

$$P_{ij} = \lambda_{ij}\,\Omega_{ij} + \lambda_{ji}\,\Omega_{ji}$$

This holds for both cases without branching.

---

## 3. Chain Rule, Step by Step

### Step 1: $\alpha \to W_{eo}$

Let $U \subseteq \{1,\dots,5\} \times \{1,\dots,20\}$ denote the set of **unsaturated** segments at the current value of $\alpha$. A segment $(e, o)$ is unsaturated when neither the upper nor lower bound is binding, i.e., when $-w_{eo} < \alpha\,w_{eo} < u_{eo} - w_{eo}$.

For unsaturated segments, $\Delta w_{eo} = \alpha\,w_{eo}$, so:

$$W_{eo} = 1 - \frac{\alpha\,w_{eo}}{1 - w_{eo}} = 1 - \alpha\,\phi_{eo}, \qquad \phi_{eo} = \frac{w_{eo}}{1 - w_{eo}}$$

For saturated segments, $W_{eo}$ is constant, so $dW_{eo}/d\alpha = 0$. Once a segment saturates at its upper bound, $1 - W_{eo}$ holds at the constant $c_{eo} = \dfrac{u_{eo} - w_{eo}}{1 - w_{eo}}$. Therefore:

$$\frac{dW_{eo}}{d\alpha} = \begin{cases} -\phi_{eo} & (e, o) \in U \\ 0 & (e, o) \notin U \end{cases}$$

### Step 2: $W_{eo} \to \theta_e(s)$

For any workplace tract $s$:

$$\theta_e(s) = \sum_o W_{eo}\,O_{so}$$

Differentiating:

$$\frac{d\theta_e(s)}{d\alpha} = \sum_o \frac{dW_{eo}}{d\alpha}\,O_{so} = -\sum_{o\,:\,(e,o)\in U} \phi_{eo}\,O_{so}$$

### Step 3: $\theta_e(s) \to \Omega_{ij}$

For a directed flow from residence tract $i$ to workplace tract $j$:

$$\Omega_{ij} = \sum_e E_{ie}\,\theta_e(s = j)$$

Differentiating:

$$\frac{d\Omega_{ij}}{d\alpha} = \sum_e E_{ie}\left[-\sum_{o\,:\,(e,o)\in U} \phi_{eo}\,O_{jo}\right] = -\sum_{(e,o)\in U} \phi_{eo}\,E_{ie}\,O_{jo}$$

This is the key intermediate result: the sensitivity of the directional perturbation factor $\Omega_{ij}$ to $\alpha$ is a weighted sum over unsaturated segments, where each segment's contribution depends on the **residence** tract's education share ($E_{ie}$) and the **workplace** tract's industry share ($O_{jo}$).

### Step 4: $\Omega_{ij} \to P_{ij}$

$$P_{ij} = \lambda_{ij}\,\Omega_{ij} + \lambda_{ji}\,\Omega_{ji}$$

Since $\lambda_{ij}$ and $\lambda_{ji}$ are constants (they depend on LODES counts, not on $\alpha$):

$$\frac{dP_{ij}}{d\alpha} = \lambda_{ij}\,\frac{d\Omega_{ij}}{d\alpha} + \lambda_{ji}\,\frac{d\Omega_{ji}}{d\alpha}$$

Substituting from Step 3:

$$\frac{dP_{ij}}{d\alpha} = -\sum_{(e,o)\in U} \phi_{eo}\big[\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io}\big]$$

### Step 5: $P_{ij} \to X$

$$\frac{dX}{d\alpha} = \frac{1}{S}\sum_{ij} T_{ij}\,\frac{dP_{ij}}{d\alpha} = -\sum_{(e,o)\in U} \phi_{eo}\left[\frac{1}{S}\sum_{ij} T_{ij}\big(\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io}\big)\right]$$

where the order of summation ($\sum_{ij}$ and $\sum_{(e,o)}$) has been swapped, valid since both are finite sums.

---

## 4. The Trip-Weighted Share $m_{eo}$

Define the **trip-weighted share** of segment $(e, o)$ — the same $m_{eo}$ as the WFH scenario supplement:

$$m_{eo} = \frac{1}{S}\sum_{ij} T_{ij}\big(\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io}\big)$$

Then the slope takes a compact form:

$$\boxed{\ \frac{dX}{d\alpha} = -\sum_{(e,o)\in U} \phi_{eo}\,m_{eo}\ }$$

where $\phi_{eo} = w_{eo}/(1 - w_{eo})$ is the sensitivity, $m_{eo}$ is the trip-weighted share above, and $U$ is the set of unsaturated segments.

This is the derivative of the supplement's closed form $X(\alpha) = -\sum_{eo} m_{eo}\,\min(\alpha\,\phi_{eo},\, c_{eo})$: on any interval the unsaturated segments contribute the linear term $-\alpha\,\phi_{eo}\,m_{eo}$ (slope $-\phi_{eo}\,m_{eo}$ each), while saturated segments contribute the constant $-c_{eo}\,m_{eo}$ (slope $0$). The flow-weighted average sensitivity is $\bar{\Phi} = \sum_{eo} \phi_{eo}\,m_{eo}$, so the slope at $\alpha = 0$ is exactly $-\bar{\Phi}$.

**Interpretation:** Each education-industry segment $(e, o)$ contributes to the slope in proportion to two factors: $\phi_{eo}$ captures how sensitive the perturbation weight is to changes in $\alpha$ (segments with higher baseline WFH are more responsive), and $m_{eo}$ captures how much influence that segment has on total network flow (segments that are demographically prevalent in high-flow corridors matter more).

---

## 5. Properties (Self-Checks)

### 5.1. Sign

$\phi_{eo} > 0$ for all segments (since $0 < w_{eo} < 1$), and $m_{eo} \ge 0$ (since $T_{ij}$, $E_{ie}$, $O_{jo}$, $\lambda_{ij}$ are all non-negative). Therefore $dX/d\alpha \le 0$ whenever $U$ is nonempty. This is correct: increasing $\alpha$ (more WFH) reduces total trips.

### 5.2. $\alpha = 0$

At $\alpha = 0$, no segments are saturated ($U$ = all segments), $W_{eo} = 1$ for all, $\theta_e(s) = \sum_o O_{so} = 1$, $\Omega_{ij} = \sum_e E_{ie} = 1$, $P_{ij} = 1$, and $X = 0$. The slope at $\alpha = 0$ is $dX/d\alpha = -\sum_{\text{all }(e,o)} \phi_{eo}\,m_{eo} = -\bar{\Phi}$. This is the steepest the slope can be (subsequent saturation can only remove terms from the sum, making the slope less negative).

### 5.3. Homogeneous demographics

If all tracts have identical education shares $E_e$ and industry shares $O_o$, then $\Omega_{ij} = \Omega_{ji}$ for all pairs, $P_{ij}$ is the same everywhere, and $X(\alpha) = P(\alpha) - 1$. In this case:

$$m_{eo} = \frac{1}{S}\sum_{ij} T_{ij}\,E_e\,O_o\,(\lambda_{ij} + \lambda_{ji}) = E_e\,O_o$$

since $\lambda_{ij} + \lambda_{ji} = 1$ and $\frac{1}{S}\sum_{ij} T_{ij} = 1$. So:

$$\frac{dX}{d\alpha} = -\sum_{(e,o)\in U} \phi_{eo}\,E_e\,O_o$$

Meanwhile, direct computation gives $P = \sum_e E_e \sum_o W_{eo}\,O_o$, and differentiating:

$$\frac{dP}{d\alpha} = -\sum_{(e,o)\in U} \phi_{eo}\,E_e\,O_o$$

These match. ✓

### 5.4. Single pair

If the network has just one pair $(i, j)$ with flow $T_{ij}$, then $S = T_{ij}$ (or $2T_{ij}$ if we count both directions — but this cancels in the ratio). The $m_{eo}$ formula reduces to:

$$m_{eo} = \lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io}$$

This is exactly the "effective demographic share" of segment $(e, o)$ for this pair, weighted by the directional split. This is consistent with the per-pair computation in the spreadsheet. ✓

### 5.5. Breakpoint structure

At each breakpoint $\alpha^*$ where segment $(e^*, o^*)$ saturates, the slope changes by:

$$\Delta(\text{slope}) = +\phi_{e^*o^*}\,m_{e^*o^*}$$

The slope becomes less negative (closer to zero), which is correct: once a segment saturates, further increases in $\alpha$ don't affect that segment's contribution, so the marginal reduction in trips diminishes. At that breakpoint, that segment's contribution to $1 - W_{eo}$ freezes at $c_{e^*o^*} = \dfrac{u_{e^*o^*} - w_{e^*o^*}}{1 - w_{e^*o^*}}$, so its contribution to $X$ holds at the constant $-c_{e^*o^*}\,m_{e^*o^*}$ thereafter.

---

## 6. The Complete Algorithm (optional exact solver)

This breakpoint walk is the reference implementation behind `solve_for_alpha_exact`. It is **optional**: the default `solve_for_alpha` bisects the closed form $X(\alpha)$ and returns the same $\alpha$ more simply. The walk is exact (no root-finding tolerance) and is useful as a cross-check.

**Precomputation (once per study area):**

1. Compute $\phi_{eo} = w_{eo} / (1 - w_{eo})$ for all 100 segments.
2. Compute $\lambda_{ij}$ for all tract pairs (from LODES counts and fallback policy).
3. Compute $m_{eo} = \frac{1}{S}\sum_{ij} T_{ij}\,(\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io})$ for all 100 segments.
4. Compute the upper breakpoints $\alpha_{eo} = (u_{eo} - w_{eo}) / w_{eo}$ for all segments, and the saturated contributions $c_{eo} = (u_{eo} - w_{eo}) / (1 - w_{eo})$.
5. Sort the positive breakpoints in ascending order. (There is also a single lower breakpoint at $\alpha = -1$ where all segments simultaneously hit the zero-WFH floor.)

**Solver (given target $X$):**

6. Start at $\alpha = 0$ where $X = 0$.
7. Initialize $\text{slope} = -\sum_{\text{all }(e,o)} \phi_{eo}\,m_{eo}$ (which equals $-\bar{\Phi}$).
8. Walk forward (if target $X < 0$) or backward (if target $X > 0$) through breakpoints:
    - At each breakpoint $\alpha^*$, compute the $X$ value there using the current slope: $X(\alpha^*) = X(\alpha_{\text{prev}}) + \text{slope}\cdot(\alpha^* - \alpha_{\text{prev}})$.
    - If the target $X$ falls within the current interval $[X(\alpha_{\text{prev}}),\, X(\alpha^*)]$, solve linearly: $\alpha_{\text{target}} = \alpha_{\text{prev}} + (X_{\text{target}} - X(\alpha_{\text{prev}})) / \text{slope}$.
    - Otherwise, update the slope by removing the saturated segment: $\text{slope} \mathrel{+}= \phi_{e^*o^*}\,m_{e^*o^*}$.
    - Continue to the next breakpoint.
9. If all breakpoints are exhausted without reaching the target, report infeasibility.

Equivalently, on the interval where the saturated set is $\mathcal{S}$,

$$X(\alpha) = -\alpha\!\!\sum_{(e,o)\notin \mathcal{S}}\!\!\phi_{eo}\,m_{eo} \;-\!\!\sum_{(e,o)\in \mathcal{S}}\!\!c_{eo}\,m_{eo}$$

the slope-and-offset form: the first sum is the current slope magnitude, the second is the frozen offset from already-saturated segments.

**Complexity:** The precomputation of $m_{eo}$ in step 3 is $O(100 \cdot |\text{pairs}|)$. The sort in step 5 is $O(100 \log 100)$. The walk in steps 6–9 is $O(100)$. Total: $O(|\text{pairs}|)$, dominated by the trip-weighted-share computation.

---

## 7. Implementation Note on $m_{eo}$

The trip-weighted share $m_{eo} = \frac{1}{S}\sum_{ij} T_{ij}\,(\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io})$ requires iterating over all tract pairs for each of the 100 segments. This can be restructured as a matrix operation:

For each pair $(i, j)$, define the $5 \times 20$ contribution matrix:

$$M_{ij}[e, o] = T_{ij}\,(\lambda_{ij}\,E_{ie}\,O_{jo} + \lambda_{ji}\,E_{je}\,O_{io})$$

Then $m_{eo} = \frac{1}{S}\sum_{ij} M_{ij}[e, o]$. In practice, this sum can be accumulated incrementally while iterating over pairs, without storing all $M_{ij}$ matrices. This makes the computation $O(|\text{pairs}| \times 100)$ in time and $O(100)$ in space (just the running $m_{eo}$ accumulator). This is exactly how `build_aggregate_model` accumulates $m_{eo}$.

Alternatively, note that the sum decomposes:

$$S\,m_{eo} = \sum_{ij} T_{ij}\,\lambda_{ij}\,E_{ie}\,O_{jo} \;+\; \sum_{ij} T_{ij}\,\lambda_{ji}\,E_{je}\,O_{io}$$

The first term can be written as $\sum_i E_{ie}\big[\sum_j T_{ij}\,\lambda_{ij}\,O_{jo}\big]$ and the second as $\sum_j E_{je}\big[\sum_i T_{ij}\,\lambda_{ji}\,O_{io}\big]$. If the inner sums are precomputed per tract, this further reduces the work — but the details depend on the implementation's data structures.
