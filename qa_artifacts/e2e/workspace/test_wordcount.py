import unittest
import subprocess
import os

class TestWordcount(unittest.TestCase):
    def setUp(self):
        self.file_path = 'sample.txt'
        self.wordcount_script = 'wordcount.py'
        self.test_file = 'test.txt'
        self.test_file_content = 'test line one\ntest line two\ntest line three'
        with open(self.test_file, 'w') as f:
            f.write(self.test_file_content)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_normal_file(self):
        result = subprocess.run([
            self.wordcount_script, self.file_path
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'words: 9')

    def test_missing_argument(self):
        result = subprocess.run([
            self.wordcount_script
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), 'usage: wordcount.py FILE')

    def test_file_not_found(self):
        result = subprocess.run([
            self.wordcount_script, 'nonexistent.txt'
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), f'error: file not found: nonexistent.txt')

if __name__ == '__main__':
    unittest.main()