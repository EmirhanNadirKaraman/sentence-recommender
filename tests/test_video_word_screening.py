"""Screening must not mistake a familiar headword for a known idiom."""
import unittest
import tempfile
from pathlib import Path
from tools.screen_video_word_picker import screen, plain, goethe_entries


def card(word, *keys):
    return {'id': word, 'word': word, 'members': [{'key': key, 'kind': 'pattern'} for key in (keys or (word,))]}


class VideoWordScreeningTests(unittest.TestCase):
    def test_explicit_cognate_has_visible_reason(self):
        result = screen({'cards': [card('der Computer')]}, {})
        reason = result['cards'][0]['auto_no']
        self.assertIn('Computer → computer', reason['text'])
        self.assertEqual(result['screening']['counts']['english-cognate'], 1)

    def test_false_friends_stay_manual(self):
        cards = [card(w) for w in ['das Gift', 'der Rat', 'aktuell', 'eventuell', 'bekommen', 'sensibel']]
        screen({'cards': cards}, {})
        self.assertTrue(all('auto_no' not in c for c in cards))

    def test_unknown_usage_keeps_whole_family_manual(self):
        cards = [card('der Kontakt', 'der Kontakt', 'mit jdm. in Kontakt treten')]
        screen({'cards': cards}, {})
        self.assertNotIn('auto_no', cards[0])

    def test_level_match_keeps_source_and_noun_case(self):
        levels = {'mittel': {'level': 'A1', 'entry': 'mittel', 'page': 19, 'source': 'https://example.org/a1.pdf'}}
        cards = [card('mittel'), card('das Mittel')]
        screen({'cards': cards}, levels)
        evidence = cards[0]['auto_no']['members'][0]['evidence'][0]
        self.assertEqual(evidence['source'], 'https://example.org/a1.pdf')
        self.assertIn('s. 19', evidence['text'])
        self.assertNotIn('auto_no', cards[1])

    def test_reclassification_removes_stale_auto_reason(self):
        cards = [card('unverified')]
        cards[0]['auto_no'] = {'text': 'old heuristic'}
        screen({'cards': cards}, {})
        self.assertNotIn('auto_no', cards[0])

    def test_pdf_example_words_are_not_headwords(self):
        page = '<page><line xMin="142" yMin="120"><word xMax="182">kleben,</word><word xMax="290">Aspekt</word></line><line xMin="235" yMin="150"><word xMax="290">Hypothese</word></line></page>'
        xml = '<html xmlns="http://www.w3.org/1999/xhtml"><body>' + '<page/>' * 8 + page + '<page/>' * 18 + '</body></html>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'a1.html'
            path.write_text(xml)
            entries = goethe_entries(path, 'A1')
        self.assertIn('kleben', entries)
        self.assertNotIn('Aspekt', entries)
        self.assertNotIn('Hypothese', entries)

    def test_only_plain_words_are_normalized(self):
        self.assertEqual(plain('die Organisation'), 'Organisation')
        self.assertIsNone(plain('auf etw. verzichten'))
        self.assertIsNone(plain('etw. (Akk) aufgeben'))


if __name__ == '__main__':
    unittest.main()
