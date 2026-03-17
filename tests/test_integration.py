"""Integration tests: live API calls for the data acquisition layer.

These tests hit the Census Bureau API and download LODES files.
They require a CENSUS_API_KEY environment variable or config file.

Run with: CENSUS_API_KEY=<key> python -m pytest tests/test_integration.py -v -s

The first run downloads data (may take a few minutes for LODES files).
Subsequent runs use the cache and are fast.
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wfh_perturbation import (
    fetch_education_data,
    fetch_wac_data,
    fetch_od_data,
    fetch_study_area_data,
    perturb_flows,
)

# Use a persistent cache directory so repeated test runs don't re-download
CACHE_DIR = os.path.join(tempfile.gettempdir(), "wfh_perturbation_test_cache")
API_KEY = os.environ.get("CENSUS_API_KEY", "")

# Validation tracts from the spec (Section 5)
# Example 3 (Austin TX) — smaller LODES files, faster to download
AUSTIN_TRACTS = ["48453001101", "48453002422"]

# Example 1 (NYC) — larger files but well-validated
NYC_TRACTS = ["36061000700", "36061018400"]

# Cross-state example (NJ + NY)
CROSS_STATE_TRACTS = ["34003005000", "36061010000"]


def skip_without_api_key():
    if not API_KEY:
        pytest.skip("CENSUS_API_KEY not set; skipping live API test")


# ============================================================
# DA-1: Education data from Census API
# ============================================================

class TestFetchEducation:
    def test_austin_tracts(self):
        """Fetch education data for Austin TX tracts and verify shape/sums."""
        skip_without_api_key()
        edu = fetch_education_data(
            AUSTIN_TRACTS, year=2024, api_key=API_KEY, cache_dir=CACHE_DIR
        )

        assert len(edu) == 2, f"Expected 2 tracts, got {len(edu)}"
        for fips in AUSTIN_TRACTS:
            assert fips in edu, f"Missing tract {fips}"
            shares = edu[fips]
            assert shares.shape == (5,), f"Wrong shape: {shares.shape}"
            assert abs(shares.sum() - 1.0) < 0.01, f"Shares don't sum to 1: {shares.sum()}"
            assert np.all(shares >= 0), f"Negative shares: {shares}"
            print(f"  {fips}: {shares}")

    def test_cross_state_tracts(self):
        """Fetch education data across NJ and NY."""
        skip_without_api_key()
        edu = fetch_education_data(
            CROSS_STATE_TRACTS, year=2024, api_key=API_KEY, cache_dir=CACHE_DIR
        )
        assert len(edu) == 2
        for fips in CROSS_STATE_TRACTS:
            assert fips in edu

    def test_caching(self):
        """DA-6: Second call uses cache (no HTTP requests)."""
        skip_without_api_key()
        # First call populates cache
        edu1 = fetch_education_data(
            AUSTIN_TRACTS, year=2024, api_key=API_KEY, cache_dir=CACHE_DIR
        )
        # Second call should hit cache
        edu2 = fetch_education_data(
            AUSTIN_TRACTS, year=2024, api_key=API_KEY, cache_dir=CACHE_DIR
        )
        for fips in AUSTIN_TRACTS:
            np.testing.assert_array_almost_equal(edu1[fips], edu2[fips])


# ============================================================
# DA-2: LODES WAC industry data
# ============================================================

class TestFetchWAC:
    def test_austin_tracts(self):
        """Fetch WAC data for Austin tracts and verify industry shares."""
        skip_without_api_key()
        ind = fetch_wac_data(AUSTIN_TRACTS, year=2023, cache_dir=CACHE_DIR)

        assert len(ind) == 2
        for fips in AUSTIN_TRACTS:
            assert fips in ind, f"Missing tract {fips}"
            shares = ind[fips]
            assert shares.shape == (20,), f"Wrong shape: {shares.shape}"
            total = shares.sum()
            # Shares should sum to ~1.0 (DP-2), or 0.0 for empty tracts
            assert total < 0.01 or abs(total - 1.0) < 0.005, (
                f"Shares sum to {total}, expected ~1.0 or ~0.0"
            )
            print(f"  {fips}: top 3 industries = {np.argsort(shares)[-3:][::-1]}")

    def test_block_level_returns(self):
        """fetch_wac_data with return_block_level=True returns block jobs."""
        skip_without_api_key()
        ind, block_jobs = fetch_wac_data(
            AUSTIN_TRACTS, year=2023, cache_dir=CACHE_DIR, return_block_level=True
        )
        assert len(block_jobs) > 0, "Expected some block-level job counts"
        print(f"  {len(block_jobs)} blocks with jobs")


# ============================================================
# DA-3, DA-4: LODES OD commute flows
# ============================================================

class TestFetchOD:
    def test_austin_tracts(self):
        """Fetch OD data for Austin tracts and verify tract-level flows."""
        skip_without_api_key()
        flows = fetch_od_data(AUSTIN_TRACTS, year=2023, cache_dir=CACHE_DIR)

        print(f"  Found {len(flows)} directed tract pairs with nonzero flow")
        for (res, work), count in flows.items():
            assert res in set(AUSTIN_TRACTS), f"Unexpected residence tract: {res}"
            assert work in set(AUSTIN_TRACTS), f"Unexpected workplace tract: {work}"
            assert count > 0, f"Zero flow should not appear: ({res},{work})={count}"
            print(f"  ({res} -> {work}): {count} workers")


# ============================================================
# End-to-end: fetch + perturb for arbitrary tracts
# ============================================================

class TestEndToEndLive:
    def test_austin_pipeline(self):
        """Full pipeline: fetch data for Austin tracts, perturb at alpha=0.25."""
        skip_without_api_key()

        # Fetch all data
        edu, ind, commute = fetch_study_area_data(
            AUSTIN_TRACTS, api_key=API_KEY, cache_dir=CACHE_DIR
        )

        # Create synthetic baseline flows (Deep Gravity would provide these)
        T_ij = {(AUSTIN_TRACTS[0], AUSTIN_TRACTS[1]): 1600.0}

        # Run perturbation
        result = perturb_flows(
            alpha=0.25,
            baseline_flows=T_ij,
            edu_shares=edu,
            ind_shares=ind,
            commute_weights=commute,
        )

        pair = (AUSTIN_TRACTS[0], AUSTIN_TRACTS[1])
        P = result.P[pair]
        G = result.G[pair]

        print(f"\n  Austin end-to-end (live data):")
        print(f"  P_ij = {P:.6f}")
        print(f"  G_ij = {G:.1f} (from T={T_ij[pair]:.0f})")
        print(f"  % change = {(P - 1) * 100:.2f}%")

        # Sanity checks
        assert 0 < P < 1.0, f"P should be in (0, 1) at alpha=0.25, got {P}"
        assert G < T_ij[pair], "Perturbed flow should be less than baseline"
        assert result.metadata["mode"] == "direct_alpha"

    def test_cross_state_pipeline(self):
        """Full pipeline for NJ-NY cross-state pair."""
        skip_without_api_key()

        edu, ind, commute = fetch_study_area_data(
            CROSS_STATE_TRACTS, api_key=API_KEY, cache_dir=CACHE_DIR
        )

        T_ij = {(CROSS_STATE_TRACTS[0], CROSS_STATE_TRACTS[1]): 2800.0}

        result = perturb_flows(
            alpha=0.25,
            baseline_flows=T_ij,
            edu_shares=edu,
            ind_shares=ind,
            commute_weights=commute,
        )

        pair = (CROSS_STATE_TRACTS[0], CROSS_STATE_TRACTS[1])
        P = result.P[pair]

        print(f"\n  NJ-NY cross-state (live data):")
        print(f"  P_ij = {P:.6f}")
        print(f"  Commute flows found: {len(commute)}")

        assert 0 < P < 1.0


# ============================================================
# H3 hex-native pipeline: live TIGER + Census block data
# ============================================================

class TestHexNative:
    """Test the hex-native workflow with real geographic data.

    Uses prepare_hex_data() to convert tract-level Census demographics
    to H3 hex-level data, then runs perturbation directly on hex-keyed
    inputs (as Deep Gravity would provide in production).

    These tests are slower (TIGER block files are ~100 MB per state)
    but the cache makes subsequent runs fast.
    """

    def test_prepare_hex_data(self):
        """prepare_hex_data returns hex-keyed edu, ind, commute dicts."""
        skip_without_api_key()

        from wfh_perturbation import prepare_hex_data
        hex_edu, hex_ind, hex_commute = prepare_hex_data(
            AUSTIN_TRACTS, resolution=7, api_key=API_KEY,
            lodes_year=2023, cache_dir=CACHE_DIR,
        )

        # Keys should be H3 hex strings, not FIPS
        print(f"\n  prepare_hex_data results:")
        print(f"  Hex edu entries: {len(hex_edu)}")
        print(f"  Hex ind entries: {len(hex_ind)}")
        print(f"  Hex commute pairs: {len(hex_commute)}")

        assert len(hex_edu) > 0, "Should have hex education data"
        assert len(hex_ind) > 0, "Should have hex industry data"
        assert len(hex_commute) > 0, "Should have hex commute weights"

        for hex_id, shares in hex_edu.items():
            assert not hex_id.isdigit(), f"Expected hex ID, got FIPS-like key: {hex_id}"
            assert shares.shape == (5,), f"Wrong edu shape: {shares.shape}"
            assert abs(shares.sum() - 1.0) < 0.01, f"Edu shares should sum to ~1: {shares.sum()}"
            print(f"    edu {hex_id[:12]}: {shares}")

        for hex_id, shares in hex_ind.items():
            assert not hex_id.isdigit(), f"Expected hex ID, got FIPS-like key: {hex_id}"
            assert shares.shape == (20,), f"Wrong ind shape: {shares.shape}"

        for (h_a, h_b), w in hex_commute.items():
            assert not h_a.isdigit(), f"Expected hex ID, got FIPS-like key: {h_a}"
            assert w > 0, f"Commute weight should be positive: {w}"

    def test_hex_native_perturbation(self):
        """Full hex-native pipeline: prepare data, then perturb with hex-level flows."""
        skip_without_api_key()

        from wfh_perturbation import prepare_hex_data
        hex_edu, hex_ind, hex_commute = prepare_hex_data(
            AUSTIN_TRACTS, resolution=7, api_key=API_KEY,
            lodes_year=2023, cache_dir=CACHE_DIR,
        )

        # Simulate hex-level Deep Gravity flows between all hex pairs
        # that have commute data (in production, these come from Deep Gravity)
        hex_flows = {}
        for (h_a, h_b), w in hex_commute.items():
            hex_flows[(h_a, h_b)] = w * 10.0  # Scale up for illustration

        total_T = sum(hex_flows.values())
        print(f"\n  Hex-native perturbation:")
        print(f"  Hex flow pairs: {len(hex_flows)}")
        print(f"  Total baseline flow: {total_T:.1f}")

        # Run perturbation directly on hex-level data
        result = perturb_flows(
            alpha=0.25,
            baseline_flows=hex_flows,
            edu_shares=hex_edu,
            ind_shares=hex_ind,
            commute_weights=hex_commute,
        )

        # All P values should be hex-keyed and in (0, 1)
        assert len(result.P) > 0, "Should have P values"
        total_G = sum(result.G.values())

        for pair, P in result.P.items():
            assert 0 < P < 1.0, f"P should be in (0,1) at alpha=0.25, got {P} for {pair}"
            assert not pair[0].isdigit(), f"Expected hex IDs, got FIPS-like key: {pair[0]}"

        pct_change = (total_G / total_T - 1) * 100
        print(f"  Total perturbed flow: {total_G:.1f}")
        print(f"  Aggregate % change: {pct_change:.2f}%")
        print(f"  P values computed: {len(result.P)}")

        # Show a few sample P values
        for pair, P in sorted(result.P.items(), key=lambda x: x[1])[:3]:
            print(f"    {pair[0][:12]} <-> {pair[1][:12]}: P={P:.6f}")

        assert total_G < total_T, "Perturbed total should be < baseline at alpha=0.25"

    def test_h3_conversion_details(self):
        """Verify H3 conversion internals: block counts, hex assignments, weight sums."""
        skip_without_api_key()

        from wfh_perturbation.geo import (
            fetch_block_centroids,
            assign_blocks_to_hexes,
            compute_tract_hex_weights,
        )
        from wfh_perturbation.data_acquisition import fetch_block_population, fetch_wac_data

        # Get block centroids
        centroids = fetch_block_centroids(AUSTIN_TRACTS, cache_dir=CACHE_DIR)
        print(f"\n  Blocks in Austin study area: {len(centroids)}")
        assert len(centroids) > 0, "Should find blocks in Austin tracts"

        # Assign to hexes
        block_hex = assign_blocks_to_hexes(centroids, resolution=7)
        unique_hexes = set(block_hex.values())
        print(f"  Unique H3 hexes (res 7): {len(unique_hexes)}")
        assert len(unique_hexes) >= 1, "Should have at least 1 hex"

        # Get block population and employment
        block_pop = fetch_block_population(
            AUSTIN_TRACTS, api_key=API_KEY, cache_dir=CACHE_DIR
        )
        _, block_jobs = fetch_wac_data(
            AUSTIN_TRACTS, year=2023, cache_dir=CACHE_DIR, return_block_level=True
        )
        print(f"  Blocks with population data: {len(block_pop)}")
        print(f"  Blocks with employment data: {len(block_jobs)}")

        # Compute weights and verify they sum to 1 per tract
        res_weights = compute_tract_hex_weights(
            block_hex, {k: float(v) for k, v in block_pop.items()}, AUSTIN_TRACTS
        )
        emp_weights = compute_tract_hex_weights(
            block_hex, {k: float(v) for k, v in block_jobs.items()}, AUSTIN_TRACTS
        )

        for tract in AUSTIN_TRACTS:
            res_sum = sum(w for (t, h), w in res_weights.items() if t == tract)
            emp_sum = sum(w for (t, h), w in emp_weights.items() if t == tract)
            print(f"  {tract}: res weight sum={res_sum:.6f}, emp weight sum={emp_sum:.6f}")
            assert abs(res_sum - 1.0) < 0.001, f"Residential weights should sum to 1, got {res_sum}"
            assert abs(emp_sum - 1.0) < 0.001, f"Employment weights should sum to 1, got {emp_sum}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
