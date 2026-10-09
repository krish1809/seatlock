"""The same 1,000 opposing pairs as reproduce.py, with seat ids sorted first.

Both transactions now lock the lower seat_id first. Whoever gets it first gets
both; the other waits for the first lock and never holds anything the winner
needs, so no wait cycle can form. Expect zero 40P01 errors.

Usage: python experiments/deadlock/fixed.py   (or `make deadlock`)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import random_pairs, record, reseed, run_pairs  # noqa: E402

if __name__ == "__main__":
    reseed()
    result = run_pairs(random_pairs(1000), ordered=True)
    print(result)
    record("ordered", result)
