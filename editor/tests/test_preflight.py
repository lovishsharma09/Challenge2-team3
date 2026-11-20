import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from editor import preflight as P


class PreflightTest(unittest.TestCase):
    def run_quiet(self, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = P.run(**kw)
        return code, buf.getvalue()

    def test_a_failing_check_makes_the_demo_not_ready_and_never_raises(self):
        with mock.patch.object(P, "check_person_c", side_effect=RuntimeError("package missing")):
            code, out = self.run_quiet()
        self.assertEqual(code, 1)
        self.assertIn("FAIL  Person C", out)
        self.assertIn("NOT READY (1 problem(s))", out)

    def test_everything_ok_is_ready_and_the_live_check_is_opt_in(self):
        names = ("check_dependencies", "check_person_c", "check_batch", "check_nutrition_db", "check_gateway_settings", "check_offline_engine")
        with mock.patch.multiple(P, **{n: (lambda: "fine") for n in names}), \
                mock.patch.object(P, "check_gateway_live", side_effect=AssertionError("must not run without --live")):
            code, out = self.run_quiet()
        self.assertEqual(code, 0)
        self.assertIn("READY", out)
        self.assertIn("add --live", out)

    def test_live_check_runs_with_the_flag_and_its_failure_is_reported(self):
        names = ("check_dependencies", "check_person_c", "check_batch", "check_nutrition_db", "check_gateway_settings", "check_offline_engine")
        with mock.patch.multiple(P, **{n: (lambda: "fine") for n in names}), mock.patch.object(P, "check_gateway_live", side_effect=OSError("timeout")):
            code, out = self.run_quiet(live=True)
        self.assertEqual(code, 1)
        self.assertIn("FAIL  live gateway: OSError: timeout", out)

    def test_missing_gateway_settings_are_named_but_no_secret_is_printed(self):
        with mock.patch.object(P, "_env", lambda name: ""):
            with self.assertRaises(RuntimeError) as ctx:
                P.check_gateway_settings()
        self.assertIn("TESSERACTED_API_KEY", str(ctx.exception))
        env = {"TESSERACTED_BASE_URL": "http://x", "TESSERACTED_API_KEY": "sk-VERY-SECRET", "EDITOR_LLM_MODEL": "org/model"}
        with mock.patch.object(P, "_env", lambda name: env.get(name, "")):
            self.assertNotIn("sk-VERY-SECRET", P.check_gateway_settings())


if __name__ == "__main__":
    unittest.main()
