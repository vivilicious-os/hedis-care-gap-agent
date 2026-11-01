"""Tests run on the cached public data in data/public. Run: python -m unittest discover -s tests"""
import json
import unittest

from hedis_agent import cms, facts
from hedis_agent.agent import TOOLS, run_tool
from hedis_agent.analytics import PublicAnalyzer
from hedis_agent.config import CORE_SET_MEASURES
from hedis_agent.server import render_static

CLAUDE_MD_COLUMNS = {"MeasureCode", "MeasureName", "HEDISCode", "MeasureCategory", "MeasureGroup", "PayerName",
                     "LineOfBusiness", "ProviderId", "ProviderName", "DepartmentName", "MeasurementYear",
                     "AsOfDate", "SourceRunDate", "RuleVersion", "RunId", "BuildId", "ReportDate", "BaseKey"}
PATIENT_COLUMNS = {"PatientIdentityKey", "PAT_MRN_ID", "Member_ID", "Patient_First_Name", "Patient_Last_Name", "DOB"}


class PublicDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = PublicAnalyzer()
        cls.ms = cls.a.measures()

    def test_fact_table_uses_claude_md_names_and_has_no_patient_fields(self):
        cols = set(facts.COLUMNS)
        self.assertTrue(CLAUDE_MD_COLUMNS <= cols)
        self.assertFalse(PATIENT_COLUMNS & cols)
        self.assertEqual({r["Source"] for r in self.a.rows}, {"Medicaid Core Set", "CMS MIPS", "CDC PLACES"})

    def test_every_measure_is_listed_and_ranked_sensibly(self):
        self.assertEqual({m["measure"] for m in self.ms}, set(CORE_SET_MEASURES))
        for m in self.ms:
            if m["reported"]:
                self.assertTrue(1 <= m["rank"] <= m["of"])
                self.assertEqual(m["target"], m["top_quartile"])
                self.assertIn("top-quartile", m["target_source"])

    def test_hybrid_sample_denominators_are_never_turned_into_member_counts(self):
        for m in self.ms:
            if m.get("sample_denominator"):
                self.assertIsNone(m["members_to_top_quartile"])
                self.assertIn("sample", m["rate_display"])

    def test_trend_change_is_last_minus_first(self):
        for t in self.a.trends():
            rated = [p for p in t["points"] if p["rate"] is not None]
            if len(rated) >= 2:
                self.assertAlmostEqual(t["change_pts"], round(rated[-1]["rate"] - rated[0]["rate"], 1))

    def test_provider_groups_are_in_state_only(self):
        grp = cms.load_groups()
        for rows in grp["measures"].values():
            self.assertTrue(all(r.get("in_state_share", 1) >= 0.5 for r in rows))
        for p in self.a.providers()["measures"].values():
            for g in p["top"]:
                exp = g["patients"] * ((100 - g["rate"]) if p["higher_is_better"] else g["rate"]) / 100
                self.assertAlmostEqual(g["patients_not_meeting"], round(exp), delta=1)

    def test_campaigns_ranked_and_labeled(self):
        c = self.a.campaigns()
        self.assertEqual([x["rank"] for x in c["campaigns"]], list(range(1, len(c["campaigns"]) + 1)))
        self.assertIn("no response rates", c["disclaimer"])

    def test_every_agent_tool_runs_offline(self):
        for t in TOOLS:
            if t["name"] == "lookup_npi":
                continue
            json.dumps(run_tool(self.a, t["name"], {"measure": "CBP"}), default=str)

    def test_static_page_embeds_data_safely(self):
        html = render_static(self.a.payload())
        blob = html.split("window.__HEDIS_DATA__ = ", 1)[1].split(";</script>", 1)[0]
        self.assertNotIn("</script", blob.lower())
        json.loads(blob.replace("<\\/", "</"))


if __name__ == "__main__":
    unittest.main()
