import unittest
from coding_intent import detect_coding_intent

class IntentTests(unittest.TestCase):
    def test_java_voice(self):
        result=detect_coding_intent('Джарвис, создай проект на Java для заметок')
        self.assertEqual(result.language,'java')
    def test_roblox_voice(self):
        result=detect_coding_intent('Джарвис, напиши скрипт для Roblox, который даёт монеты')
        self.assertEqual(result.language,'luau')
    def test_open_non_coding_falls_through(self):
        self.assertIsNone(detect_coding_intent('Открой Roblox Studio'))
        self.assertIsNone(detect_coding_intent('Расскажи про Java и Roblox'))
    def test_negation(self):
        self.assertIsNone(detect_coding_intent('Джарвис, не создавай проект Java'))
    def test_ambiguous(self):
        self.assertIsNone(detect_coding_intent('Напиши проект на Java и Roblox'))

if __name__=='__main__': unittest.main()
