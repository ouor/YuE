from pathlib import Path
import os
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
REPO = APP.parent
sys.path.insert(0, str(APP))


@pytest.fixture
def examples():
    return REPO / "examples"


@pytest.fixture(scope="session")
def server_url():
    return os.environ.get("YUE2_STUDIO_URL", "http://127.0.0.1:7860")
