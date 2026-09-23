"""Contract tests for remote rendering; no SSH, GPU render or external mutation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import render_dispatch
import render_worker


class RemoteRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for name in ("jobs", "incoming", "outgoing", "bin", "tools"):
            (self.root / name).mkdir()
        (self.root / "bin/render_blender_job.py").write_text("# fixture", encoding="utf-8")
        (self.root / "tools/blender.exe").write_bytes(b"fixture")
        self.config = {
            "schema_version": 1,
            "root": str(self.root),
            "jobs_root": str(self.root / "jobs"),
            "incoming_root": str(self.root / "incoming"),
            "outgoing_root": str(self.root / "outgoing"),
            "blender": str(self.root / "tools/blender.exe"),
            "render_script": str(self.root / "bin/render_blender_job.py"),
            "max_archive_bytes": 1024 * 1024,
        }
        self.scene = b"immutable blend fixture"
        semantic = {
            "schema_version": 1,
            "blender_version": "5.1.0",
            "scene_file": "bundle/scene.blend",
            "scene_sha256": hashlib.sha256(self.scene).hexdigest(),
            "dependencies": [],
            "profile": {"frame_start": 1, "frame_end": 2, "frame_step": 1,
                        "resolution_x": 64, "resolution_y": 64, "resolution_percentage": 100,
                        "samples": 1, "device": "CUDA", "output_format": "PNG16"},
        }
        self.job_id = render_worker.digest_json(semantic)
        self.job = {"schema_version": 1, "job_id": self.job_id, "semantic": semantic,
                    "prepared_utc": "2026-09-06T00:00:00+00:00"}

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, name="submission.zip", extra=None):
        path = self.root / "incoming" / name
        with zipfile.ZipFile(path, "x") as package:
            package.writestr("job.json", json.dumps(self.job))
            package.writestr("bundle/scene.blend", self.scene)
            if extra:
                package.writestr(*extra)
        return path

    def test_semantic_id_is_canonical_and_stable(self):
        reordered = dict(reversed(list(self.job["semantic"].items())))
        self.assertEqual(render_worker.digest_json(reordered), self.job_id)
        self.assertEqual(render_dispatch.digest_json(reordered), self.job_id)

    def test_submit_is_idempotent_and_preserves_manifest(self):
        archive = self.archive()
        first = render_worker.submit(self.config, archive)
        second = render_worker.submit(self.config, archive)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        installed = json.loads((self.root / "jobs" / self.job_id / "job.json").read_text())
        self.assertEqual(installed, self.job)

    def test_idempotency_uses_semantics_not_preparation_timestamp(self):
        first = self.archive("first.zip")
        render_worker.submit(self.config, first)
        self.job["prepared_utc"] = "2026-09-07T00:00:00+00:00"
        second = self.archive("second.zip")
        result = render_worker.submit(self.config, second)
        self.assertTrue(result["idempotent"])

    def test_remote_submission_rejects_cpu_test_profile(self):
        self.job["semantic"]["profile"]["device"] = "CPU_TEST"
        self.job_id = render_worker.digest_json(self.job["semantic"])
        self.job["job_id"] = self.job_id
        path = self.archive()
        with self.assertRaisesRegex(ValueError, "CUDA or OPTIX"):
            render_worker.validated_archive(path, 1024 * 1024)

    def test_submit_rejects_archive_outside_incoming_root(self):
        archive = self.archive()
        outside = self.root / "outside.zip"
        archive.replace(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            render_worker.submit(self.config, outside)

    def test_archive_rejects_path_traversal(self):
        path = self.archive(extra=("../escape.txt", b"bad"))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            render_worker.validated_archive(path, 1024 * 1024)

    def test_archive_rejects_semantic_mismatch(self):
        self.job["semantic"]["profile"]["samples"] = 2
        path = self.archive()
        with self.assertRaisesRegex(ValueError, "semantic"):
            render_worker.validated_archive(path, 1024 * 1024)

    def make_result(self, tamper=False, extra=False):
        frame_payloads = {"frames/000001.png": b"frame-one", "frames/000002.png": b"frame-two"}
        result = {"schema_version": 1, "job_id": self.job_id, "status": "complete",
                  "frames": [{"name": name.split("/")[-1], "bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest(), "width": 64, "height": 64}
                             for name, payload in frame_payloads.items()]}
        payloads = {"job.json": json.dumps(self.job).encode(), "result.json": json.dumps(result).encode(),
                    "state.json": json.dumps({"status": "complete"}).encode(), **frame_payloads}
        manifest = {"schema_version": 1, "job_id": self.job_id,
                    "files": [{"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                              for name, payload in payloads.items()]}
        if tamper:
            payloads["frames/000002.png"] = b"changed"
        path = self.root / "result.zip"
        with zipfile.ZipFile(path, "x") as package:
            package.writestr("collection-manifest.json", json.dumps(manifest))
            for name, payload in payloads.items():
                package.writestr(name, payload)
            if extra:
                package.writestr("unmanifested.txt", b"no")
        return path

    def test_result_verification_checks_identity_count_and_hashes(self):
        verified = render_dispatch.verify_result_archive(self.make_result(), self.job_id)
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["frames"], 2)

    def test_result_verification_rejects_tamper(self):
        with self.assertRaisesRegex(ValueError, "verification failed"):
            render_dispatch.verify_result_archive(self.make_result(tamper=True), self.job_id)

    def test_result_verification_rejects_unmanifested_member(self):
        with self.assertRaisesRegex(ValueError, "unmanifested"):
            render_dispatch.verify_result_archive(self.make_result(extra=True), self.job_id)

    def test_disappeared_executor_becomes_unknown(self):
        archive = self.archive()
        render_worker.submit(self.config, archive)
        job_dir = self.root / "jobs" / self.job_id
        render_worker.set_state(job_dir, "running")
        render_worker.atomic_json(job_dir / "executor.json", {"pid": 2147483647})
        current = render_worker.status(self.config, self.job_id)
        self.assertEqual(current["status"], "unknown")
        self.assertIn("reconcile", current["error"])

    def test_status_summarizes_verified_frames_without_mutating_ledger(self):
        job_dir = self.root / "jobs" / self.job_id
        job_dir.mkdir()
        render_worker.atomic_json(job_dir / "state.json", {"status": "complete"})
        frames = [{"name": "000001.png"}, {"name": "000002.png"}]
        render_worker.atomic_json(job_dir / "progress.json", {
            "status": "complete", "completed_frames": 2, "total_frames": 2, "frames": frames,
        })

        current = render_worker.status(self.config, self.job_id)

        self.assertNotIn("frames", current["progress"])
        self.assertEqual(current["progress"]["verified_frames"], 2)
        stored = json.loads((job_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["frames"], frames)

    def test_unknown_requires_explicit_reconciliation(self):
        render_worker.submit(self.config, self.archive())
        job_dir = self.root / "jobs" / self.job_id
        render_worker.set_state(job_dir, "unknown")
        self.config["config_path"] = str(self.root / "config.json")
        with self.assertRaisesRegex(ValueError, "--reconciled"):
            render_worker.start_job(self.config, self.job_id)

    def test_global_worker_lock_blocks_second_start(self):
        render_worker.submit(self.config, self.archive())
        (self.root / "worker.lock").write_text(json.dumps({"pid": 123, "job_id": "other"}))
        self.config["config_path"] = str(self.root / "config.json")
        with self.assertRaisesRegex(ValueError, "already locked"):
            render_worker.start_job(self.config, self.job_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
