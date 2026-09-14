"""The package version must agree with pyproject.toml at release time."""

from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="stdlib tomllib needs Python 3.11+")


def test_version_matches_pyproject():
    # local import: the importorskip gate must run before gitsense loads
    import gitsense

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert gitsense.__version__ == pyproject["project"]["version"]
