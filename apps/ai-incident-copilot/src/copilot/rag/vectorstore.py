# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""Thin wrapper around langchain-oracledb's OracleVS for the demo's two corpora."""

from __future__ import annotations

from langchain_oracledb.vectorstores import OracleVS
from langchain_oracledb.vectorstores.utils import DistanceStrategy

from copilot.db.connection import get_pool
from copilot.rag.embedder import _model


def incidents_store() -> OracleVS:
    return OracleVS(
        client=get_pool().acquire(),
        embedding_function=_model(),
        table_name="incidents",
        distance_strategy=DistanceStrategy.COSINE,
        query="text",
    )


def runbooks_store() -> OracleVS:
    return OracleVS(
        client=get_pool().acquire(),
        embedding_function=_model(),
        table_name="runbooks",
        distance_strategy=DistanceStrategy.COSINE,
        query="text",
    )
