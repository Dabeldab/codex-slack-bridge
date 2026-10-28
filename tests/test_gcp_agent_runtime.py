from __future__ import annotations

"""GCP runtime regression surface for the ChatGPT Work production runtime."""

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = Path(__file__).with_name("_legacy_gcp_agent_runtime_tests.py")

_spec = importlib.util.spec_from_file_location("_legacy_gcp_agent_runtime_tests", LEGACY)
assert _spec and _spec.loader
_legacy = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _legacy
_spec.loader.exec_module(_legacy)

for _name in dir(_legacy):
    if _name.startswith("test_") or _name.startswith("Test"):
        globals()[_name] = getattr(_legacy, _name)
