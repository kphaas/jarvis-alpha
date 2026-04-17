"""Root conftest — adds repo root to sys.path for test discovery.

This allows tests to import top-level packages (brain, gateway, common)
without installing the repo as a pip package.

Standard pytest idiom. Runtime code is unaffected — production services
run from their own working directories and never import cross-module.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
