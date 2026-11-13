import importlib.util, json, pathlib, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("plan_states", here / "plan_states.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
CONFIG = json.loads((here.parent / "state-sources.json").read_text())


class PlanStates(unittest.TestCase):
    def test_split_states_get_a_job_per_chamber(self):
        jobs, _ = module.plan(CONFIG, only={"ks", "nj"})
        self.assertEqual([(j["state"], j["chamber"]) for j in jobs], [("ks", "upper"), ("ks", "lower"), ("nj", "")])

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


if __name__ == "__main__":
    unittest.main()
