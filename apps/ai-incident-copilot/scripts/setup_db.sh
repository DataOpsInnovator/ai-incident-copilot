#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
#
# Idempotent: pull the Oracle 26ai Free image, run a container named oracle26ai,
# wait for it to be ready. Safe to re-run — exits early if everything is already up.

set -euo pipefail

IMAGE="container-registry.oracle.com/database/free:23.26.1.0"
NAME="oracle26ai"
PORT="${ORACLE_PORT:-1521}"
PASSWORD="${ORACLE_PWD:-Welcome_123}"
VOLUME="${NAME}-data"

if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "[setup_db] $NAME is already running"
elif docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "[setup_db] $NAME exists but is stopped — starting"
    docker start "$NAME" >/dev/null
else
    echo "[setup_db] pulling $IMAGE (this can take 5–15 min on first run)"
    docker pull "$IMAGE"
    echo "[setup_db] starting $NAME on port $PORT (data volume: $VOLUME)"
    docker run -d --name "$NAME" \
        -p "${PORT}:1521" \
        -e ORACLE_PWD="$PASSWORD" \
        -v "${VOLUME}:/opt/oracle/oradata" \
        "$IMAGE" >/dev/null
fi

echo "[setup_db] waiting for SQL*Plus to accept connections..."
# Probe connectability, not log content. macOS / Docker Desktop sleep-wake
# can leave `docker logs` returning stale state, wedging a log-grep loop
# even when the listener is healthy. Each sqlplus call is independent.
MAX_WAIT_S="${MAX_WAIT_S:-900}"
deadline=$(( $(date +%s) + MAX_WAIT_S ))
until docker exec "$NAME" sh -c \
        "echo 'SELECT 1 FROM DUAL;' | sqlplus -S -L system/${PASSWORD}@FREEPDB1" 2>&1 \
        | grep -q '^----------'; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "[setup_db] timed out after ${MAX_WAIT_S}s waiting for listener" >&2
        echo "[setup_db] last 20 log lines:" >&2
        docker logs --tail 20 "$NAME" >&2 || true
        exit 1
    fi
    sleep 5
done

# Create the application schema. Idempotent: drops + recreates the user.
# VECTOR columns require automatic segment space management — SYSTEM
# tablespace uses manual SSM, so we cannot just connect as `system`.
APP_USER="${APP_USER:-copilot}"
APP_PWD="${APP_PWD:-Welcome_123}"
echo "[setup_db] bootstrapping application user: $APP_USER"
docker exec -i "$NAME" sqlplus -S "system/${PASSWORD}@FREEPDB1" <<SQL
WHENEVER SQLERROR EXIT FAILURE
SET FEEDBACK OFF
BEGIN
  EXECUTE IMMEDIATE 'DROP USER ${APP_USER} CASCADE';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -1918 THEN RAISE; END IF;  -- ORA-01918: user does not exist
END;
/
CREATE USER ${APP_USER} IDENTIFIED BY "${APP_PWD}"
    DEFAULT TABLESPACE USERS
    QUOTA UNLIMITED ON USERS;
GRANT CONNECT, RESOURCE TO ${APP_USER};
GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE TO ${APP_USER};
GRANT DB_DEVELOPER_ROLE TO ${APP_USER};
EXIT;
SQL

echo "[setup_db] ready — DSN = localhost:${PORT}/FREEPDB1, user = ${APP_USER}"
