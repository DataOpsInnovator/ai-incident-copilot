# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""The four LangChain tools the Incident Copilot agent calls.

Each tool is also exposed as a plain Python function (with `_impl` suffix)
so tests can call retrieval directly without going through the LLM.

Tools:
    find_similar_incidents          — pure semantic search over incidents.embedding
    find_similar_incidents_filtered — semantic + WHERE (the killer demo)
    get_runbooks_for_incident       — relational join via incident_runbooks
    get_service_owner               — pure relational on services
"""

from __future__ import annotations

import array
from typing import Optional

from langchain_core.tools import tool

from copilot.db.connection import connection
from copilot.rag.embedder import embed

# Whitelisted columns the LLM can filter on. Keeps the WHERE clause builder
# safe from injection — no string from the LLM is ever interpolated into SQL.
_ALLOWED_REGIONS = {"us-east", "us-west", "eu-west", "ap-south"}
_ALLOWED_CATEGORIES = {
    "latency", "error_rate", "saturation", "availability",
    "data_quality", "auth", "deploy_rollback",
}


def _embed_query(text: str) -> array.array:
    return array.array("f", embed(text))


# ---------------------------------------------------------------------------
# 1) Pure semantic search
# ---------------------------------------------------------------------------

def _find_similar_incidents_impl(query: str, top_k: int = 5) -> list[dict]:
    qv = _embed_query(query)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT incident_id, service_name, category, severity, region,
                   TO_CHAR(occurred_at, 'YYYY-MM-DD HH24:MI') AS occurred_at,
                   summary,
                   VECTOR_DISTANCE(embedding, :v, COSINE) AS distance
            FROM incidents
            ORDER BY VECTOR_DISTANCE(embedding, :v, COSINE)
            FETCH FIRST :k ROWS ONLY
            """,
            v=qv, k=top_k,
        )
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


@tool
def find_similar_incidents(query: str, top_k: int = 5) -> list[dict]:
    """Find past incidents most semantically similar to a free-text problem description.

    Use this when the user describes a symptom and you want context from history
    without filtering on any specific service or region.

    Args:
        query: Free-text description of the current incident (the user's words).
        top_k: How many incidents to return (default 5, max 20).

    Returns:
        List of incidents ordered by COSINE distance ascending. Each item has
        incident_id, service_name, category, severity, region, occurred_at,
        summary, distance.
    """
    return _find_similar_incidents_impl(query, min(top_k, 20))


# ---------------------------------------------------------------------------
# 2) Semantic + WHERE filter — the killer demo
# ---------------------------------------------------------------------------

def _find_similar_incidents_filtered_impl(
    query: str,
    service_name: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    qv = _embed_query(query)
    where_parts: list[str] = []
    params: dict = {"v": qv, "k": top_k}
    if service_name:
        where_parts.append("service_name = :svc")
        params["svc"] = service_name
    if region:
        if region not in _ALLOWED_REGIONS:
            return []
        where_parts.append("region = :reg")
        params["reg"] = region
    if category:
        if category not in _ALLOWED_CATEGORIES:
            return []
        where_parts.append("category = :cat")
        params["cat"] = category
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = f"""
        SELECT incident_id, service_name, category, severity, region,
               TO_CHAR(occurred_at, 'YYYY-MM-DD HH24:MI') AS occurred_at,
               summary,
               VECTOR_DISTANCE(embedding, :v, COSINE) AS distance
        FROM incidents
        {where}
        ORDER BY VECTOR_DISTANCE(embedding, :v, COSINE)
        FETCH FIRST :k ROWS ONLY
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


@tool
def find_similar_incidents_filtered(
    query: str,
    service_name: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Semantic search + structured filter — the canonical hybrid retrieval pattern.

    Use this when the user mentions a specific service, region, or incident category.
    Filters are AND-combined; any filter left as None is ignored.

    Args:
        query: Free-text description of the current incident.
        service_name: Exact service name (e.g. 'payment-service'). Optional.
        region: One of 'us-east', 'us-west', 'eu-west', 'ap-south'. Optional.
        category: One of 'latency', 'error_rate', 'saturation', 'availability',
            'data_quality', 'auth', 'deploy_rollback'. Optional.
        top_k: How many incidents to return (default 5, max 20).

    Returns:
        Filtered + semantically-ranked incidents. Empty list if no matches.
    """
    return _find_similar_incidents_filtered_impl(
        query, service_name, region, category, min(top_k, 20),
    )


# ---------------------------------------------------------------------------
# 3) Multi-corpus join — incident -> runbooks
# ---------------------------------------------------------------------------

def _get_runbooks_for_incident_impl(incident_id: int) -> list[dict]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.runbook_id, r.title, r.category, r.body
            FROM incident_runbooks ir
            JOIN runbooks r ON r.runbook_id = ir.runbook_id
            WHERE ir.incident_id = :iid
            ORDER BY r.runbook_id
            """,
            iid=incident_id,
        )
        cols = [c[0].lower() for c in cur.description]
        out: list[dict] = []
        for row in cur.fetchall():
            d = dict(zip(cols, row, strict=True))
            # CLOB → str so the LLM can read it.
            body = d.get("body")
            if body is not None and hasattr(body, "read"):
                d["body"] = body.read()
            out.append(d)
        return out


@tool
def get_runbooks_for_incident(incident_id: int) -> list[dict]:
    """Look up the operational runbooks linked to a specific past incident.

    Use this after find_similar_incidents(_filtered) to fetch the playbooks
    that resolved a similar past incident — this is how the agent surfaces
    actionable steps, not just historical context.

    Args:
        incident_id: The numeric incident_id from a previous tool result.

    Returns:
        List of runbooks with runbook_id, title, category, body.
    """
    return _get_runbooks_for_incident_impl(incident_id)


# ---------------------------------------------------------------------------
# 4) Pure relational — service owner lookup
# ---------------------------------------------------------------------------

def _get_service_owner_impl(service_name: str) -> dict | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT service_id, service_name, owner_team, on_call_handle, tier
            FROM services
            WHERE service_name = :svc
            """,
            svc=service_name,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0].lower() for c in cur.description]
        return dict(zip(cols, row, strict=True))


@tool
def get_service_owner(service_name: str) -> dict | None:
    """Look up the team and on-call handle that owns a service.

    Use this whenever the user asks 'who do I page' or 'who owns X'. Pure
    relational — no vector search.

    Args:
        service_name: Exact service name (e.g. 'payment-service').

    Returns:
        Dict with service_id, service_name, owner_team, on_call_handle, tier.
        None if the service is not in the catalog.
    """
    return _get_service_owner_impl(service_name)


# Convenience export for the agent — keeps copilot.py terse.
ALL_TOOLS = [
    find_similar_incidents,
    find_similar_incidents_filtered,
    get_runbooks_for_incident,
    get_service_owner,
]
