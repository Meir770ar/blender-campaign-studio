import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import character_library as library
import heygen_bridge


class CharacterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'frame.png'; self.image.write_bytes(b'reviewed identity fixture')
        self.file = self.root / 'card.json'
        self.cards = self.root / 'library'
        self.connection = {'cli_entry': 'fixture.mjs', 'character_library': str(self.cards)}
        self.card = {'id': 'host', 'name': 'Studio host', 'kind': 'designed-character', 'heygen_group_id': 'group',
                     'looks': [{'id': 'look', 'label': 'Neutral studio', 'engine': 'iv-quality'}],
                     'voice': {'provider': 'elevenlabs', 'id': 'voice', 'language': 'Hebrew'},
                     'continuity': {'wardrobe': 'Dark blue jacket', 'lighting': 'Soft key from camera left',
                                    'framing': 'Medium shot at eye level', 'voice_direction': 'Warm, clear, restrained'},
                     'references': [str(self.image)]}
        self.live = {'groupId': 'group', 'engines': [{'engine': 'iv-quality', 'available': True}]}

    def save(self, card=None):
        self.file.write_text(json.dumps(card or self.card), encoding='utf-8')
        with patch.object(library, 'cli', return_value=self.live):
            return library.save(self.file, self.cards, self.connection)

    def test_library_keeps_immutable_revisions_and_local_reference_copy(self):
        first = self.save()
        card = library.read(self.cards, 'host')
        self.assertEqual(Path(card['references'][0]['path']).read_bytes(), self.image.read_bytes())
        revised = json.loads(json.dumps(self.card)); revised['continuity']['wardrobe'] = 'Light grey jacket'
        second = self.save(revised)
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertTrue(Path(first['card']).exists())

    def test_wrong_identity_or_engine_cannot_enter_library(self):
        self.live['groupId'] = 'other-group'
        with self.assertRaisesRegex(ValueError, 'identity or engine'):
            self.save()
        self.assertFalse((self.cards / 'host' / 'current.json').exists())

    def test_real_person_requires_existing_consent_evidence(self):
        with self.assertRaisesRegex(ValueError, 'consent'):
            self.save({**self.card, 'kind': 'real-person'})

    def test_request_binds_revision_and_rejects_later_tampering(self):
        self.save()
        card = library.read(self.cards, 'host')
        audio = self.root / 'audio.json'; audio.write_text('{}', encoding='utf-8')
        out = self.root / 'request.json'
        library.make_request(card, 'look', audio, 'Opening line', out)
        request = json.loads(out.read_text(encoding='utf-8'))
        heygen_bridge.validate_character(request, self.connection)
        with self.assertRaisesRegex(ValueError, 'differs'):
            heygen_bridge.validate_character({**request, 'options': {**request['options'], 'avatar': 'different'}}, self.connection)
        path = self.cards / 'host' / 'revisions' / (card['revision'] + '.json')
        altered = json.loads(path.read_text(encoding='utf-8')); altered['voice']['id'] = 'changed'
        path.write_text(json.dumps(altered), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'altered'):
            heygen_bridge.validate_character(request, self.connection)

    def test_library_request_cannot_overwrite_existing_request(self):
        self.save(); card = library.read(self.cards, 'host')
        audio = self.root / 'audio.json'; audio.write_text('{}', encoding='utf-8')
        out = self.root / 'request.json'; out.write_text('existing user file', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            library.make_request(card, 'look', audio, 'Opening line', out)
        self.assertEqual(out.read_text(encoding='utf-8'), 'existing user file')


if __name__ == '__main__':
    unittest.main()
