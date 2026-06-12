# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""Smoke tests — must stay fast and import-safe (no DB / no model)."""

from __future__ import annotations

import importlib


def test_package_imports():
    importlib.import_module("copilot")
    importlib.import_module("copilot.db.connection")
    importlib.import_module("copilot.rag.embedder")


def test_schema_sql_has_vector_column():
    """The schema must declare 384-dim FLOAT32 vector columns or the demo can't work."""
    from pathlib import Path

    schema = Path(__file__).resolve().parents[1] / "src" / "copilot" / "db" / "schema.sql"
    text = schema.read_text()
    assert "VECTOR(384, FLOAT32)" in text
    assert "CREATE VECTOR INDEX" in text
