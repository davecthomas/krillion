import time

from krillion.cache_store import SQLiteCacheStore


def test_store_round_trip_expiry_and_persistence(tmp_path):
    path = tmp_path / "c.sqlite"
    s = SQLiteCacheStore(path)
    s.set("k", b"v", ttl_seconds=60)
    assert s.get("k") == b"v"
    assert SQLiteCacheStore(path).get("k") == b"v"  # survives a restart
    s.set("old", b"x", ttl_seconds=0.01)
    time.sleep(0.02)
    assert s.get("old") is None
    s.delete("k")
    assert s.get("k") is None and s.get("missing") is None
