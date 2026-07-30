# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

"""On-disk, content-addressed cache for herd7 allowed-outcome sets.

The allowed set herd7 returns is a pure function of the ``.litmus`` text (herd7
is deterministic given identical input), so a cache keyed on the SHA-256 of the
litmus *content* is sound: identical litmus texts always yield identical allowed
sets.

This pays off most in deterministic generation, where every seed of the same
family emits byte-identical litmus -- without a cache herd7 recomputes the same
answer ``seeds_num`` times. With a cache, each distinct litmus is solved once,
both within a run and across runs.

Concurrency
-----------
The cache is a directory holding one JSON file per content hash. Writes are
atomic (``tempfile`` + ``os.replace``), so parallel worker processes share the
cache through the filesystem without locks. Two workers that miss the same key
simultaneously both compute and write; the values are identical, so the last
writer wins harmlessly, and a reader never observes a partially-written file.

Versioning
----------
A ``v`` field is stored in each entry and also names a versioned subdirectory.
Bump :data:`CACHE_VERSION` to invalidate every entry at once -- e.g. after a
herd7 upgrade that changes its model, or a serialization-format change.
"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

# Bump to invalidate the entire cache (herd7 model change, key/format change).
CACHE_VERSION = "2"

# The ``RISCV <name>`` header is cosmetic: herd7 uses it only as the test label,
# never in the allowed-set computation. Two seeds of the same family (identical
# instruction topology, different per-seed names) therefore yield identical
# allowed sets. Normalizing the header line before hashing lets them share one
# cache entry, so within one run of N seeds across M families only M herd solves
# happen (not N).
_NAME_HEADER = re.compile(r"^RISCV .*$", re.MULTILINE)

class HerdCache:
    """Content-addressed on-disk cache of herd allowed-outcome sets.

    Tracks per-instance hit/miss counters for visibility; in parallel mode each
    worker process owns its own instance (and thus its own counters), while the
    underlying files are shared.
    """

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir) / f"v{CACHE_VERSION}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(litmus_text):
        normalized = _NAME_HEADER.sub("RISCV <n>", litmus_text, count=1)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _entry_path(self, litmus_text):
        return self.cache_dir / f"{self._key(litmus_text)}.json"

    def get(self, litmus_text):
        """Return the cached allowed set for ``litmus_text``, or ``None`` on a miss."""
        path = self._entry_path(litmus_text)
        try:
            text = path.read_text()
        except FileNotFoundError:
            self.misses += 1
            return None
        except OSError:
            self.misses += 1
            return None
        try:
            data = json.loads(text)
        except ValueError:
            # Corrupt entry: treat as miss; the next put() overwrites it.
            self.misses += 1
            return None
        if data.get("v") != CACHE_VERSION:
            self.misses += 1
            return None
        allowed = {
            tuple((str(k), int(v)) for k, v in outcome)
            for outcome in data["allowed"]
        }
        self.hits += 1
        return allowed

    def put(self, litmus_text, allowed):
        """Store ``allowed`` (a set of canonical outcomes) for ``litmus_text``."""
        path = self._entry_path(litmus_text)
        payload = json.dumps(
            {
                "v": CACHE_VERSION,
                "allowed": [
                    [[k, v] for (k, v) in outcome] for outcome in sorted(allowed)
                ],
            }
        )
        # Atomic write: temp file in the same dir (so rename stays on one FS),
        # then os.replace() which is atomic on POSIX and Windows.
        fd, tmp = tempfile.mkstemp(dir=str(self.cache_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def stats(self):
        """Per-instance hit/miss counters."""
        return {"hits": self.hits, "misses": self.misses}
