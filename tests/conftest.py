"""Shared test set-up: project on the import path, an empty parts library for every test."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import matplotlib  # noqa: E402

matplotlib.use('Agg')


@pytest.fixture(autouse=True)
def isolated_parts(tmp_path, monkeypatch):
    """Each test gets its own (empty) my_parts.json in a temporary folder."""
    path = tmp_path / 'my_parts.json'
    monkeypatch.setenv('PCFLOW_PARTS', str(path))
    from pcflow import library
    library.reset()
    yield path
    library.reset()
