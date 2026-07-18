import statistics
import subprocess
import time

import pytest

MAX_STARTUP_SECONDS = 0.4
RUNS_PER_COMMAND = 3


@pytest.mark.parametrize("flag", ["--version", "--list-issue-codes", "--list-fields", "--list-configs"])
def test_cli_startup_time(flag):
    times = []
    for _ in range(RUNS_PER_COMMAND):
        t0 = time.perf_counter()
        result = subprocess.run(["uv", "run", "kvet", flag], capture_output=True, text=True)
        times.append(time.perf_counter() - t0)

    median = statistics.median(times)
    assert result.returncode == 0, f"kvet {flag} failed: {result.stderr}"
    assert (
        median < MAX_STARTUP_SECONDS
    ), f"kvet {flag} too slow: median {median:.3f}s > {MAX_STARTUP_SECONDS}s (times: {[f'{t:.3f}s' for t in times]})"
