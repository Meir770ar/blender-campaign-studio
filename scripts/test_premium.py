"""Contract tests for premium direction, shot review and product technique tools."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from campaign_common import sha256_file
from creative_gates import validate
from premium_product import validate_spec
from review_shot import finalize, prepare, sample_times


def valid_direction():
    return {
        'version': 1,
        'project': 'Launch film',
        'outcome': {
            'audience': 'Existing customers comparing the new package on a phone screen.',
            'change': 'Move from uncertainty about the redesign to recognition of the verified product.',
            'evidence': 'The front label and changed closure are shown together in one uninterrupted reveal.',
            'action': 'Open the verified product page after the stable CTA packshot.',
        },
        'concept': {
            'governing_idea': 'Information appears only as the physical package becomes readable.',
            'point_of_view': 'A careful customer inspecting the new package for proof of authenticity.',
            'hook': 'Begin on an incomplete reflection that withholds the label for one beat.',
            'payoff': 'The reflection clears to a stable front label and exact call to action.',
        },
        'visual_system': {
            'attention': 'Begin on the moving edge highlight, transfer to the label, then land on the CTA space.',
            'composition': 'Use restrained asymmetry during motion and a centered final packshot with clear negative space.',
            'camera': 'A shallow approach reveals perspective; it settles before the brand state and does not orbit.',
            'lighting': 'A broad soft source defines the package while one narrow moving reflection performs the reveal.',
            'palette': 'Verified package colors remain neutral against a low-saturation blue-black surround.',
            'materials': 'Gloss is described by long gradients; the printed label remains diffuse and color accurate.',
            'continuity': 'Light travels screen-left to screen-right and hands the same direction into the next graphic.',
        },
        'sound_system': {
            'voice': 'No voice in this beat; narration resumes only after the label becomes stable.',
            'ambience': 'A very low controlled room bed prevents a vacuum without suggesting a real location.',
            'music': 'The sustained phrase opens harmonically when the front label becomes readable.',
            'effects': 'One restrained material sweep follows the reflection and ends before the hold.',
            'silence': 'The first six frames remain nearly silent so the reveal has contrast.',
        },
        'delivery': [{
            'id': 'vertical-main', 'width': 1080, 'height': 1920, 'platform': 'Instagram Reels',
            'safe_areas': 'Keep the label inside the central 80 percent and the lower CTA above platform controls.',
        }],
        'open_decisions': [],
    }


def valid_shots(kind='blender', status='planned'):
    return {
        'version': 1,
        'fps': 24,
        'shots': [{
            'id': 'S04',
            'purpose': 'Convert the visual question into verified recognition of the new package.',
            'action': 'A controlled reflection crosses the pack while the camera approaches and settles.',
            'start_state': 'The silhouette is readable but the front label is intentionally incomplete.',
            'end_state': 'The complete front label and closure are stable with space for the CTA.',
            'duration_frames': 72,
            'attention': {
                'start': 'The eye begins on the bright left edge of the package.',
                'path': 'The moving reflection carries attention across the material into the label.',
                'end': 'The eye lands on the verified wordmark before the cut.',
            },
            'camera': {
                'mode': 'reveal',
                'reason': 'The approach changes incomplete geometry into readable proof.',
                'start_composition': 'Three-quarter silhouette with open space on screen right.',
                'end_composition': 'Near-front packshot with undistorted label and CTA space.',
                'velocity': 'Quintic ease into motion, restrained middle speed and a twelve-frame settled hold.',
                'settle_frames': 12,
                'handles_frames': 4,
            },
            'lighting': {
                'motivation': 'A large off-camera soft source behaves like a controlled studio reflection card.',
                'subject_priority': 'The label remains below clipping while the edge highlight defines the package.',
                'background': 'A low-contrast blue-black sweep separates the silhouette without a halo.',
                'exposure_risk': 'The narrow reflection can clip embossed letters and must be checked through motion.',
            },
            'continuity': {
                'incoming': 'The previous graphic exits toward screen right on the same visual vector.',
                'outgoing': 'The final packshot holds long enough for the centered CTA cut.',
                'screen_direction': 'Attention moves left to right and ends on axis.',
            },
            'sound': {
                'foreground': 'One short material sweep supports the highlight without masking speech.',
                'perspective': 'Close and dry, matching a controlled tabletop product distance.',
                'transition': 'The sweep resolves before the next narration consonant begins.',
            },
            'source': {
                'kind': kind, 'status': status,
                'description': 'Original Blender scene built from the verified client GLB.',
            },
            'acceptance': [{
                'id': 'label-readable',
                'check': 'The approved front label remains geometrically exact and readable during the settled hold.',
                'evidence': 'Inspect the full motion and cite a settled timestamp showing the complete label.',
            }],
        }],
    }


class CreativeGateTests(unittest.TestCase):
    def test_heygen_avatar_requires_paid_motion_review_and_approval_reference(self):
        shots = valid_shots('heygen-avatar', 'planned')
        report = validate(valid_direction(), shots, 'paid-motion')
        self.assertFalse(report['ready'])
        self.assertTrue(any('.generation is required' in error for error in report['errors']))
        shots['shots'][0]['source']['status'] = 'styleframe-approved'
        shots['shots'][0]['generation'] = {'provider': 'heygen', 'semantic_fingerprint': 'a' * 64,
                                         'approval_ref': 'exact-current-task', 'max_attempts': 1}
        self.assertTrue(validate(valid_direction(), shots, 'paid-motion')['ready'])

    def test_complete_styleframe_contract_is_ready(self):
        report = validate(valid_direction(), valid_shots(), 'styleframes')
        self.assertTrue(report['ready'], report['errors'])
        self.assertIn('not artistic quality', report['limits'][0])

    def test_aesthetic_adjective_is_not_direction(self):
        direction = valid_direction()
        direction['concept']['governing_idea'] = 'cinematic'
        report = validate(direction, None, 'direction')
        self.assertFalse(report['ready'])
        self.assertTrue(any('adjective' in error for error in report['errors']))

    def test_paid_motion_requires_styleframe_and_authorization_reference(self):
        shots = valid_shots('grok-video', 'planned')
        report = validate(valid_direction(), shots, 'paid-motion')
        self.assertFalse(report['ready'])
        self.assertTrue(any('.generation is required' in error for error in report['errors']))
        self.assertTrue(any('styleframe approval' in error for error in report['errors']))

    def test_paid_motion_contract_can_pass_without_granting_authorization(self):
        shots = valid_shots('grok-video', 'styleframe-approved')
        shots['shots'][0]['generation'] = {
            'provider': 'grok', 'semantic_fingerprint': 'b' * 64,
            'approval_ref': 'conversation-item-123', 'max_attempts': 1,
        }
        report = validate(valid_direction(), shots, 'paid-motion')
        self.assertTrue(report['ready'], report['errors'])
        self.assertIn('S04', report['summary']['paid_motion_shots'])
        self.assertTrue(any('provider_jobs.py' in item for item in report['limits']))

    def test_blocking_decision_stops_paid_motion(self):
        direction = valid_direction()
        direction['open_decisions'] = [{
            'question': 'Which verified package label is legally approved for the final reveal?',
            'owner': 'Client brand lead', 'blocking': True,
        }]
        report = validate(direction, valid_shots(), 'paid-motion')
        self.assertFalse(report['ready'])
        self.assertIn('1 blocking direction decision(s) remain open', report['errors'])

    def test_rough_cut_requires_selected_media(self):
        report = validate(valid_direction(), valid_shots(status='ready'), 'rough-cut')
        self.assertFalse(report['ready'])
        self.assertTrue(any('must be selected' in error for error in report['errors']))


class PremiumProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'product.glb').write_bytes(b'contract-only fixture')
        self.spec = {
            'version': 1, 'shot_id': 'S04',
            'intent': 'Reveal the verified front label, then hold the accurate packshot for the CTA.',
            'model': 'product.glb', 'width': 320, 'height': 180, 'fps': 24, 'frames': 48, 'samples': 8,
            'camera': {'lens_mm': 70, 'distance': 6, 'height_offset': .1, 'travel': .3,
                       'yaw_start_deg': -7, 'yaw_end_deg': 2, 'fstop': 5.6},
            'motion': {'settle_fraction': .75, 'sweep_side': 'left'},
            'lighting': {'key_energy': 800, 'fill_energy': 200, 'rim_energy': 900, 'sweep_energy': 1100},
            'look': {'background_rgba': [.02, .03, .04, 1], 'floor_roughness': .4,
                     'world_strength': .02, 'glare': False},
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        path = self.root / 'spec.json'
        path.write_text(json.dumps(self.spec), encoding='utf-8')
        return path

    def test_spec_resolves_local_model(self):
        result = validate_spec(self.write())
        self.assertEqual(result['model'], str((self.root / 'product.glb').resolve()))

    def test_spec_rejects_generic_intent(self):
        self.spec['intent'] = 'cinematic'
        with self.assertRaisesRegex(ValueError, 'at least 24'):
            validate_spec(self.write())

    def test_spec_rejects_flat_light_hierarchy(self):
        self.spec['lighting']['fill_energy'] = 900
        with self.assertRaisesRegex(ValueError, 'must exceed fill_energy'):
            validate_spec(self.write())


class ShotReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.media = self.root / 'shot.mp4'
        self.media.write_bytes(b'immutable review fixture')
        self.packet_path = self.root / 'review-packet.json'
        self.packet = {
            'version': 1,
            'shot': valid_shots()['shots'][0],
            'media': {'path': str(self.media), 'sha256': sha256_file(self.media),
                      'duration_seconds': 3.0, 'fps': 24, 'width': 320, 'height': 180,
                      'codec': 'h264', 'has_audio': False},
            'evidence_frames': [],
        }
        self.packet_path.write_text(json.dumps(self.packet), encoding='utf-8')
        self.findings = {
            'version': 1, 'packet': str(self.packet_path), 'reviewer': 'Codex review',
            'reviewed_complete_motion': True, 'reviewed_with_sound': False,
            'criteria': [{'id': 'label-readable', 'status': 'pass',
                          'evidence_time_seconds': 2.5,
                          'note': 'The complete approved label is readable throughout the final hold.'}],
            'issues': [], 'overall_note': 'All specified visual evidence passed this bounded review.',
        }

    def tearDown(self):
        self.temp.cleanup()

    def write_findings(self):
        path = self.root / 'findings.json'
        path.write_text(json.dumps(self.findings), encoding='utf-8')
        return path

    def test_sample_times_include_safe_first_and_last_frames(self):
        self.assertEqual(sample_times(2.0, 24, 3), [0.0, 0.979167, 1.958333])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_prepare_extracts_timecoded_evidence_from_real_video(self):
        source = self.root / 'real-shot.mp4'
        subprocess.run([
            shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=0x183450:s=160x90:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-an', '-n', str(source),
        ], check=True)
        shots = self.root / 'shots.json'
        shots.write_text(json.dumps(valid_shots()), encoding='utf-8')
        packet = prepare(source, shots, 'S04', self.root / 'prepared', 3)
        self.assertEqual(len(packet['evidence_frames']), 3)
        self.assertTrue(all(Path(item['path']).is_file() for item in packet['evidence_frames']))
        self.assertTrue((self.root / 'prepared/review.html').is_file())
        self.assertFalse(packet['media']['has_audio'])

    def test_complete_findings_derive_pass_without_score(self):
        report = finalize(self.packet_path, self.write_findings(), self.root / 'final.json')
        self.assertEqual(report['disposition'], 'passed')
        self.assertNotIn('score', report)

    def test_changed_media_invalidates_review(self):
        findings = self.write_findings()
        self.media.write_bytes(b'changed after extraction')
        with self.assertRaisesRegex(ValueError, 'changed'):
            finalize(self.packet_path, findings, self.root / 'final.json')

    def test_failed_criterion_requires_corrective_issue(self):
        self.findings['criteria'][0]['status'] = 'fail'
        with self.assertRaisesRegex(ValueError, 'requires at least one'):
            finalize(self.packet_path, self.write_findings(), self.root / 'final.json')

    def test_major_issue_derives_revision(self):
        self.findings['issues'] = [{
            'severity': 'major', 'time_seconds': 1.25,
            'description': 'The moving highlight clips the embossed mark during the reveal.',
            'action': 'Lower sweep energy and rerender only this shot revision.',
        }]
        report = finalize(self.packet_path, self.write_findings(), self.root / 'final.json')
        self.assertEqual(report['disposition'], 'revise')


if __name__ == '__main__':
    unittest.main(verbosity=2)
