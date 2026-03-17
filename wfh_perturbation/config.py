"""
Configuration defaults for the WFH perturbation module.

Contains pre-populated WFH parameter vectors (DA-5), the B15003 education
crosswalk (DP-1, DP-6), and the CPS-to-LODES industry mapping.

These values are derived from CPS Q1/Aug 2024 supplements and Dingel-Neiman
(2020) O*NET classifications. They may be overridden by the user but do not
need to be re-derived on every run.
"""

import numpy as np
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Education-level WFH parameters (5 bins)
# Index: 0=Less than HS, 1=HS Diploma, 2=Some College/Assoc., 3=Bachelor's, 4=Advanced
# ---------------------------------------------------------------------------

EDUCATION_LABELS = [
    "Less than HS",
    "HS Diploma",
    "Some College/Assoc.",
    "Bachelor's",
    "Advanced",
]

DEFAULT_W_E = np.array([0.035, 0.085, 0.183, 0.384, 0.436])
DEFAULT_U_E = np.array([0.098, 0.183, 0.317, 0.556, 0.674])


# ---------------------------------------------------------------------------
# Industry-level WFH parameters (20 LODES CNS sectors)
# Index: 0=CNS01 through 19=CNS20
# ---------------------------------------------------------------------------

INDUSTRY_LABELS = [
    "CNS01 Agriculture, Forestry, Fishing",
    "CNS02 Mining, Quarrying, Oil/Gas",
    "CNS03 Utilities",
    "CNS04 Construction",
    "CNS05 Manufacturing",
    "CNS06 Wholesale Trade",
    "CNS07 Retail Trade",
    "CNS08 Transportation & Warehousing",
    "CNS09 Information",
    "CNS10 Finance & Insurance",
    "CNS11 Real Estate & Rental/Leasing",
    "CNS12 Professional, Scientific, Tech",
    "CNS13 Management of Companies",
    "CNS14 Admin/Support/Waste Mgmt",
    "CNS15 Educational Services",
    "CNS16 Healthcare & Social Assistance",
    "CNS17 Arts, Entertainment, Recreation",
    "CNS18 Accommodation & Food Services",
    "CNS19 Other Services",
    "CNS20 Public Administration",
]

DEFAULT_W_O = np.array([
    0.123,  # CNS01
    0.162,  # CNS02
    0.277,  # CNS03
    0.089,  # CNS04
    0.196,  # CNS05
    0.234,  # CNS06
    0.110,  # CNS07
    0.080,  # CNS08
    0.500,  # CNS09
    0.595,  # CNS10
    0.421,  # CNS11
    0.597,  # CNS12
    0.199,  # CNS13
    0.199,  # CNS14
    0.197,  # CNS15
    0.181,  # CNS16
    0.187,  # CNS17
    0.043,  # CNS18
    0.177,  # CNS19
    0.271,  # CNS20
])

DEFAULT_U_O = np.array([
    0.20,   # CNS01
    0.25,   # CNS02
    0.37,   # CNS03
    0.19,   # CNS04
    0.22,   # CNS05
    0.52,   # CNS06
    0.14,   # CNS07
    0.19,   # CNS08
    0.72,   # CNS09
    0.76,   # CNS10
    0.60,   # CNS11
    0.80,   # CNS12
    0.79,   # CNS13
    0.31,   # CNS14
    0.83,   # CNS15
    0.25,   # CNS16
    0.30,   # CNS17
    0.08,   # CNS18
    0.31,   # CNS19
    0.41,   # CNS20
])


# ---------------------------------------------------------------------------
# B15003 Education Crosswalk (DP-1, DP-6)
#
# Maps ACS Table B15003 variable suffixes to the five education bins.
# B15003_001E is the total (population 25+). Variables B15003_002E through
# B15003_025E are the detailed attainment categories.
#
# This crosswalk follows the standard five-bin aggregation used in labor
# economics and matches the bins validated in the Excel workbook.
# ---------------------------------------------------------------------------

B15003_CROSSWALK: Dict[str, List[str]] = {
    # Bin 0: Less than high school
    # No schooling through 12th grade no diploma
    "less_than_hs": [
        "B15003_002E",  # No schooling completed
        "B15003_003E",  # Nursery school
        "B15003_004E",  # Kindergarten
        "B15003_005E",  # 1st grade
        "B15003_006E",  # 2nd grade
        "B15003_007E",  # 3rd grade
        "B15003_008E",  # 4th grade
        "B15003_009E",  # 5th grade
        "B15003_010E",  # 6th grade
        "B15003_011E",  # 7th grade
        "B15003_012E",  # 8th grade
        "B15003_013E",  # 9th grade
        "B15003_014E",  # 10th grade
        "B15003_015E",  # 11th grade
        "B15003_016E",  # 12th grade, no diploma
    ],
    # Bin 1: High school diploma or equivalent
    "hs_diploma": [
        "B15003_017E",  # Regular high school diploma
        "B15003_018E",  # GED or alternative credential
    ],
    # Bin 2: Some college or associate's degree
    "some_college": [
        "B15003_019E",  # Some college, less than 1 year
        "B15003_020E",  # Some college, 1 or more years, no degree
        "B15003_021E",  # Associate's degree
    ],
    # Bin 3: Bachelor's degree
    "bachelors": [
        "B15003_022E",  # Bachelor's degree
    ],
    # Bin 4: Advanced degree (master's, professional, doctorate)
    "advanced": [
        "B15003_023E",  # Master's degree
        "B15003_024E",  # Professional school degree
        "B15003_025E",  # Doctorate degree
    ],
}

# Total variable for B15003
B15003_TOTAL = "B15003_001E"

# All variables needed from the API (total + all detail lines)
B15003_VARIABLES = [B15003_TOTAL] + [
    var for group in B15003_CROSSWALK.values() for var in group
]

# Ordered bin names matching the education index (0-4)
EDUCATION_BIN_ORDER = ["less_than_hs", "hs_diploma", "some_college", "bachelors", "advanced"]


# ---------------------------------------------------------------------------
# LODES column mappings
# ---------------------------------------------------------------------------

LODES_WAC_INDUSTRY_COLS = [f"CNS{i:02d}" for i in range(1, 21)]
LODES_WAC_TOTAL_COL = "C000"
LODES_OD_RESIDENCE_COL = "w_geocode"
LODES_OD_WORKPLACE_COL = "h_geocode"
LODES_OD_TOTAL_COL = "S000"


