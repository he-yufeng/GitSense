"""The package version must agree with pyproject.toml at release time."""

from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="stdlib tomllib needs Python 3.11+")

import gitsense


def test_version_matches_pyproject():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert gitsense.__version__ == pyproject["project"]["version"]
