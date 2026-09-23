"""Contract tests for the reusable Blender campaign technique library."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from campaign_techniques import interpolate_track, source_assets, validate_spec


class TechniqueContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for name in ("plate.png", "insert.png", "back.png", "middle.png", "front.png"):
            (self.root / name).write_bytes(b"contract fixture")
        (self.root / "product.glb").write_bytes(b"contract fixture")
        self.common = {
            "version": 1,
            "shot_id": "TECH-01",
            "intent": "Demonstrate one visible campaign compositing job and hold the resolved result.",
            "width": 320,
            "height": 180,
            "fps": 24,
            "frames": 24,
            "samples": 8,
            "acceptance": [{
                "id": "visible-result",
                "check": "The intended result remains readable through the complete rendered motion.",
                "evidence": "Inspect every rendered frame and cite the final settled composition.",
            }],
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, spec):
        path = self.root / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def screen(self):
        return {
            **copy.deepcopy(self.common),
            "technique": "planar-screen-replacement",
            "plate": "plate.png",
            "replacement": "insert.png",
            "insert_opacity": 1,
            "track": [
                {"frame": 1, "corners": {
                    "upper_left": [.2, .8], "upper_right": [.8, .78],
                    "lower_left": [.24, .25], "lower_right": [.76, .27],
                }},
                {"frame": 24, "corners": {
                    "upper_left": [.18, .82], "upper_right": [.82, .8],
                    "lower_left": [.22, .23], "lower_right": [.78, .25],
                }},
            ],
        }

    def product(self):
        return {
            **copy.deepcopy(self.common),
            "technique": "environment-product-integration",
            "model": "product.glb",
            "environment": {
                "background_rgba": [.02, .03, .05, 1], "floor_rgba": [.08, .1, .14, 1],
                "floor_roughness": .24, "floor_metallic": .15, "world_strength": .04,
            },
            "lighting": {
                "match_reference": "A large cool window appears above camera left in the designed environment.",
                "key_azimuth_deg": -55, "key_elevation_deg": 45, "key_energy": 900,
                "fill_energy": 180, "key_size": 3.5, "key_rgb": [.75, .86, 1],
            },
            "camera": {"lens_mm": 58, "distance": 6, "height_offset": .25,
                       "travel_x": .3, "fstop": 5.6},
            "motion": {"settle_fraction": .75},
        }

    def projection(self):
        return {
            **copy.deepcopy(self.common),
            "technique": "camera-projection-2_5d",
            "layers": [
                {"name": "Background", "image": "back.png", "depth": -1, "width": 10},
                {"name": "Middle", "image": "middle.png", "depth": 0, "width": 8},
                {"name": "Foreground", "image": "front.png", "depth": 1, "width": 7},
            ],
            "camera": {"lens_mm": 50, "distance": 12, "travel_x": .5},
            "motion": {"settle_fraction": .75},
        }

    def test_screen_contract_resolves_local_assets(self):
        result = validate_spec(self.write(self.screen()))
        self.assertEqual(result["plate"], str((self.root / "plate.png").resolve()))
        self.assertEqual(len(source_assets(result)), 2)

    def test_common_contract_rejects_generic_intent(self):
        spec = self.screen()
        spec["intent"] = "cinematic"
        with self.assertRaisesRegex(ValueError, "at least 24"):
            validate_spec(self.write(spec))

    def test_common_contract_rejects_odd_video_dimension(self):
        spec = self.screen()
        spec["width"] = 319
        with self.assertRaisesRegex(ValueError, "even"):
            validate_spec(self.write(spec))

    def test_screen_track_must_cover_complete_timeline(self):
        spec = self.screen()
        spec["track"][-1]["frame"] = 23
        with self.assertRaisesRegex(ValueError, "cover frame 1"):
            validate_spec(self.write(spec))

    def test_screen_track_rejects_inverted_quad(self):
        spec = self.screen()
        spec["track"][0]["corners"]["upper_left"] = [.9, .8]
        with self.assertRaisesRegex(ValueError, "left corners"):
            validate_spec(self.write(spec))

    def test_track_interpolation_is_frame_deterministic(self):
        track = self.screen()["track"]
        middle = interpolate_track(track, 12)
        amount = 11 / 23
        self.assertAlmostEqual(middle["upper_left"][0], .2 + (.18 - .2) * amount)

    def test_product_contract_resolves_glb_and_light_match(self):
        result = validate_spec(self.write(self.product()))
        self.assertEqual(result["model"], str((self.root / "product.glb").resolve()))
        self.assertIn("window", result["lighting"]["match_reference"])

    def test_product_rejects_flat_light_hierarchy(self):
        spec = self.product()
        spec["lighting"]["fill_energy"] = 900
        with self.assertRaisesRegex(ValueError, "below key_energy"):
            validate_spec(self.write(spec))

    def test_product_rejects_unbounded_floor_reflection(self):
        spec = self.product()
        spec["environment"]["floor_metallic"] = .8
        with self.assertRaisesRegex(ValueError, "floor_metallic"):
            validate_spec(self.write(spec))

    def test_projection_contract_requires_three_layers(self):
        spec = self.projection()
        spec["layers"] = spec["layers"][:2]
        with self.assertRaisesRegex(ValueError, "3 to 12"):
            validate_spec(self.write(spec))

    def test_projection_depths_must_be_ordered(self):
        spec = self.projection()
        spec["layers"][2]["depth"] = -.5
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            validate_spec(self.write(spec))

    def test_projection_camera_must_clear_nearest_layer(self):
        spec = self.projection()
        spec["camera"]["distance"] = 6
        spec["layers"][-1]["depth"] = 4
        with self.assertRaisesRegex(ValueError, "at least two units"):
            validate_spec(self.write(spec))

    def test_projection_accepts_narrow_vertical_boundary(self):
        spec = self.projection()
        spec.update(width=180, height=320, frames=12)
        result = validate_spec(self.write(spec))
        self.assertEqual((result["width"], result["height"], result["frames"]), (180, 320, 12))


if __name__ == "__main__":
    unittest.main(verbosity=2)
