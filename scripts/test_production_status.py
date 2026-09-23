"""Read-only dashboard tests; no provider, render or delivery actions."""
import json
from pathlib import Path
import tempfile
import unittest

from production_status import inspect
from studio import main as studio_main


class ProductionStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name).resolve() / "production"
        studio_main(["init", "--project", str(self.project), "--idea", "סרטון בדיקה מלא בעברית"])

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, value):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def test_initialized_project_starts_at_direction_without_authority(self):
        status = inspect(self.project)
        self.assertEqual(status["phase"], "direction")
        self.assertEqual(status["external_actions_authorized_by_initialization"], [])

    def test_failed_gate_errors_are_visible(self):
        self.write("planning/direction-gate-v001.json", {"ready": False, "errors": ["missing concrete hook"]})
        status = inspect(self.project)
        self.assertIn("direction gate: missing concrete hook", status["blockers"])

    def test_unknown_provider_and_render_jobs_are_blockers(self):
        self.write("jobs/provider/job.json", {"id": "provider", "state": "unknown", "request": {"provider": "grok"}})
        self.write("render-jobs/" + "a" * 64 + "/job.json", {"job_id": "a" * 64})
        self.write("render-jobs/" + "a" * 64 + "/dispatch.json", {"status": "failed"})
        blockers = inspect(self.project)["blockers"]
        self.assertTrue(any("provider job provider" in item for item in blockers))
        self.assertTrue(any("render job" in item for item in blockers))

    def test_received_video_with_failed_quality_check_blocks_delivery(self):
        self.write("jobs/clip/job.json", {"id": "clip", "state": "received_needs_review", "request": {"provider": "heygen"}})
        self.assertTrue(any("clip" in item and "received_needs_review" in item for item in inspect(self.project)["blockers"]))

    def test_delivery_without_review_stays_in_review(self):
        for gate in ("direction", "styleframes", "rough-cut"):
            self.write(f"planning/{gate}-gate-v001.json", {"ready": True, "errors": []})
        self.write("delivery-qa-v001.json", {"technical_pass": True, "errors": []})
        status = inspect(self.project)
        self.assertEqual(status["phase"], "review")
        self.assertTrue(any("no finalized shot review" in item for item in status["blockers"]))

    def test_passed_review_and_delivery_complete_the_dashboard(self):
        for gate in ("direction", "styleframes", "rough-cut"):
            self.write(f"planning/{gate}-gate-v001.json", {"ready": True, "errors": []})
        self.write("delivery-qa-v001.json", {"technical_pass": True, "errors": []})
        self.write("reviews/S01/review-report.json", {"shot_id": "S01", "disposition": "passed"})
        self.assertEqual(inspect(self.project)["phase"], "complete")

    def test_non_project_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "initialized production"):
            inspect(self.temp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
