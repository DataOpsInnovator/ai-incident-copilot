-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Licensed under the Universal Permissive License v 1.0
-- as shown at https://oss.oracle.com/licenses/upl/.
--
-- AI Incident Copilot — schema
-- All embedding columns are 384-dim FLOAT32 (sentence-transformers/all-MiniLM-L6-v2).

-- Idempotent DROPs — ignore "table does not exist" so first-run is clean.
BEGIN
    FOR t IN (SELECT 'INCIDENT_RUNBOOKS' name FROM dual UNION ALL
              SELECT 'INCIDENTS' FROM dual UNION ALL
              SELECT 'RUNBOOKS' FROM dual UNION ALL
              SELECT 'SERVICES' FROM dual)
    LOOP
        BEGIN
            EXECUTE IMMEDIATE 'DROP TABLE ' || t.name || ' PURGE';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -942 THEN RAISE; END IF;  -- ORA-00942: table does not exist
        END;
    END LOOP;
END;
/

-- Service catalog: pure relational, joined to incidents by service name.
CREATE TABLE services (
    service_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_name   VARCHAR2(120) NOT NULL UNIQUE,
    owner_team     VARCHAR2(120) NOT NULL,
    on_call_handle VARCHAR2(120) NOT NULL,
    tier           NUMBER(1)     NOT NULL CHECK (tier BETWEEN 0 AND 3)
);

-- Past incidents — body + structured fields + embedding.
CREATE TABLE incidents (
    incident_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_name  VARCHAR2(120) NOT NULL,
    category      VARCHAR2(60)  NOT NULL,
    severity      NUMBER(1)     NOT NULL CHECK (severity BETWEEN 0 AND 3),
    region        VARCHAR2(40),
    occurred_at   TIMESTAMP     NOT NULL,
    summary       VARCHAR2(400) NOT NULL,
    body          CLOB          NOT NULL,
    embedding     VECTOR(384, FLOAT32)
);

-- Operational runbooks — title + body + embedding + category mapping.
CREATE TABLE runbooks (
    runbook_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title         VARCHAR2(200) NOT NULL,
    category      VARCHAR2(60)  NOT NULL,
    body          CLOB          NOT NULL,
    embedding     VECTOR(384, FLOAT32)
);

-- Many-to-many link from incidents to runbooks (which runbook resolved which incident).
CREATE TABLE incident_runbooks (
    incident_id NUMBER NOT NULL,
    runbook_id  NUMBER NOT NULL,
    PRIMARY KEY (incident_id, runbook_id),
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
    FOREIGN KEY (runbook_id)  REFERENCES runbooks(runbook_id)
);

-- HNSW vector indexes — COSINE because MiniLM is L2-normalised by default.
CREATE VECTOR INDEX incidents_embedding_hnsw
    ON incidents (embedding)
    ORGANIZATION INMEMORY NEIGHBOR GRAPH
    DISTANCE COSINE
    WITH TARGET ACCURACY 95;

CREATE VECTOR INDEX runbooks_embedding_hnsw
    ON runbooks (embedding)
    ORGANIZATION INMEMORY NEIGHBOR GRAPH
    DISTANCE COSINE
    WITH TARGET ACCURACY 95;

-- B-tree indexes for the WHERE clauses we expect to filter on alongside vector search.
CREATE INDEX incidents_service_idx  ON incidents (service_name);
CREATE INDEX incidents_category_idx ON incidents (category);
CREATE INDEX runbooks_category_idx  ON runbooks  (category);
