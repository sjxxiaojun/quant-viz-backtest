"""Tests must never touch the user's live SQLite accounts or research artifacts."""
import os
import tempfile
from pathlib import Path

_test_runtime = tempfile.TemporaryDirectory(prefix="momo-tests-")
os.environ["QUANT_RUNTIME_DIR"] = _test_runtime.name
os.environ["QUANT_DB_PATH"] = str(Path(_test_runtime.name) / "legacy-fixture.db")
os.environ["QUANT_BACKEND_LOG"] = str(Path(_test_runtime.name) / "backend.log")


def pytest_sessionfinish(session, exitstatus):
    import sys
    if "main" in sys.modules:
        sys.modules["main"].job_queue.stop()
