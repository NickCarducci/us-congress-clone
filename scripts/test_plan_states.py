import importlib.util, json, pathlib, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("plan_states", here / "plan_states.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
CONFIG = json.loads((here.parent / "state-sources.json").read_text())


class PlanStates(unittest.TestCase):
    def test_split_states_get_a_job_per_chamber(self):
        jobs, _ = module.plan(CONFIG, only={"pa", "nj"})
        self.assertEqual([(j["state"], j["chamber"]) for j in jobs], [("nj", ""), ("pa", "upper"), ("pa", "lower")])

    def test_api_states_and_missing_keys_get_no_job(self):
        jobs, skipped = module.plan(CONFIG, only={"il", "tx", "ny"})
        self.assertEqual(jobs, [])
        self.assertIn("ny: needs NEW_YORK_API_KEY", skipped)

    def test_a_key_once_set_brings_the_state_in(self):
        jobs, _ = module.plan(CONFIG, only={"ny"}, have_secrets={"NEW_YORK_API_KEY"})
        self.assertEqual(jobs, [{"state": "ny", "chamber": "", "rpm": 60, "secret": "NEW_YORK_API_KEY"}])

    def test_every_state_is_configured(self):
        self.assertEqual(len(CONFIG["states"]), 51)   # 50 states and DC
        jobs, _ = module.plan(CONFIG)
        self.assertEqual(next(j["rpm"] for j in jobs if j["state"] == "wi"), 6)


    def test_only_changed_states_are_scraped(self):
        import datetime
        jobs, _ = module.plan(CONFIG, only={"pa", "nj", "wy", "or"})
        at = datetime.datetime(2026, 11, 14, 9, tzinfo=datetime.timezone.utc)
        marks = module.parse_marks(f"paupper {at.isoformat()}\npalower 2026-11-13T09:00:00Z\nnj {at.isoformat()}\nwy {at.isoformat()}")
        asked = {}
        def check(state, since):
            asked[state] = since
            if state == "wy":
                raise OSError("429")
            return {"pa": 3, "nj": 0}[state]
        kept, report = module.gate(jobs, marks, check)
        self.assertEqual(sorted({(j["state"], j["chamber"]) for j in kept}),
                         [("or", ""), ("pa", "lower"), ("pa", "upper"), ("wy", "")])
        self.assertNotIn("or", asked, "never scraped: no check, just scrape")
        self.assertEqual(asked["pa"], datetime.datetime(2026, 11, 13, 3, tzinfo=datetime.timezone.utc),
                         "from the older chamber's scrape, less the overlap")
        self.assertIn("nj: unchanged since 2026-11-14 03:00 UTC, skipped", report)


if __name__ == "__main__":
    unittest.main()
