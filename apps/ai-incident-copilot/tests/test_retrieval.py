# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""5 golden retrieval tests — Phase 5 of demo-todo.md.

These exercise the four tools' `_impl` functions directly (no LLM). They depend
on the seeded dataset from `python -m copilot.db.seed`. Marked integration so
the default `pytest` run skips them; run explicitly:

    PYTHONPATH=src pytest -m integration tests/test_retrieval.py
"""

from __future__ import annotations

import pytest

from copilot.agent.tools import (
    _find_similar_incidents_filtered_impl,
    _find_similar_incidents_impl,
    _get_runbooks_for_incident_impl,
    _get_service_owner_impl,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_oracle]

CANONICAL_QUERY = "payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east"


def test_payment_latency_retrieves_similar_payment_incidents():
    """Pure semantic search on the canonical query should put payment-service
    latency anchors at the top — they semantically match on both topic and
    service name in the body."""
    hits = _find_similar_incidents_impl(CANONICAL_QUERY, top_k=5)
    assert len(hits) == 5
    # All five top hits should be category=latency on the seeded anchor data.
    assert all(h["category"] == "latency" for h in hits)
    # At least one of them should be payment-service (the anchor block guarantees ≥6).
    assert any(h["service_name"] == "payment-service" for h in hits)
    # Distances should be monotonically non-decreasing (ranking sanity).
    distances = [h["distance"] for h in hits]
    assert distances == sorted(distances)


def test_filter_by_service_excludes_other_services():
    """Adding service_name='payment-service' must remove every non-payment row."""
    hits = _find_similar_incidents_filtered_impl(
        CANONICAL_QUERY, service_name="payment-service", top_k=10,
    )
    assert hits, "anchor block guarantees payment-service has incidents"
    assert all(h["service_name"] == "payment-service" for h in hits)


def test_filter_by_region_narrows_to_one_region():
    """Region filter must be enforced even when the query mentions a different region."""
    # Query mentions us-east, filter overrides to ap-south.
    hits = _find_similar_incidents_filtered_impl(
        CANONICAL_QUERY, region="ap-south", top_k=5,
    )
    assert hits, "seed data covers all 4 regions"
    assert all(h["region"] == "ap-south" for h in hits)


def test_runbook_lookup_returns_category_match():
    """A latency incident must link only to latency-category runbooks."""
    latency_hits = _find_similar_incidents_filtered_impl(
        CANONICAL_QUERY, service_name="payment-service", category="latency", top_k=1,
    )
    assert latency_hits, "payment-service has 6 latency anchors"
    runbooks = _get_runbooks_for_incident_impl(latency_hits[0]["incident_id"])
    assert runbooks, "every seeded incident has at least one runbook"
    assert all(rb["category"] == "latency" for rb in runbooks)


def test_service_owner_lookup_is_pure_relational():
    """get_service_owner returns the deterministic seed values for known services,
    and None (not an exception) for unknown services."""
    owner = _get_service_owner_impl("payment-service")
    assert owner is not None
    assert owner["owner_team"] == "payments-core"
    assert owner["on_call_handle"] == "@payments-oncall"
    assert owner["tier"] == 0
    assert _get_service_owner_impl("does-not-exist") is None
