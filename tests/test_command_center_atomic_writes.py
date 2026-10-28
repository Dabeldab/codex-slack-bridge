from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from codex_slack_bridge.command_center_server import CommandCenterRuntime, _write_cached_json


def test_concurrent_job_and_cache_writes_use_unique_atomic_temporary_files(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.instance_id = "runtime-concurrency-test"
    record = {"id": "cc-concurrent", "status": "running"}

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(runtime._write_job, {**record, "sequence": index}) for index in range(100)]
        cache_futures = [
            pool.submit(_write_cached_json, tmp_path / "cache.json", {"sequence": index})
            for index in range(100)
        ]
        for future in [*futures, *cache_futures]:
            future.result()

    assert json.loads((runtime.jobs_dir / "cc-concurrent.json").read_text(encoding="utf-8"))["id"] == "cc-concurrent"
    assert isinstance(json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))["sequence"], int)
    assert list(tmp_path.rglob("*.tmp")) == []
