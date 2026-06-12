# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""Seed the copilot demo schema with synthetic incidents, runbooks, and services.

Idempotent: deletes existing rows in FK order, re-inserts, re-embeds.
Runs on a freshly applied schema in well under 2 minutes (Phase 4 exit criteria).

Usage:
    python -m copilot.db.seed
"""

from __future__ import annotations

import array
import random
from datetime import datetime, timedelta, timezone

from copilot.db.connection import connection
from copilot.rag.embedder import embed_batch

# ---------------------------------------------------------------------------
# Static taxonomy — categories the agent is expected to discriminate between.
# Keep this list small and disjoint; each category has at least 2 runbooks
# so the retrieval demo isn't trivially 1-to-1.
# ---------------------------------------------------------------------------

CATEGORIES = [
    "latency",
    "error_rate",
    "saturation",
    "availability",
    "data_quality",
    "auth",
    "deploy_rollback",
]

REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]

# 20-service catalog. team / handle / tier are deterministic so retrieval
# tests can assert exact join results.
SERVICES: list[tuple[str, str, str, int]] = [
    ("payment-service", "payments-core", "@payments-oncall", 0),
    ("checkout-service", "checkout", "@checkout-oncall", 0),
    ("auth-service", "identity", "@identity-oncall", 0),
    ("user-profile", "identity", "@identity-oncall", 1),
    ("cart-service", "checkout", "@checkout-oncall", 1),
    ("inventory-service", "fulfillment", "@fulfillment-oncall", 1),
    ("order-service", "checkout", "@checkout-oncall", 0),
    ("shipping-service", "fulfillment", "@fulfillment-oncall", 1),
    ("search-service", "discovery", "@discovery-oncall", 1),
    ("recommendations", "discovery", "@discovery-oncall", 2),
    ("notification-service", "platform", "@platform-oncall", 2),
    ("email-service", "platform", "@platform-oncall", 2),
    ("billing-service", "payments-core", "@payments-oncall", 0),
    ("fraud-service", "payments-core", "@payments-oncall", 1),
    ("analytics-ingest", "data-platform", "@data-oncall", 2),
    ("etl-runner", "data-platform", "@data-oncall", 2),
    ("image-cdn", "platform", "@platform-oncall", 1),
    ("api-gateway", "platform", "@platform-oncall", 0),
    ("session-store", "identity", "@identity-oncall", 1),
    ("config-service", "platform", "@platform-oncall", 2),
]

# ---------------------------------------------------------------------------
# Incident body templates — one per category. Each is rendered with concrete
# numbers/regions/services so the resulting bodies vary enough for MiniLM
# to produce well-separated embeddings.
# ---------------------------------------------------------------------------

INCIDENT_TEMPLATES: dict[str, str] = {
    "latency": (
        "{service} p99 latency spiked from {p99_baseline}ms to {p99_peak}ms "
        "starting at {time} UTC, only in {region}. p50 was unaffected. "
        "Downstream callers ({downstream}) saw timeouts cascade. CPU on the "
        "service stayed flat at {cpu}%, but thread-pool saturation alarms "
        "fired on {pool} after the {workload} workload kicked in. "
        "GC pause times in the JVM logs jumped to {gc}ms. "
        "Connection pool exhaustion to the downstream {downstream} cluster "
        "was the proximate cause; oversaturated upstream backpressure "
        "compounded it. Mitigation: scaled the pool from {pool_old} to "
        "{pool_new} connections and fast-failed on >{slo}ms. Incident closed "
        "after rolling restart of {service} pods in {region}."
    ),
    "error_rate": (
        "{service} 5xx error rate climbed from <0.1% to {err}% over "
        "{minutes} minutes, isolated to {region}. The spike correlated with "
        "deploy {deploy_id} pushed at {time} UTC, which changed the "
        "{downstream} client timeout from {old}ms to {new}ms. Stack traces "
        "showed RetryExhaustedException from the circuit breaker. No data "
        "loss — all failed requests were idempotent and the client retried "
        "successfully. Mitigation: rolled deploy {deploy_id} back, error "
        "rate returned to baseline within {recovery} minutes. Postmortem "
        "action: tighten preprod load test to cover the {downstream} "
        "circuit-breaker config."
    ),
    "saturation": (
        "{service} memory utilization climbed steadily to {mem}% in "
        "{region} starting around {time} UTC. OOMKilled events on {n_pods} "
        "pods. The leak was in the {component} cache layer — entries with "
        "{eviction_bug} were never evicted because the LRU key included a "
        "timestamp. Disk on {pool} reached {disk}%. Mitigation: rolling "
        "restart cleared the heap; permanent fix shipped in deploy "
        "{deploy_id} with the cache-key normalization patch. Observed "
        "recovery time: {recovery} minutes."
    ),
    "availability": (
        "{service} availability dropped to {avail}% in {region} between "
        "{time} UTC and {time2} UTC. Root cause: ALB target group health "
        "checks were misconfigured to hit {bad_path} which now returns "
        "{bad_code} after the {deploy_id} change. Healthy pods were taken "
        "out of rotation. Mitigation: rolled back the health-check path to "
        "/health/live; all targets returned to healthy within {recovery} "
        "minutes. No customer-visible impact in other regions thanks to "
        "geo-failover from {failover_region}."
    ),
    "data_quality": (
        "{service} produced rows with NULL {column} values in the "
        "{downstream} pipeline starting {time} UTC. Affected count: "
        "approximately {n_rows} rows in {region}. Cause: deploy "
        "{deploy_id} added a new optional field upstream and the "
        "transform did not default it. Downstream report jobs failed "
        "with NotNullConstraintViolation. Mitigation: deployed a "
        "fix-forward to coalesce the column, then backfilled {n_rows} "
        "rows from the bronze layer."
    ),
    "auth": (
        "{service} login failure rate jumped to {err}% in {region} at "
        "{time} UTC. Affected clients were OIDC-flow integrators using "
        "the {downstream} provider. Cause: the JWKS cache TTL of "
        "{old}s was too short relative to the rotation cadence; signing "
        "keys rotated mid-request. Mitigation: bumped JWKS cache TTL to "
        "{new}s and added background refresh. Recovery: {recovery} "
        "minutes after the config push. No password leakage; no "
        "session hijacking observed."
    ),
    "deploy_rollback": (
        "Deploy {deploy_id} of {service} to {region} caused immediate "
        "p99 regression and {err}% 5xx for the {downstream} caller. "
        "The change introduced a new SQL query that triggered a full "
        "table scan on a {n_rows}-row table because the index hint was "
        "dropped during refactor. Mitigation: automated rollback "
        "triggered after the {recovery}-minute SLO breach. Postmortem: "
        "add an EXPLAIN PLAN check to CI for any query change in "
        "{component}."
    ),
}

# ---------------------------------------------------------------------------
# Runbook content — 15 total, ≥2 per category. Title + body. Bodies are
# short, action-oriented, and reference the same vocabulary the incident
# templates use, so semantic search has signal to latch onto.
# ---------------------------------------------------------------------------

RUNBOOKS: list[tuple[str, str, str]] = [
    ("Diagnose p99 latency spike (single-region)", "latency",
     "Step 1: Confirm the spike is regional via the per-region latency dashboard. "
     "Step 2: Check thread-pool saturation and downstream connection-pool metrics — "
     "exhausted pools manifest as p99 spikes with flat CPU. "
     "Step 3: Inspect GC pause times. Pauses >500ms indicate heap pressure; correlate with deploys. "
     "Step 4: If a downstream cluster is implicated, scale its connection pool and add fast-fail. "
     "Step 5: Rolling restart of affected pods clears stuck connections."),
    ("Tune connection pools for downstream services", "latency",
     "When a downstream becomes the bottleneck, raise the client connection pool size in steps "
     "(double, observe for 5 min, repeat). Also set a sane fast-fail threshold above your p99 SLO. "
     "Document the new pool size in the service's deploy.yaml and the runbook so it survives the next deploy."),
    ("Roll back a bad deploy", "deploy_rollback",
     "Step 1: Identify the deploy via the deploy_id correlated with the alert timestamp. "
     "Step 2: Trigger automated rollback through the deploy tool — single command. "
     "Step 3: Confirm error rate returns to baseline within 5 min; if not, escalate to on-call SRE. "
     "Step 4: Open a postmortem; tag with `regression`."),
    ("Fix preprod escape — add EXPLAIN PLAN check", "deploy_rollback",
     "If a query regression escaped preprod, add an EXPLAIN PLAN diff to the CI pipeline for the affected service. "
     "Block any PR whose plan changes from index-scan to full-scan on tables >100k rows."),
    ("Spike in 5xx error rate after deploy", "error_rate",
     "Correlate the spike with the most recent deploy in the affected region. Inspect the deploy diff for "
     "timeout, retry, and circuit-breaker config changes. If a circuit-breaker change is implicated, "
     "rollback first, fix-forward second. Update preprod load tests to exercise the breaker config."),
    ("Diagnose RetryExhaustedException", "error_rate",
     "RetryExhaustedException usually means a downstream is failing while the client retries within its budget. "
     "Check downstream health first; do not increase retry counts as a workaround. If the client is idempotent, "
     "the impact is latency, not data loss."),
    ("Triage memory saturation / OOMKilled pods", "saturation",
     "Look for a leak signature: linear memory growth that resets on restart. Common causes: cache keys that "
     "include timestamps and never expire; unbounded queues; thread-locals retained across requests. "
     "Mitigate with rolling restart, fix-forward with bounded eviction."),
    ("Diagnose disk saturation", "saturation",
     "Order of operations: 1) identify which volume is filling — log dir, data dir, tmp; 2) rotate or truncate; "
     "3) raise alarm threshold below the breaking point. If logs are the cause, ship to centralized logging "
     "and shorten local retention."),
    ("Investigate availability drop", "availability",
     "Check ALB target health first. Misconfigured health checks (wrong path, wrong expected code) are the "
     "single most common cause of availability incidents post-deploy. Confirm the health-check path returns "
     "the expected status code under realistic conditions."),
    ("Geo-failover playbook", "availability",
     "If a region cannot recover within the failover SLO, initiate geo-failover. Update DNS weights to drain "
     "the failed region; monitor downstream regions for surge capacity. Write a postmortem before failing back."),
    ("Backfill NULL column from bronze layer", "data_quality",
     "When a downstream pipeline rejects rows due to NULLs in a newly required column, fix-forward by "
     "shipping a coalesce in the transform. Backfill the affected window from the bronze layer using the "
     "documented backfill script. Verify counts before swapping the silver tables."),
    ("Validate schema changes through the pipeline", "data_quality",
     "Every optional → required column change must include a transform-side default and a backfill plan. "
     "CI gate: Avro schema diff + downstream contract test."),
    ("OIDC: fix JWKS cache TTL mismatch", "auth",
     "If login failure rate spikes after a key rotation event, JWKS cache TTL is likely shorter than the "
     "rotation cadence. Bump TTL to at least 2× the rotation interval and add background refresh. "
     "Verify with synthetic OIDC login from each region."),
    ("Auth incident triage", "auth",
     "Check: 1) JWKS endpoint reachability from the auth service; 2) clock skew between issuer and verifier; "
     "3) recent IdP changes. Do not roll back auth deploys without IdP team sign-off."),
    ("Identity-tier escalation policy", "auth",
     "All auth-service incidents at severity 0 or 1 page identity-oncall AND the on-call SRE. "
     "Do not handle alone; coordinate via the #identity-incidents channel."),
]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _stable_random() -> random.Random:
    # Fixed seed → reproducible synthetic dataset across runs.
    return random.Random(1729)


def _gen_incidents(rng: random.Random, n: int = 50) -> list[dict]:
    services = [s[0] for s in SERVICES]
    rows: list[dict] = []
    base_time = datetime(2026, 4, 1, tzinfo=timezone.utc)

    # Anchor block — guarantees coverage for the canonical demo query
    # ("payment-service p99 latency …"). Without these, random sampling
    # leaves payment-service under-represented and the filtered tool returns
    # zero rows. Layout: 7 anchors covering every category + 5 extra
    # payment-service latency variants. Anchors use the ANCHOR_SERVICE.
    ANCHOR_SERVICE = "payment-service"
    anchor_plan: list[str] = list(CATEGORIES) + ["latency"] * 5  # 12 total
    assert n >= len(anchor_plan), "n must accommodate the anchor block"

    for i in range(n):
        if i < len(anchor_plan):
            category = anchor_plan[i]
            service = ANCHOR_SERVICE
        else:
            category = CATEGORIES[i % len(CATEGORIES)]
            service = rng.choice(services)

        # Region selection: pin one anchor latency incident to us-east so
        # the demo's "find latency for payment-service in us-east" filter
        # always has a hit.
        if i == 7:  # first extra latency anchor
            forced_region: str | None = "us-east"
        else:
            forced_region = None
        downstream = rng.choice([s for s in services if s != service])
        region = forced_region if forced_region else rng.choice(REGIONS)
        occurred = base_time + timedelta(hours=rng.randint(0, 24 * 30), minutes=rng.randint(0, 59))
        time_str = occurred.strftime("%H:%M")
        time2_str = (occurred + timedelta(minutes=rng.randint(20, 90))).strftime("%H:%M")
        params = {
            "service": service,
            "downstream": downstream,
            "region": region,
            "time": time_str,
            "time2": time2_str,
            "p99_baseline": rng.choice([120, 180, 220, 250]),
            "p99_peak": rng.choice([1800, 3500, 6000, 8000, 12000]),
            "cpu": rng.randint(35, 60),
            "pool": f"{service}-pool",
            "workload": rng.choice(["nightly batch", "promo flash sale", "monthly close", "weekend backfill"]),
            "gc": rng.choice([400, 800, 1200, 1800]),
            "pool_old": rng.choice([20, 40, 50]),
            "pool_new": rng.choice([100, 150, 200]),
            "slo": rng.choice([500, 800, 1000]),
            "err": rng.choice([2.5, 4.1, 6.8, 11.2, 18.0]),
            "minutes": rng.randint(8, 45),
            "deploy_id": f"deploy-{rng.randint(20000, 99999)}",
            "old": rng.choice([200, 500, 1000]),
            "new": rng.choice([50, 100, 250]),
            "recovery": rng.randint(3, 25),
            "mem": rng.randint(85, 99),
            "n_pods": rng.randint(2, 12),
            "component": rng.choice(["session", "tokenizer", "result", "lookup"]),
            "eviction_bug": rng.choice(["per-request UUIDs", "monotonic timestamps", "request-scoped trace IDs"]),
            "disk": rng.randint(85, 98),
            "avail": round(rng.uniform(91.0, 99.4), 2),
            "bad_path": rng.choice(["/health", "/healthz", "/status"]),
            "bad_code": rng.choice([404, 503, 502]),
            "failover_region": rng.choice([r for r in REGIONS if r != region]),
            "column": rng.choice(["customer_segment", "ab_variant", "campaign_id", "tax_jurisdiction"]),
            "n_rows": rng.choice([12_000, 80_000, 250_000, 1_500_000]),
        }
        body = INCIDENT_TEMPLATES[category].format(**params)
        summary = f"{service} {category.replace('_', ' ')} in {region} at {time_str} UTC"
        rows.append({
            "service_name": service,
            "category": category,
            "severity": rng.choice([0, 1, 1, 2, 2, 3]),
            "region": region,
            "occurred_at": occurred.replace(tzinfo=None),  # oracledb expects naive datetime for TIMESTAMP
            "summary": summary[:400],
            "body": body,
        })
    return rows


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _to_vec(emb: list[float]) -> array.array:
    # oracledb maps array.array("f", ...) directly to VECTOR(FLOAT32).
    return array.array("f", emb)


def _wipe(cur) -> None:
    # FK-safe order: child first.
    for table in ("incident_runbooks", "incidents", "runbooks", "services"):
        cur.execute(f"DELETE FROM {table}")


def _insert_services(cur) -> None:
    cur.executemany(
        "INSERT INTO services (service_name, owner_team, on_call_handle, tier) "
        "VALUES (:1, :2, :3, :4)",
        SERVICES,
    )


def _insert_incidents(cur, incidents: list[dict], embeddings: list[list[float]]) -> list[int]:
    sql = (
        "INSERT INTO incidents "
        "(service_name, category, severity, region, occurred_at, summary, body, embedding) "
        "VALUES (:service_name, :category, :severity, :region, :occurred_at, :summary, :body, :embedding) "
        "RETURNING incident_id INTO :new_id"
    )
    incident_ids: list[int] = []
    for row, emb in zip(incidents, embeddings, strict=True):
        new_id = cur.var(int)
        params = {**row, "embedding": _to_vec(emb), "new_id": new_id}
        cur.execute(sql, params)
        incident_ids.append(new_id.getvalue()[0])
    return incident_ids


def _insert_runbooks(cur, embeddings: list[list[float]]) -> list[tuple[int, str]]:
    sql = (
        "INSERT INTO runbooks (title, category, body, embedding) "
        "VALUES (:title, :category, :body, :embedding) "
        "RETURNING runbook_id INTO :new_id"
    )
    out: list[tuple[int, str]] = []
    for (title, category, body), emb in zip(RUNBOOKS, embeddings, strict=True):
        new_id = cur.var(int)
        cur.execute(sql, {
            "title": title, "category": category, "body": body,
            "embedding": _to_vec(emb), "new_id": new_id,
        })
        out.append((new_id.getvalue()[0], category))
    return out


def _link_incidents_to_runbooks(
    cur,
    incident_ids: list[int],
    incidents: list[dict],
    runbooks: list[tuple[int, str]],
) -> None:
    by_cat: dict[str, list[int]] = {}
    for rid, cat in runbooks:
        by_cat.setdefault(cat, []).append(rid)
    pairs: list[tuple[int, int]] = []
    for iid, inc in zip(incident_ids, incidents, strict=True):
        for rid in by_cat.get(inc["category"], []):
            pairs.append((iid, rid))
    if pairs:
        cur.executemany(
            "INSERT INTO incident_runbooks (incident_id, runbook_id) VALUES (:1, :2)",
            pairs,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    rng = _stable_random()
    incidents = _gen_incidents(rng, n=50)

    print(f"[seed] embedding {len(incidents)} incidents + {len(RUNBOOKS)} runbooks…")
    incident_embeddings = embed_batch([row["body"] for row in incidents])
    runbook_embeddings = embed_batch([rb[2] for rb in RUNBOOKS])
    print("[seed] embeddings ready; writing to Oracle…")

    with connection() as conn:
        with conn.cursor() as cur:
            _wipe(cur)
            _insert_services(cur)
            incident_ids = _insert_incidents(cur, incidents, incident_embeddings)
            runbook_meta = _insert_runbooks(cur, runbook_embeddings)
            _link_incidents_to_runbooks(cur, incident_ids, incidents, runbook_meta)
        conn.commit()

    print(
        f"[seed] done — {len(SERVICES)} services, "
        f"{len(incident_ids)} incidents, {len(runbook_meta)} runbooks, "
        f"links built by category."
    )


if __name__ == "__main__":
    main()
