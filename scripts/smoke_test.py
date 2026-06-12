"""Smoke test: prove the venv can reach Oracle 26ai and call vector functions.

Run from the repo root with the venv active:
    python scripts/smoke_test.py
"""
import oracledb

DSN = "localhost:1521/FREEPDB1"
USER = "system"
PASSWORD = "Welcome_123"

with oracledb.connect(user=USER, password=PASSWORD, dsn=DSN) as conn:
    print(f"oracledb {oracledb.__version__} | thin mode = {conn.thin}")

    with conn.cursor() as cur:
        cur.execute("SELECT BANNER_FULL FROM v$version WHERE ROWNUM = 1")
        print("server :", cur.fetchone()[0])

        cur.execute(
            """
            SELECT VECTOR_DISTANCE(
                TO_VECTOR('[1,2,3]', 3, FLOAT32),
                TO_VECTOR('[4,5,6]', 3, FLOAT32),
                COSINE
            ) FROM dual
            """
        )
        print("cosine :", cur.fetchone()[0])

print("OK")
