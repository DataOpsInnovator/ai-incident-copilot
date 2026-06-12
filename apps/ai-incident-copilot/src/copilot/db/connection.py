# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""Oracle 26ai connection helpers — thin-mode pool, no Instant Client required."""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache

import oracledb
from dotenv import load_dotenv

load_dotenv()


def _settings() -> dict[str, str]:
    return {
        "user": os.environ["ORACLE_USER"],
        "password": os.environ["ORACLE_PASSWORD"],
        "dsn": os.environ["ORACLE_DSN"],
    }


@lru_cache(maxsize=1)
def get_pool() -> oracledb.ConnectionPool:
    return oracledb.create_pool(min=1, max=4, increment=1, **_settings())


@contextmanager
def connection() -> oracledb.Connection:
    pool = get_pool()
    conn = pool.acquire()
    try:
        yield conn
    finally:
        pool.release(conn)
