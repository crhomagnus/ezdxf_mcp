from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT / "dxf-workspace"
GENERATED = PROJECT / "tests" / "fixtures" / "generated"
os.environ["EZDXF_MCP_WORKSPACE"] = str(WORKSPACE)


@pytest.fixture(autouse=True)
def clean_sessions():
    from ezdxf_mcp.session import store

    store.clear()
    yield
    store.clear()


@pytest.fixture(scope="session", autouse=True)
def generated_fixtures():
    from tests.fixtures.make_fixtures import main

    main()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    for suffix in ("*.dxf", "*.png", "*.jpg"):
        for fixture in GENERATED.glob(suffix):
            shutil.copy2(fixture, WORKSPACE / fixture.name)
    return WORKSPACE


@pytest.fixture()
def workspace() -> Path:
    return WORKSPACE
