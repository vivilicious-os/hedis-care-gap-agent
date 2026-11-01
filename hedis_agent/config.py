"""Settings: focus geography, file paths and the measure catalog.

Everything the agent analyzes comes from public APIs. The only things taken
from CLAUDE.md are the column names used in the fact table.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "data" / "public"      # cached public API pulls (committed)
OUTPUT_DIR = ROOT / "output"

# Focus geography. Override with HEDIS_STATE=TX (two-letter code) before refresh.
FOCUS_STATE = os.environ.get("HEDIS_STATE", "OH").upper()
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
FOCUS_STATE_NAME = STATE_NAMES.get(FOCUS_STATE, FOCUS_STATE)

MEDICAID_FILE = PUBLIC_DIR / "medicaid_core_set.json"
CMS_NATIONAL_FILE = PUBLIC_DIR / "cms_mips_national.json"
CMS_GROUPS_FILE = PUBLIC_DIR / f"cms_mips_groups_{FOCUS_STATE}.json"
PLACES_FILE = PUBLIC_DIR / f"cdc_places_counties_{FOCUS_STATE}.json"
NPPES_SUPPLY = PUBLIC_DIR / "nppes_provider_supply.json"
NPPES_CACHE = PUBLIC_DIR / "nppes_npi_cache.json"      # per-NPI lookups, git-ignored
FACTS_FILE = PUBLIC_DIR / f"hedis_public_facts_{FOCUS_STATE}.csv"

CORE_SET_YEARS = 5  # how many Core Set releases to pull for trends

# ---------------------------------------------------------------------------
# Medicaid & CHIP Core Set measures (HEDIS-based). One rate per measure:
#   abbr     abbreviations used across years (renamed measures share a code)
#   match    text that must appear in rate_definition (all of them)
# ---------------------------------------------------------------------------
CORE_SET_MEASURES = {
    "BCS": {"name": "Breast Cancer Screening", "abbr": ["BCS-AD"], "match": ["Mammogram"],
            "category": "Prevention & Screening", "group": "Cancer screening", "program": "Adult"},
    "CCS": {"name": "Cervical Cancer Screening", "abbr": ["CCS-AD"], "match": ["Cervical"],
            "category": "Prevention & Screening", "group": "Cancer screening", "program": "Adult"},
    "COL": {"name": "Colorectal Cancer Screening", "abbr": ["COL-AD"], "match": ["51 to 65"],
            "category": "Prevention & Screening", "group": "Cancer screening", "program": "Adult"},
    "CHL": {"name": "Chlamydia Screening (21–24)", "abbr": ["CHL-AD"], "match": ["Chlamydia"],
            "category": "Prevention & Screening", "group": "Sexual health", "program": "Adult"},
    "CBP": {"name": "Controlling High Blood Pressure", "abbr": ["CBP-AD"], "match": ["Blood Pressure"],
            "category": "Chronic Condition Management", "group": "Cardiovascular", "program": "Adult"},
    "GSD": {"name": "Glycemic Status <8% (Diabetes)", "abbr": ["GSD-AD", "HBD-AD"], "match": ["<8.0%"],
            "category": "Chronic Condition Management", "group": "Diabetes", "program": "Adult"},
    "PPC": {"name": "Postpartum Care", "abbr": ["PPC2-AD", "PPC-AD"], "match": ["Postpartum"],
            "category": "Maternal Health", "group": "Maternal", "program": "Adult"},
    "AMM": {"name": "Antidepressant Medication Mgmt (6 mo)", "abbr": ["AMM-AD"], "match": ["Continuation"],
            "category": "Behavioral Health", "group": "Behavioral", "program": "Adult"},
    "FUH": {"name": "Follow-Up After MH Hospitalization (30 d)", "abbr": ["FUH-AD"],
            "match": ["30 Days", "18 to 64"], "category": "Behavioral Health", "group": "Behavioral",
            "program": "Adult"},
    "IET": {"name": "Initiation of SUD Treatment", "abbr": ["IET-AD"], "match": ["Total", "Initiation"],
            "category": "Behavioral Health", "group": "Behavioral", "program": "Adult"},
    "W30": {"name": "Well-Child Visits, First 15 Months (6+)", "abbr": ["W30-CH"], "match": ["6 or More"],
            "category": "Pediatric & Preventive", "group": "Well-child", "program": "Child"},
    "WCV": {"name": "Child & Adolescent Well-Care Visits", "abbr": ["WCV-CH"], "match": ["Ages 3 to 21"],
            "category": "Pediatric & Preventive", "group": "Well-child", "program": "Child"},
    "CIS": {"name": "Childhood Immunizations (Combo 3)", "abbr": ["CIS-CH"], "match": ["Combination 3"],
            "category": "Pediatric & Preventive", "group": "Immunizations", "program": "Child"},
    "IMA": {"name": "Adolescent Immunizations (Combo 1)", "abbr": ["IMA-CH"], "match": ["Combination 1"],
            "category": "Pediatric & Preventive", "group": "Immunizations", "program": "Child"},
    "LSC": {"name": "Lead Screening in Children", "abbr": ["LSC-CH"], "match": ["Lead"],
            "category": "Pediatric & Preventive", "group": "Well-child", "program": "Child"},
    "DEV": {"name": "Developmental Screening (first 3 yrs)", "abbr": ["DEV-CH"], "match": ["Developmental"],
            "category": "Pediatric & Preventive", "group": "Well-child", "program": "Child"},
}

# CMS MIPS clinician-group measures (data.cms.gov). higher_is_better=False for inverse measures.
MIPS_MEASURES = {
    "CBP": {"measure_cd": "MIPS_GRP_236_overall", "name": "Controlling High Blood Pressure (MIPS #236)",
            "higher_is_better": True},
    "CCS": {"measure_cd": "MIPS_GRP_309_overall", "name": "Cervical Cancer Screening (MIPS #309)",
            "higher_is_better": True},
    "HBA1C>9": {"measure_cd": "MIPS_GRP_001_overall", "name": "Diabetes: HbA1c Poor Control >9% (MIPS #001)",
                "higher_is_better": False},
    "EED": {"measure_cd": "MIPS_GRP_117_overall", "name": "Diabetes: Eye Exam (MIPS #117)",
            "higher_is_better": True},
    "DSF": {"measure_cd": "MIPS_GRP_134_overall", "name": "Depression Screening & Follow-Up (MIPS #134)",
            "higher_is_better": True},
}

# CDC PLACES county indicators (adults 18+, model-based survey estimates).
PLACES_INDICATORS = {
    "colon_screen": {"name": "Colorectal cancer screening (45–75)", "kind": "screening", "higher_is_better": True},
    "mammouse": {"name": "Mammography in past 2 years (women 50–74)", "kind": "screening", "higher_is_better": True},
    "checkup": {"name": "Routine checkup in past year", "kind": "access", "higher_is_better": True},
    "bpmed": {"name": "Taking BP medication (adults with high BP)", "kind": "treatment", "higher_is_better": True},
    "access2": {"name": "No health insurance (18–64)", "kind": "access", "higher_is_better": False},
    "diabetes": {"name": "Diagnosed diabetes", "kind": "prevalence", "higher_is_better": False},
    "bphigh": {"name": "High blood pressure", "kind": "prevalence", "higher_is_better": False},
    "depression": {"name": "Depression", "kind": "prevalence", "higher_is_better": False},
}

SERVICE_AREA = ("Columbus", "OH")  # NPPES provider-supply example city

# Illustrative weights for ranking. Model settings, not data.
PRIORITY_DISCLAIMER = "Illustrative prioritization model — weights require business approval."
STALE_DAYS = 400  # public releases older than this (by last-modified date) are flagged
