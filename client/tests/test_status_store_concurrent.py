"""Concurrent save_status calls don't collide on one temp file (several network threads
plus the supervisor write status.json; seen on a fresh 0.8.0 install)."""
import json
import sys
import threading

import pytest

from client.status_store import save_status


# Windows can refuse os.replace onto a file another thread is replacing at that moment,
# whatever the temp name; the Windows service writes status through its own path.
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX rename semantics")
def test_concurrent_writers(tmp_path):
    path = str(tmp_path / "status.json")
    errors = []

    def writer(i):
        for _ in range(50):
            try:
                save_status(path, "idle", f"writer {i}")
            except OSError as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert json.load(open(path))["state"] == "idle"
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]
