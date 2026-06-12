# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""Streamlit UI — the surface that gets recorded in the demo.

Run alongside the API:
    Terminal 1:  PYTHONPATH=src .venv/bin/uvicorn copilot.api.main:app --port 8000
    Terminal 2:  PYTHONPATH=src .venv/bin/streamlit run src/copilot/ui/app.py --server.port 8501

Env:
    COPILOT_API_URL  default http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os

import requests
import streamlit as st

API_URL = os.environ.get("COPILOT_API_URL", "http://127.0.0.1:8000")
DIAGNOSE_TIMEOUT_S = int(os.environ.get("COPILOT_DIAGNOSE_TIMEOUT_S", "180"))

CANONICAL_QUERY = (
    "payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east"
)

st.set_page_config(
    page_title="AI Incident Copilot",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("AI Incident Copilot")
st.caption("Oracle AI Database 26ai · LangChain · Llama 3.1 (Ollama)")

# API status — inline so it's always visible without expanding a sidebar.
try:
    _h = requests.get(f"{API_URL}/healthz", timeout=2).json()
    st.caption(f":green[●] API `{API_URL}` — healthz: {_h.get('status', 'unknown')}")
except Exception as e:  # noqa: BLE001
    st.caption(f":red[●] API `{API_URL}` — unreachable: {e}")

# Sample-query buttons inline as a 3-column row. Verbatim match with
# demo-queries.md "On-camera lineup".
st.markdown("**Sample queries** — click to load, then press Diagnose")
b1, b2, b3 = st.columns(3)
if b1.button("1. Canonical (payment / us-east)", use_container_width=True):
    st.session_state["query"] = CANONICAL_QUERY
if b2.button("2. Auth — JWKS rotation (eu-west)", use_container_width=True):
    st.session_state["query"] = (
        "auth-service OIDC login failures spiked after a JWKS rotation "
        "in eu-west around 10:00 UTC"
    )
if b3.button("3. Ownership — checkout-service", use_container_width=True):
    st.session_state["query"] = "Who owns checkout-service and who do I page?"

query = st.text_area(
    "Paste a freshly paged incident description",
    value=st.session_state.get("query", ""),
    placeholder=CANONICAL_QUERY,
    height=120,
    key="query_input",
)

go = st.button("Diagnose", type="primary", disabled=not query.strip())

if go:
    with st.spinner("Calling agent — embedding query, vector search, runbook lookup, LLM synthesis…"):
        try:
            resp = requests.post(
                f"{API_URL}/diagnose",
                json={"query": query.strip()},
                timeout=DIAGNOSE_TIMEOUT_S,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:  # noqa: BLE001
            st.error(f"/diagnose failed: {e}")
            st.stop()

    # --- Final answer (the main demo asset) ---
    st.subheader("Answer")
    st.markdown(result.get("answer") or "_(empty)_")

    # --- Tool call trace ---
    with st.expander(f"Tool calls ({len(result.get('tool_calls', []))})", expanded=True):
        for i, tc in enumerate(result.get("tool_calls", []), start=1):
            st.markdown(f"**{i}. `{tc['name']}`**")
            st.json(tc.get("args", {}))

    # --- Retrieved incidents (parsed from any *_incidents* tool result) ---
    incidents_payload = next(
        (
            tr["result"]
            for tr in result.get("tool_results", [])
            if "incidents" in tr["name"]
        ),
        None,
    )
    if incidents_payload:
        try:
            rows = json.loads(incidents_payload)
        except (TypeError, ValueError):
            rows = None
        if rows:
            st.subheader("Retrieved incidents")
            st.dataframe(
                rows,
                column_order=[
                    "incident_id", "service_name", "category", "severity",
                    "region", "occurred_at", "distance", "summary",
                ],
                use_container_width=True,
                hide_index=True,
            )

    # --- Runbooks (parsed from get_runbooks_for_incident result) ---
    runbooks_payload = next(
        (tr["result"] for tr in result.get("tool_results", []) if tr["name"] == "get_runbooks_for_incident"),
        None,
    )
    if runbooks_payload:
        try:
            rbs = json.loads(runbooks_payload)
        except (TypeError, ValueError):
            rbs = None
        if rbs:
            st.subheader("Runbooks")
            for rb in rbs:
                with st.expander(f"#{rb['runbook_id']} · {rb['title']}  ·  category={rb['category']}"):
                    st.markdown(rb.get("body", ""))

    # --- Service owner (parsed from get_service_owner result) ---
    owner_payload = next(
        (tr["result"] for tr in result.get("tool_results", []) if tr["name"] == "get_service_owner"),
        None,
    )
    if owner_payload:
        try:
            owner = json.loads(owner_payload)
        except (TypeError, ValueError):
            owner = None
        if owner:
            st.subheader("Service owner")
            cols = st.columns(4)
            cols[0].metric("Service", owner.get("service_name", "—"))
            cols[1].metric("Team", owner.get("owner_team", "—"))
            cols[2].metric("On-call", owner.get("on_call_handle", "—"))
            cols[3].metric("Tier", owner.get("tier", "—"))
