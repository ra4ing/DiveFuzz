"""Concurrent seeds must share exact per-opcode XOR uniqueness state."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from generator.reg_analyzer.xor_cache_sqlite import prepare, check_and_add


def _insert_overlap(path):
    cache = Path(path)
    return sum(check_and_add(cache, 'add', i) for i in range(64))


class ExactCacheTest(unittest.TestCase):
    def test_parallel_duplicate_inserts_are_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            prepare(cache)
            with ProcessPoolExecutor(max_workers=4) as pool:
                successes = list(pool.map(_insert_overlap, [temp] * 4))
            self.assertEqual(sum(successes), 64)
            conn = sqlite3.connect(cache / 'xor_values.sqlite3')
            try:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM values_seen').fetchone()[0], 64)
            finally:
                conn.close()
            self.assertFalse(check_and_add(cache, 'add', 0))
            self.assertTrue(check_and_add(cache, 'sub', 0))


if __name__ == '__main__':
    unittest.main()
