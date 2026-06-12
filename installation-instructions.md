# Installation Instructions — AI Incident Copilot (Oracle 26ai RAG Demo)

> Step-by-step setup so a fresh machine can replicate this demo environment.
> Living document — updated as the build progresses.

---

## 0. Prerequisites

Before you start, make sure these are installed on the host machine:

| Tool | Minimum version | Verify with |
|---|---|---|
| Docker (Desktop or Engine) | 20.10+ | `docker --version` |
| Python | 3.10+ | `python3 --version` |
| Git | any recent | `git --version` |

macOS users: Docker Desktop must be running before any `docker` command will work.

---

## 1. Clone / open the project directory

```bash
cd /path/to/oracle-26ai-rag-course
```

All commands below assume you are at the repo root.

---

## 2. Create and activate the Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate            # Windows PowerShell

python -m pip install --upgrade pip
```

**Verify:**
```bash
which python      # should point inside .venv/bin/python
python --version  # 3.10.x
pip --version     # 26.x or newer
```

The repo's `.gitignore` excludes `.venv/`, `__pycache__/`, `*.pyc`, `.env`, and `.DS_Store`.

> Every subsequent `python` / `pip` command in this SOP assumes the venv is active. If you open a new shell, run `source .venv/bin/activate` again.

---

## 3. Pull the Oracle Database 26ai Free container image

> **Naming note:** Oracle markets the product as "Oracle Database 26ai", but the
> container image version is `23.26.x` (the `23ai` train continued; "26ai" is the
> 2026 release branding). There is **no** `latest-26ai` tag — pull `23.26.1.0`
> (or `latest`) from the `database/free` repo.

```bash
docker pull container-registry.oracle.com/database/free:23.26.1.0
```

- Image size: **~3.5 GB compressed download**, **~9 GB on disk** after extraction (22 layers; the four large ones are Oracle binaries, patches, and two seed-database layers).
- Make sure Docker Desktop has at least **15 GB** of free disk allocated before pulling.
- On a typical home connection expect 5–15 minutes.
- The Free image at `container-registry.oracle.com/database/free` is publicly pullable — no Oracle SSO login required.
- We pin `23.26.1.0` (current latest as of 2026-05) so the demo is reproducible. `latest` works too but may drift later.

**Discovering tags yourself** (optional, if `23.26.1.0` is no longer available):
```bash
TOKEN=$(curl -s "https://container-registry.oracle.com/auth?service=Oracle%20Registry&scope=repository:database/free:pull" | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" "https://container-registry.oracle.com/v2/database/free/tags/list" | python3 -m json.tool
```

**Verify:**
```bash
docker images | grep oracle
```

You should see `container-registry.oracle.com/database/free` with the `23.26.1.0` tag.

---

## 4. Boot the Oracle 26ai container

```bash
docker run -d --name oracle26ai \
  -p 1521:1521 \
  -e ORACLE_PWD=Welcome_123 \
  -v oracle26ai-data:/opt/oracle/oradata \
  container-registry.oracle.com/database/free:23.26.1.0
```

What each flag does:

| Flag | Purpose |
|---|---|
| `-d` | Detached — runs in the background. |
| `--name oracle26ai` | Stable container name for `docker logs` / `docker exec`. |
| `-p 1521:1521` | Maps the TNS listener to the host so `oracledb` can connect from your venv. |
| `-e ORACLE_PWD=Welcome_123` | Password for `SYS` / `SYSTEM` / `PDBADMIN`. The image refuses to start without one. **Demo only — change it for anything real.** |
| `-v oracle26ai-data:/opt/oracle/oradata` | Named Docker volume so the database survives `docker rm` and you don't pay the 5–10 min init cost again. |

**Wait for the database to be ready.** First boot creates the `FREE` CDB and `FREEPDB1` PDB — takes **5–10 minutes** on first run, ~30 sec on subsequent starts. Watch the logs:

```bash
docker logs -f oracle26ai
```

You're ready when you see this banner:

```
#########################
DATABASE IS READY TO USE!
#########################
```

Press `Ctrl+C` to stop following the logs (the container keeps running).

**Or, wait non-interactively** (script-friendly — exits when ready):

```bash
until docker logs oracle26ai 2>&1 | grep -q "DATABASE IS READY TO USE"; do sleep 5; done && echo "READY"
```

**Connection details** (use these in every later step):

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `1521` |
| Pluggable DB (PDB) | `FREEPDB1` |
| User (demo) | `system` |
| Password (demo) | `Welcome_123` |
| Easy-Connect string | `localhost:1521/FREEPDB1` |

**Lifecycle commands** for later:

```bash
docker stop oracle26ai     # graceful shutdown
docker start oracle26ai    # restart (fast — DB files are on the volume)
docker rm -f oracle26ai    # delete container only (volume + data preserved)
docker volume rm oracle26ai-data   # nuke the database files (irreversible)
```

---

## 5. Smoke-test the vector engine

Confirm the 26ai vector functions actually work, **before** writing any Python. This catches a broken image or a wrong tag in 30 seconds.

```bash
docker exec -i oracle26ai sqlplus -S system/Welcome_123@FREEPDB1 <<'SQL'
SET PAGESIZE 0 LINESIZE 200
SELECT VECTOR_DISTANCE(
  TO_VECTOR('[1,2,3]', 3, FLOAT32),
  TO_VECTOR('[4,5,6]', 3, FLOAT32),
  COSINE
) AS cosine_distance FROM dual;
EXIT;
SQL
```

Expected output: a single number around **`2.537E-002`** (≈ 0.0254 — cosine distance between the two vectors). Any number prints → vector engine is live. An ORA- error → stop and debug before moving on.

Verify the banner at the same time (sanity check on the build you're running):

```bash
docker exec -i oracle26ai sqlplus -S system/Welcome_123@FREEPDB1 <<'SQL'
SET PAGESIZE 0 FEEDBACK OFF
SELECT BANNER_FULL FROM v$version WHERE ROWNUM=1;
EXIT;
SQL
```

Confirmed banner on the demo machine:

```
Oracle AI Database 26ai Free Release 23.26.1.0.0 - Develop, Learn, and Run for Free
Version 23.26.1.0.0
```

---

## 6. Install Python demo dependencies

> **Heads-up — disk + bandwidth.** This step pulls `torch` (~700 MB wheel, ~2.5 GB on disk) as a transitive dep of `sentence-transformers`. Allow ~3 GB free in the venv directory. First install on a slow connection takes 3–8 min.

The dependency list lives in `requirements.txt` at the repo root:

```text
oracledb>=2.5.0
langchain>=0.3.0
langchain-community>=0.3.0
langchain-core>=0.3.0
sentence-transformers>=3.0.0
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
streamlit>=1.40.0
python-dotenv>=1.0.0
```

Install:

```bash
.venv/bin/pip install -r requirements.txt
# or, with the venv activated:
pip install -r requirements.txt
```

**Resolved versions on the demo machine** (2026-05-04, Python 3.10.5):

| Package | Version |
|---|---|
| `oracledb` | 3.4.2 |
| `langchain` | 1.2.17 |
| `langchain-community` | 0.4.1 |
| `langchain-core` | 1.3.2 |
| `sentence-transformers` | 5.4.1 |
| `fastapi` | 0.136.1 |
| `uvicorn` | 0.46.0 |
| `streamlit` | 1.57.0 |
| `torch` (transitive) | 2.11.0 |
| `numpy` (transitive) | 2.2.6 |

Pin these in `requirements.txt` if you want strict reproducibility (`pip freeze > requirements.lock.txt`).

---

## 7. Smoke-test the venv → DB connection

The script lives at `scripts/smoke_test.py`:

```python
import oracledb

DSN = "localhost:1521/FREEPDB1"
USER = "system"
PASSWORD = "Welcome_123"

with oracledb.connect(user=USER, password=PASSWORD, dsn=DSN) as conn:
    print(f"oracledb {oracledb.__version__} | thin mode = {conn.thin}")
    with conn.cursor() as cur:
        cur.execute("SELECT BANNER_FULL FROM v$version WHERE ROWNUM = 1")
        print("server :", cur.fetchone()[0])
        cur.execute("""
            SELECT VECTOR_DISTANCE(
                TO_VECTOR('[1,2,3]', 3, FLOAT32),
                TO_VECTOR('[4,5,6]', 3, FLOAT32),
                COSINE
            ) FROM dual
        """)
        print("cosine :", cur.fetchone()[0])
print("OK")
```

Run it:

```bash
.venv/bin/python scripts/smoke_test.py
```

Expected output (verified on the demo machine):

```
oracledb 3.4.2 | thin mode = True
server : Oracle AI Database 26ai Free Release 23.26.1.0.0 - Develop, Learn, and Run for Free
Version 23.26.1.0.0
cosine : 0.025368153802923787
OK
```

Three things this confirms in one shot:

1. The venv has `oracledb` and is using **thin mode** (no Oracle Instant Client / native libs needed — pure Python over the network).
2. The container's TNS listener on `localhost:1521` is reachable from the host.
3. The `VECTOR_DISTANCE` / `TO_VECTOR` / `FLOAT32` types are present and produce the same cosine distance (`0.0254`) as the SQL*Plus run from inside the container.

If this script prints `OK`, the demo stack's data plane is fully wired.

---

## 8. Install Ollama and pull the local LLM

The demo uses **Ollama** for local LLM inference so no API key or internet round-trip is needed during recording. The brief allows a one-line swap to a hosted LLM later.

### 8.1. Install Ollama (macOS)

```bash
brew install ollama
ollama --version
```

Linux: see <https://ollama.com/download/linux>.
Windows: install Ollama Desktop from <https://ollama.com/download>.

Verified version on the demo machine: **`0.23.0`**.

### 8.2. Start the Ollama daemon

```bash
brew services start ollama        # macOS — auto-restarts on login
# or, foreground (no auto-start):
# OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 /opt/homebrew/opt/ollama/bin/ollama serve
```

The daemon listens on `http://127.0.0.1:11434`. Sanity-check with:

```bash
curl -s http://127.0.0.1:11434/api/version
# {"version":"0.23.0"}
```

Lifecycle:

```bash
brew services stop ollama
brew services restart ollama
```

### 8.3. Pull `llama3.1:8b`

```bash
ollama pull llama3.1:8b
```

- Download: **~4.7 GB**, on-disk: ~5 GB. Models live under `~/.ollama/models/`.
- 5–15 min on a typical home connection.
- 8B parameters — runs comfortably on Apple Silicon with 16 GB RAM. If you're on 8 GB, swap to `llama3.2:3b` instead (model name is the only change).

### 8.4. Smoke-test a completion

```bash
ollama run llama3.1:8b "In one sentence, what is RAG?"
```

Or via the HTTP API (matches how the demo will call it):

```bash
curl -s http://127.0.0.1:11434/api/generate -d '{
  "model": "llama3.1:8b",
  "prompt": "In one sentence, what is RAG?",
  "stream": false
}' | python3 -c "import json,sys;print(json.load(sys.stdin)['response'])"
```

**Verified on the demo machine** (Apple Silicon):

| Call | Tokens out | Latency |
|---|---|---|
| First call (cold load into memory) | 54 | ~28 s |
| Subsequent calls (warm) | 54 | **~1.7 s** |

Sample warm output for prompt *"In one sentence, what is retrieval-augmented generation in AI?"*:

> Retrieval-augmented generation (RAG) is a type of artificial intelligence model that combines the strengths of both language models and retrieval-based approaches by first retrieving relevant information from a large database or knowledge graph, and then generating text based on that retrieved information.

> **Gotcha:** the bare acronym `"RAG"` is ambiguous — Llama 3.1 will happily answer with the immunology gene (*Recombinase-Activating Gene*) instead. For the recording, prompts must spell out *"Retrieval-Augmented Generation"* the first time it appears.

`ollama list` should show:

```
NAME           ID              SIZE      MODIFIED
llama3.1:8b    46e0c10c039e    4.9 GB    just now
```

---

## 9. Pause — orient yourself on the architecture

Before we wire anything else up, let's pull up the picture and figure out where we are.

Open **[`img/base-workflow.svg`](img/base-workflow.svg)** in a browser. That's the whole system we're building. Trace the request flow left-to-right:

```
[USER] → [STREAMLIT] → [FASTAPI] → [LANGCHAIN] → [OLLAMA]      (the brain)
                                          └─→ [ORACLE 26ai 🐳]  (the library)
```

Here's what's done after sections 0–8, and what each next section adds:

| Piece on the diagram | State after §8 | Configured in… |
|---|---|---|
| **Oracle 26ai 🐳** (Vector DB) | ✅ container running, vector engine smoke-tested — but empty | §10 (schema) · §11 (seed) · §12 (smoke retrieval) |
| **Ollama** (LLM brain) | ✅ daemon up, `llama3.1:8b` pulled and smoke-tested | already done |
| **LangChain** (the conductor) | ⬜ Python package installed; agent code not yet wired | §13 |
| **FastAPI** (HTTP layer) | ⬜ Python package installed; server not running | §14 |
| **Streamlit** (UI) | ⬜ Python package installed; UI not running | §15 |

So the plan for the rest of this file is straightforward:

1. **§10–§12** — fill up the Vector DB (right side of the diagram). At the end you'll prove vector search works *without any LLM* — that's important: it isolates "did retrieval work" from "did the LLM write a good answer".
2. **§13** — wire LangChain on top of Ollama + Vector DB. The first time the *agent* runs end-to-end. Still no UI.
3. **§14** — put FastAPI in front of the agent. First HTTP call.
4. **§15** — put Streamlit in front of FastAPI. Your demo is now clickable.
5. **§16–§17** — the hardening (readiness probe, vector memory) and the recording prewarm — already baked into the scripts, documented here for the record.
6. **§18** — when the app works on your laptop, this is the checklist for shipping it as a PR to the upstream Oracle hub.

If you ever lose track of where you are, come back to this diagram. Each section below opens by telling you *which box on the diagram we're working on right now*.

---

## 10. Configure the Vector DB — apply the schema

> **On the diagram:** we're inside the bottom-right cylinder — **Oracle 26ai · Vector DB (Docker)**. The container is running but empty. This section creates the tables, the columns that hold vectors, and the HNSW indexes that make vector search fast.

There are two one-time fixes we have to apply to the stock Oracle 26ai Free image before the schema will work. We learned about both the hard way; you don't have to. The `setup_db.sh` script bakes them in.

### 10.1. Fix #1: don't connect as `system`

Oracle's `VECTOR` column type **refuses to be created in any tablespace that uses manual segment space management** — and the `SYSTEM` tablespace uses exactly that. Trying to apply `schema.sql` as the `system` user fails with:

```
ORA-43853: VECTOR type cannot be used in non-automatic
           segment space management tablespace "SYSTEM"
```

So we create a dedicated user named `copilot`, give it the `USERS` tablespace (which uses ASSM), and connect as that user from then on.

`scripts/setup_db.sh` does this idempotently — re-running is safe. Look inside if you're curious. The connection details after this step:

| Field | Value |
|---|---|
| User | `copilot` (NOT `system`) |
| Password | `Welcome_123` |
| Tablespace | `USERS` (ASSM-enabled) |

### 10.2. Fix #2: turn on `vector_memory_size` before HNSW indexes

The Oracle 26ai Free image ships with `vector_memory_size = 0`. Any `CREATE VECTOR INDEX … ORGANIZATION INMEMORY NEIGHBOR GRAPH` (an HNSW index — fast approximate-nearest-neighbor) needs this pool to have memory. Without it you get:

```
ORA-51962: The vector memory area is out of space for the current container
```

`vector_memory_size` is a **CDB-level static parameter** — it must be set on the root container and the database must be restarted before HNSW will work. Set it to 512M (the Free image's SGA is 1536M, so 512M is comfortable; bump to 1G if you scale to thousands of vectors later).

Apply once:

```bash
# 1) Set on the CDB (FREE), persist via SPFILE
docker exec -i oracle26ai sqlplus -S -L sys/Welcome_123@localhost:1521/FREE as sysdba <<'SQL'
ALTER SYSTEM SET vector_memory_size = 512M SCOPE=SPFILE;
EXIT;
SQL

# 2) Restart the container so the SPFILE change takes effect
docker restart oracle26ai

# 3) Wait for the listener to come back up (uses the §16 probe under the hood)
until docker exec oracle26ai sh -c \
        "echo 'SELECT 1 FROM DUAL;' | sqlplus -S -L system/Welcome_123@FREEPDB1" 2>&1 \
        | grep -q '^----------'; do sleep 5; done && echo "READY"

# 4) Verify
docker exec -i oracle26ai sqlplus -S -L sys/Welcome_123@localhost:1521/FREE as sysdba <<'SQL'
SELECT name, display_value FROM v$parameter WHERE name = 'vector_memory_size';
EXIT;
SQL
# Expect:  vector_memory_size    512M
```

After the restart, the two HNSW indexes in `schema.sql` create in well under a second each.

> **Why we restart the container instead of `SHUTDOWN IMMEDIATE` from inside.** The container's PID 1 is the Oracle init script — letting docker manage the lifecycle is safer than telling Oracle to shut itself down from underneath its own init.

#### Picking the right `vector_memory_size` for production

**512M is right for this demo and nothing more.** It's massive overkill for 65 vectors — but the rest of the pool is just empty headroom, not waste. For a real workload you have to size this against your actual vector count and dimensionality, because:

- HNSW indexes live **entirely inside this pool**. If they don't fit, `CREATE VECTOR INDEX` fails with ORA-51962 — even if you have terabytes of free disk.
- `vector_memory_size` is a **static CDB parameter**. Changing it requires a database restart, which in production is a coordinated maintenance window. Size it generously the first time.
- Multiple HNSW indexes **share the same pool**. Sum across all of them.

**Rule-of-thumb formula:**

```
vector_memory_size  ≈  N  ×  dim  ×  4 bytes  ×  3  ×  1.4
                       │     │       │          │     │
                       │     │       │          │     └─ 40% headroom for graph growth + future inserts
                       │     │       │          └─────── HNSW overhead factor (graph edges, layer pointers)
                       │     │       └────────────────── FLOAT32 — bytes per vector element
                       │     └────────────────────────── your embedding dimensionality
                       └──────────────────────────────── total number of vectors across ALL HNSW-indexed tables
```

**Worked examples — what to set for common workloads:**

| Workload tier | Vector count | Dimensionality | Suggested `vector_memory_size` | Notes |
|---|---|---|---|---|
| **This demo / dev / tiny POC** | <1,000 | 384 | **512M** | What this file uses. Bumps to 1G if you grow much. |
| **Small POC** | 10K – 100K | 384–768 | **1G – 2G** | Comfortable for a single team's data. |
| **Small production** | 100K – 1M | 384–768 | **4G – 8G** | A department's worth of documents. |
| **Medium production** | 1M – 10M | 768 | **16G – 32G** | Org-wide knowledge base. |
| **Large production** | 10M – 100M | 768–1536 | **64G – 256G+** | Plan with your DBA. Consider IVF (below). |

For reference, our demo dataset is **65 vectors × 384 dim × 4 bytes × 3 × 1.4 ≈ 420 KB**. 512M of headroom is the entire 26ai Free image's idea of "small". On a production CDB you'd likely have multi-GB SGA budgets to draw from.

**Hard constraints you have to check:**

1. **`vector_memory_size` must fit inside `sga_max_size`.** Verify before you set:
   ```sql
   SELECT name, display_value
   FROM   v$parameter
   WHERE  name IN ('sga_max_size', 'sga_target', 'vector_memory_size');
   ```
   On the 26ai Free image `sga_max_size` is 1536M, which is why 512M is the practical ceiling here. On a real Standard/Enterprise box, you'd typically have an SGA in the tens of GB or more — but it's still finite, so plan.

2. **Watch what's left for the rest of Oracle.** The buffer cache, shared pool, large pool, and Java pool all live inside the SGA. Don't starve them. A common pattern in production: budget 20–30% of total SGA for vector workloads, the rest for traditional caches.

3. **`alter system` requires `SCOPE=SPFILE` and a restart for this parameter.** It's not dynamic. Plan the maintenance window.

**When HNSW gets too big for the pool — switch to IVF**

If your `vector_memory_size` calculation says you need 200+ GB, consider IVF indexes (`ORGANIZATION NEIGHBOR PARTITIONS`) instead of HNSW (`ORGANIZATION INMEMORY NEIGHBOR GRAPH`):

| Aspect | HNSW (in-memory graph) | IVF (partitioned, mostly disk) |
|---|---|---|
| Where it lives | Entirely inside `vector_memory_size` | Mostly on disk; only working set in memory |
| Recall (accuracy) | Higher — typically 95–99% | Slightly lower — typically 90–95%, tunable |
| Query latency | Faster (memory-only) | Slower (some disk I/O) |
| Memory cost | High — `N × dim × 4 × ~3` | Low — fits any SGA |
| When to use | Datasets that fit comfortably in memory | Huge datasets, or budget-constrained SGA |

This project uses HNSW because the demo dataset is small and the recall advantage matters for the on-camera "wow" beat. For a 100M-vector production index, IVF is usually the right call.

**Monitoring once you're sized**

If your 26ai release exposes it, the pool's live usage is here:

```sql
SELECT * FROM v$vector_memory_pool;   -- if this view exists in your release
```

Otherwise infer from index size + insert rate. Resize when you see pool utilization climb past ~70%; you don't want to discover you're full at the moment of the next CREATE VECTOR INDEX.

### 10.3. Run `setup_db.sh` — creates the `copilot` user and applies the schema

```bash
cd apps/ai-incident-copilot
bash scripts/setup_db.sh
```

What this does, in order:

1. Confirms `oracle26ai` is running. (If not — start it: `docker start oracle26ai` and wait.)
2. Waits for the TNS listener to actually accept connections (the **connectability probe** from §16, not a log-grep — see §16 for why this matters).
3. Creates the `copilot` user with `DEFAULT TABLESPACE USERS` and the right grants, idempotently. Re-running just succeeds.
4. Applies `src/copilot/db/schema.sql` as `copilot`. The schema is idempotent too — `DROP TABLE IF EXISTS` first, then `CREATE`.

**Expected on disk after this step:**

| Object | Count | Where to verify |
|---|---|---|
| Tables | 4 (`SERVICES`, `INCIDENTS`, `RUNBOOKS`, `INCIDENT_RUNBOOKS`) | `SELECT table_name FROM user_tables;` |
| HNSW vector indexes | 2 (`INCIDENTS_EMBEDDING_HNSW`, `RUNBOOKS_EMBEDDING_HNSW`) | `SELECT index_name FROM user_indexes WHERE index_type='VECTOR';` |
| B-tree filter indexes | 3 (on `service_name`, `category`, `region`) | same view, `WHERE index_type='NORMAL'` |
| Vector dimension | 384, `FLOAT32` | matches the embedding model (§11) |

> **Tip:** there's no `USER_VECTOR_INDEXES` view in 26ai. Use `USER_INDEXES.INDEX_TYPE = 'VECTOR'` instead.

**If `schema.sql` fails with ORA-43853** → you're connected as `system`. Re-check `.env` — `ORACLE_USER` must be `copilot`, not `system`.
**If `schema.sql` fails with ORA-51962** → §10.2 hasn't been applied yet. Run it, restart, try again.

✅ Done when `setup_db.sh` exits 0 and the verification queries above return the expected row counts.

---

## 11. Seed the demo data — fill the Vector DB

> **On the diagram:** still in the bottom-right cylinder. The schema is in place; now we put data in it.

### 11.1. The mental model — we *index*, we don't *train*

This is the single most common point of confusion in RAG. Worth pausing on:

- **We are not training Llama.** Llama's weights stay exactly as Meta shipped them.
- The seeder takes each incident, runs the *text* through a small **embedding model** (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions), and stores the resulting vector next to the text in Oracle.
- "Filling the library." Not "teaching the brain."
- At query time the same embedding model embeds the user's question, Oracle finds the nearest vectors, and only THEN does Llama come in — to read the retrieved chunks and write the answer.

Two distinct moments. Don't confuse them.

### 11.2. Run the seeder

> **Activate the venv first.** Per §2, the venv lives at the **repo root** (`oracle-26ai-rag-course/.venv/`) — one shared venv for all apps under `apps/`. From any terminal:
> ```bash
> source /full/path/to/oracle-26ai-rag-course/.venv/bin/activate
> # or, if you're at the repo root:
> source .venv/bin/activate
> ```
> Once active, `which python` should point at `…/oracle-26ai-rag-course/.venv/bin/python`. All commands in §11–§15 assume the venv is active in the terminal you're using.

```bash
cd apps/ai-incident-copilot     # if you're not already there
PYTHONPATH=src python -m copilot.db.seed
```

> The `.env` file at `apps/ai-incident-copilot/.env` must exist (copy from `.env.example`). `connection.py` loads it via `load_dotenv()`.
>
> **If you see `bash: .venv/bin/python: No such file or directory`:** the venv isn't where the command is looking. Either activate it as shown above (then re-run with just `python`), or use the explicit relative path from the app dir: `PYTHONPATH=src ../../.venv/bin/python -m copilot.db.seed`.

**Wall-clock:** ~23 seconds on the demo machine (well under the 2-minute exit criterion).

Idempotent: re-running deletes existing rows in FK order and re-inserts. No `TRUNCATE` (IDENTITY sequences advance across re-seeds — harmless).

**Expected final state:**

| Table | Rows | Notes |
|---|---|---|
| `services` | 20 | catalog metadata |
| `incidents` | 50 | **anchor block:** 12 are `payment-service` — 1 per category + 6 latency, with one latency incident pinned to `us-east` so the canonical filtered demo query always has a hit |
| `runbooks` | 15 | ≥2 runbooks per category across 7 categories |
| `incident_runbooks` | 107 | joined by category — the LangChain `get_runbooks_for_incident` tool uses this |

### 11.3. Verify the row counts

```bash
docker exec -i oracle26ai sqlplus -S copilot/Welcome_123@FREEPDB1 <<'SQL'
SET PAGESIZE 0 FEEDBACK OFF
SELECT 'services         ' || COUNT(*) FROM services;
SELECT 'incidents        ' || COUNT(*) FROM incidents;
SELECT 'runbooks         ' || COUNT(*) FROM runbooks;
SELECT 'incident_runbooks ' || COUNT(*) FROM incident_runbooks;
EXIT;
SQL
```

Expect `20 / 50 / 15 / 107`.

✅ Done when those four numbers match.

---

## 12. Smoke-test retrieval — prove the Vector DB works *without the LLM*

> **On the diagram:** still in the Vector DB cylinder. **Crucially, we do NOT touch Ollama yet.** If the LLM and the DB are both involved and something goes wrong, you won't know which to debug. Test each layer alone first.

### 12.1. The canonical query

Run a pure vector search — same SQL Oracle will execute when LangChain calls the `find_similar_incidents` tool later:

```bash
PYTHONPATH=src python -c "
from copilot.rag.embedder import embed
from copilot.db.connection import get_connection
import array

q = 'payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east'
v = array.array('f', embed(q))
with get_connection() as conn, conn.cursor() as cur:
    cur.execute('''
        SELECT incident_id, service_name, category, region,
               VECTOR_DISTANCE(embedding, :v, COSINE) AS dist
        FROM incidents
        ORDER BY VECTOR_DISTANCE(embedding, :v, COSINE)
        FETCH FIRST 5 ROWS ONLY
    ''', v=v)
    for row in cur.fetchall():
        print(row)
"
```

Expected: **5 payment-service latency incidents**, distances roughly in the `0.26 – 0.30` range. The first row should be `incident_id=108` (the us-east latency anchor we pinned in §11).

### 12.2. Now try a *filtered* search (relational filter + vector ordering, in one SQL)

This is the Oracle 26ai converged-database flex — filter and similarity in one query, no app-level join:

```sql
SELECT incident_id, service_name, region,
       VECTOR_DISTANCE(embedding, :v, COSINE) AS dist
FROM   incidents
WHERE  service_name = 'payment-service'
  AND  region       = 'us-east'
ORDER BY VECTOR_DISTANCE(embedding, :v, COSINE)
FETCH FIRST 5 ROWS ONLY;
```

Guaranteed at least one hit at distance ≈ 0.27 because of the pinned anchor.

✅ Done — the Vector DB box on the diagram is fully proven. The entire right-hand side of the architecture works end-to-end.

> **Implementation note:** the seeder uses `array.array("f", embedding)` to bind to a `VECTOR(384, FLOAT32)` column. Use the same pattern for retrieval. `oracledb` thin mode handles it natively.

---

## 13. Wire up LangChain — the agent + 4 tools

> **On the diagram:** now we activate the **teal LangChain hub** in the center, and the **`langchain-ollama`** wire that connects it to the Ollama brain. After this section, the agent runs end-to-end *in Python* — still no API, still no UI.

### 13.1. What lives in `src/copilot/agent/`

Two files do all the work:

```
apps/ai-incident-copilot/src/copilot/agent/
├── tools.py        # 4 @tool functions, each with a parallel _impl for tests
└── copilot.py      # ChatOllama(llama3.1:8b) + langchain.agents.create_agent
                    # exposes: diagnose(query) -> {answer, tool_calls, tool_results}
```

The agent's contract is intentionally tiny: **one Python function** — `diagnose(query: str)`. Everything below it is LangChain's problem.

### 13.2. The 4 tools the agent can call

The easiest way to keep them straight: **two buckets**.

- **🔎 FIND tools** (similarity-powered, use vectors) — search the library by meaning.
- **📇 LOOKUP tools** (plain SQL, no AI math) — fetch a specific known fact.

| Tool | In plain English | Bucket | Backed by |
|---|---|---|---|
| `find_similar_incidents(query, top_k=5)` | *"Give me five past incidents that look like this new one."* | 🔎 find | Oracle `VECTOR_DISTANCE` |
| `find_similar_incidents_filtered(service_name, region, category, top_k=5)` | *"Same idea, but narrowed — similar incidents, but only in this service and this region."* | 🔎 find | Oracle 26ai converged engine — filter + similarity in **one SQL** |
| `get_runbooks_for_incident(incident_id)` | *"I've found a similar incident — now show me the playbook the team followed last time."* | 📇 lookup | Plain SQL join on `incident_runbooks` |
| `get_service_owner(service_name)` | *"Who do I page about this?"* | 📇 lookup | Plain SQL — catalog lookup (owner team, on-call handle, tier) |

The LLM picks which to call (and with what arguments) based on what you asked. That's the agentic part — we don't write "if the query mentions a service name, call the filtered version." Llama reads the question, looks at the tool docs, and decides.

> **Worth saying on camera once:** the second row is the Oracle 26ai flex. It mixes a structured filter (`service='payment-service'`, `region='us-east'`) with a vector similarity ranking, and Oracle does both in **one** SQL query. Most stacks need a relational DB for filters AND a separate vector DB for similarity, then stitch the results together in application code. Here we get it for free.

#### A worked example — what fires when, for the canonical query

User types *"payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east"*. Here's the full sequence of who's talking to whom:

| Step | Actor | Direction | Detail |
|---|---|---|---|
| 1 | Ollama | ← | user question |
| 2 | Ollama | → | call `find_similar_incidents_filtered(service='payment-service', region='us-east', category='latency')` |
| 3 | Oracle | ← | run filtered vector search |
| 4 | Oracle | → | 5 rows (top is `incident_id=108`) |
| — | *…Ollama is idle during steps 3–4…* | | |
| 5 | Ollama | ← | see the 5 rows |
| 6 | Ollama | → | call `get_runbooks_for_incident(108)` |
| 7 | Oracle | ← | join + lookup |
| 8 | Oracle | → | runbook rows |
| — | *…Ollama is idle during steps 7–8…* | | |
| 9 | Ollama | ← | see the runbook |
| 10 | Ollama | → | call `get_service_owner('payment-service')` |
| 11 | Oracle | ← | catalog lookup |
| 12 | Oracle | → | one row: `@payments-oncall` |
| — | *…Ollama is idle during steps 11–12…* | | |
| 13 | Ollama | ← | all 3 tool results |
| 14 | Ollama | → | writes the final cited answer |

**Two things this trace makes obvious:**

- **Ollama and Oracle never run at the same time.** The Vector DB is idle during reasoning steps; Ollama is idle during SQL steps. LangChain is the only thing always in the loop — it's the conductor.
- **Tool calls themselves don't involve the LLM.** Steps 3–4, 7–8, 11–12 are pure Python + SQL. That's why `tools.py` ships a parallel `_impl` function for each tool — tests exercise the DB path without ever loading Llama into memory.

Rough call count for this query: ~4 Ollama calls + 3 Oracle queries. The Oracle queries are sub-millisecond; the Ollama calls are where the wall-clock time goes.

### 13.3. The LangChain 1.x note — `create_agent`, not `create_react_agent`

LangChain 1.x ships a new agent constructor: **`langchain.agents.create_agent`**. The old `langgraph.prebuilt.create_react_agent` is deprecated. Our `copilot.py` uses the new one. If you copy code from an older tutorial you may see the deprecated form — swap it.

### 13.4. Security note — filter inputs are whitelisted

Tool arguments that get spliced into SQL (`region`, `category`) are whitelisted in `tools.py`:

```python
_ALLOWED_REGIONS    = {"us-east", "us-west", "eu-west", "eu-central", "ap-south"}
_ALLOWED_CATEGORIES = {"latency", "auth", "saturation", "deploy", "config",
                       "dependency", "data"}
```

Anything else is rejected before it reaches Oracle. The LLM can never smuggle free-text into a `WHERE` clause. Important when an LLM is doing the argument-picking.

The model occasionally serializes int args as strings (e.g. `top_k: "5"`); the tool wrapper coerces silently via `min(top_k, 20)`.

### 13.5. Smoke-test the agent in Python

```bash
PYTHONPATH=src python -c "
from copilot.agent.copilot import diagnose
r = diagnose('payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east')
print('--- tool calls ---')
for tc in r['tool_calls']:
    print(' ', tc['name'], tc['args'])
print('--- answer ---')
print(r['answer'])
"
```

> **First run will take ~30 seconds** because Ollama has to load `llama3.1:8b` into memory the first time it's called. After that, calls are ~5–8 seconds end-to-end.

**Expected** (verified on the demo machine for the canonical query):

The agent autonomously:
1. Calls `find_similar_incidents_filtered(service_name="payment-service", region="us-east", category="latency", top_k=5)` — extracts all four args from natural language.
2. Calls `get_runbooks_for_incident(108)` on the top hit (the us-east latency anchor pinned in the seeder).
3. Calls `get_service_owner("payment-service")`.
4. Returns: cause hypothesis citing `incident_id: 108`, 3 numbered next steps from the runbook body, on-call handle `@payments-oncall`.

✅ Done — the **center of the diagram is live**. LangChain is calling Ollama and the Vector DB, picking tools, and synthesizing answers.

### 13.6. The golden-tests suite (optional, ~7 s)

There are 5 deterministic retrieval tests. They skip the LLM entirely and just exercise the tool `_impl` functions against the seeded DB:

```bash
PYTHONPATH=src pytest -m integration tests/test_retrieval.py
```

Default `pytest` skips integration; use `-m integration` to run them. Useful to keep CI cheap.

---

## 14. Start the FastAPI backend

> **On the diagram:** the green **FastAPI** box. It exposes the agent over HTTP so something other than a Python REPL can call it.

### 14.1. Run the server

In a **new, dedicated terminal** (it stays running). Activate the venv first if you haven't in this terminal:

```bash
source /full/path/to/oracle-26ai-rag-course/.venv/bin/activate
cd /full/path/to/oracle-26ai-rag-course/apps/ai-incident-copilot
PYTHONPATH=src uvicorn copilot.api.main:app --host 127.0.0.1 --port 8000
```

You should see uvicorn's banner ending with `Application startup complete`.

### 14.2. Verify `/healthz`

In another terminal:

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status":"ok"}
```

If you get a connection refused, uvicorn didn't start — check the first terminal's output.

### 14.3. Smoke-test `/diagnose` over HTTP

This proves the entire backend half of the diagram works without a browser:

```bash
curl -sS -X POST http://127.0.0.1:8000/diagnose \
  -H 'Content-Type: application/json' \
  -d '{"query":"payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east"}' \
  | python3 -m json.tool
```

The response is a JSON object with three keys: `answer`, `tool_calls`, `tool_results`. The `answer` field is the same text you saw in §13.5.

✅ Done — everything but the UI is reachable over HTTP.

> **Production tip:** `--reload` makes uvicorn auto-restart on file changes — great while iterating, but skip it for recording or load-testing (it spawns child workers).

---

## 15. Start the Streamlit UI

> **On the diagram:** the pink **Streamlit** box — the user's window into the system.

### 15.1. Run streamlit

In a **third terminal** (FastAPI from §14 must stay running in its own terminal). Activate the venv first:

```bash
source /full/path/to/oracle-26ai-rag-course/.venv/bin/activate
cd /full/path/to/oracle-26ai-rag-course/apps/ai-incident-copilot
PYTHONPATH=src streamlit run src/copilot/ui/app.py --server.port 8501
```

Streamlit opens the page at <http://127.0.0.1:8501> in your default browser. If not, open it manually.

### 15.2. Layout — inline, not in a sidebar

The Streamlit page has, top to bottom:

- Live `/healthz` indicator (caption at the top — green dot when the API is reachable).
- **Sample-query buttons** as an **inline 3-column row**: canonical (payment / us-east), auth (JWKS / eu-west), ownership (checkout-service).
- Query textarea — the buttons populate it via `st.session_state` so what you click is what you read.
- **Diagnose** button.
- 4 result panels: Answer markdown · Tool calls expander (defaults to expanded) · Retrieved incidents dataframe · Runbooks expanders · Service-owner metrics.

> **Why no sidebar?** Sidebars depend on viewport width and the prior toggle state. During the screen recording the user kept opening with the sidebar collapsed and couldn't see the sample buttons. Lesson: on-camera UI must be visible without a click. Sidebars are a recording liability.

### 15.3. Configuration knobs

Two env vars the UI reads:

| Var | Default | Purpose |
|---|---|---|
| `COPILOT_API_URL` | `http://127.0.0.1:8000` | where to find FastAPI |
| `COPILOT_DIAGNOSE_TIMEOUT_S` | `180` | http timeout for `/diagnose` (first call after a cold Ollama can be ~30 s) |

### 15.4. Click a sample query — end-to-end test

1. Click the first sample-query button (canonical payment/us-east).
2. Click **Diagnose**.
3. Wait. First call after cold start: ~25–30 s. Subsequent: ~5–8 s.
4. The Answer panel renders the cause hypothesis. The Tool calls expander shows the three tool invocations from §13.5. The Retrieved-incidents dataframe highlights `incident_id=108`.

✅ Done — every box on `base-workflow.svg` is live. Your demo is clickable.

---

## 16. Hardening — already baked into the scripts

These two fixes are in the code already. They're documented here so you understand *why* the scripts look the way they do.

### 16.1. Readiness probe — connectability, not log-grep

The `setup_db.sh` script doesn't `grep` `docker logs` to decide when the DB is ready. It runs a real `SELECT 1 FROM DUAL` through `sqlplus -S -L` and greps for the column-header divider:

```bash
# Wrong (original) — slow on macOS, fragile after sleep/wake.
# until docker logs "$NAME" 2>&1 | grep -q "DATABASE IS READY TO USE"; do sleep 5; done

# Wrong (first attempt) — sqlplus -S suppresses the "Connected to:" banner,
# so this loop never matched even when the DB was fully up.
# until docker exec "$NAME" sh -c "echo exit | sqlplus -S system/${PWD}@FREEPDB1" 2>&1 \
#         | grep -q "Connected"; do …

# Right — runs an actual SELECT and greps for the column separator that
# sqlplus -S always emits for a successful query.
deadline=$(( $(date +%s) + ${MAX_WAIT_S:-900} ))
until docker exec "$NAME" sh -c \
        "echo 'SELECT 1 FROM DUAL;' | sqlplus -S -L system/${PASSWORD}@FREEPDB1" 2>&1 \
        | grep -q '^----------'; do
    [ "$(date +%s)" -ge "$deadline" ] && {
        echo "[setup_db] timed out" >&2
        docker logs --tail 20 "$NAME" >&2
        exit 1
    }
    sleep 5
done
```

`-L` keeps sqlplus from re-prompting on a transient login failure (which would hang the probe waiting on stdin we already consumed). The `^----------` underline is the column header divider that sqlplus emits for any successful SELECT under `-S` — unambiguous, present, and missing on any connection error.

Why this is better than the log-grep probe:

| Aspect | `docker logs \| grep` | `sqlplus -S … SELECT 1 \| grep '^----------'` |
|---|---|---|
| What it tests | "did the banner ever appear?" | "is the listener accepting connections right now?" |
| Cost per call | dumps whole container log buffer (10s of MB) | one TCP round-trip + handshake + 1-row query |
| Survives daemon hiccup | ❌ stale stream possible | ✅ each call is independent |
| Time when healthy | seconds | <1 s |

**Real-world reason this matters:** during one resume-from-sleep, the container's *own* clock drifted 29 minutes and `docker logs | grep` wedged for 15 minutes despite the banner being plainly present. The connectability probe was unaffected.

### 16.2. `vector_memory_size` — already covered

See §10.2. Listed here for completeness — without that pool, HNSW indexes can't be created. The fix persists via SPFILE and survives container restart.

---

## 17. Prewarm before recording

> **On the diagram:** this is operational, not architectural. Before you press record, get all three cold caches warm so the on-camera first call isn't 30 seconds of dead air.

### 17.1. Why prewarm

Three things go cold:

1. **Oracle's connection pool** — a fresh oracledb connection from the venv takes ~200ms; warm it once.
2. **Ollama** — `llama3.1:8b` loads into memory on the first call. Cold ≈ **28 s**. Warm ≈ **1.7 s**.
3. **The agent graph** — `sentence-transformers` import + langgraph compile + `oracledb` thin pool. ~3–6 s the first time.

### 17.2. Run `scripts/prewarm.sh`

```bash
cd apps/ai-incident-copilot
bash scripts/prewarm.sh
```

It runs three independent warmups:

1. `SELECT COUNT(*) FROM incidents` inside the container — warms the Oracle listener + pool.
2. A throwaway `POST /api/generate` against Ollama — pulls `llama3.1:8b` into VRAM.
3. A throwaway `POST /diagnose` against your local FastAPI — exercises every cold-cacheable thing in the agent path.

Idempotent. Safe to re-run. Exits non-zero only on a real failure (a missing dep / dead service).

Final line on success:

```
[prewarm] done — first on-camera /diagnose call should be ~5-8 s end-to-end.
```

### 17.3. The full recording checklist

`recording-preflight.md` at the repo root has the T-30 / T-20 / T-10 / T-5 / T-3 / T-1 checklist:

- Stack health (all three terminals green).
- Data integrity (row counts match §11.3).
- OBS config (frame rate, mic, screen capture).
- Secret-hiding (no `.env` open, no Slack notifications, no `~/.aws/credentials` tabs).
- Dry-run punch-list template.
- Mid-recording-failure runbook (what to do if Ollama crashes mid-shot).

The matching storyboard is in `demo-script.md` (8-beat structure for the 08:00–55:00 hands-on segment, ~47 min total).
The query lineup is in `demo-queries.md` (3 locked on-camera queries + ~13 backups grouped by retrieval path).

---

## 18. PR submission — conventions for `oracle-ai-developer-hub`

> **You're here when your demo works on your laptop.** This section is the merge-time checklist for shipping `apps/ai-incident-copilot/` upstream to <https://github.com/oracle-devrel/oracle-ai-developer-hub>. Read it once before opening the PR so the directory looks like a peer of the existing apps from the first commit — instead of being reshuffled after review.

### 18.1. Path correction — `apps/`, not `samples/`

The original brief and this repo's earlier notes say `samples/ai-incident-copilot/`. **`samples/` does not exist.** The repo's actual top-level layout is:

```
apps/         <-- our target lives here
notebooks/
guides/
workshops/
partners/    (placeholder)
.github/workflows/
pyproject.toml
.pre-commit-config.yaml
```

**Submit the PR under `apps/ai-incident-copilot/`.** Confirmed peers under `apps/`: `agentic_rag`, `finance-ai-agent-demo`, `FitTracker`, `oracle-database-vector-search`, `tanstack-shoe-store` (5 of 11).

### 18.2. PR-blocking automation (in `.github/workflows/`)

| Workflow | Trigger | Action needed from us |
|---|---|---|
| `cla.yml` (CLA Assistant) | every PR | Bot comments on the PR; reply `I have read the CLA Document and I hereby sign the CLA` once. PR cannot merge until signed. |
| `license_audit.yml` (scancode-toolkit) | every PR | Every source file must carry a UPL license header (template below). |
| `repolinter.yml` | every PR | Repo-level structural checks. Not an app-level blocker. |
| `sonarcloud.yml` | every PR | Code quality scan — fix any criticals it raises. |
| `banned_file_changes_pr.yml` | every PR | No `.env`, no secrets, no forbidden filetypes. |
| `agentic_rag_smoke.yml` | path-filtered to `apps/agentic_rag/**` | Pattern to copy: ship a tiny smoke test for our app and wire its own path-filtered workflow. |

> The OCA `Signed-off-by:` line on commits (`git commit --signoff`) is the older, manual equivalent of the CLA-assistant bot. Use both — `--signoff` every commit AND respond to the bot — to avoid being told to retry.

### 18.3. Required tooling — Ruff + Prettier + pre-commit

The repo's lint/format config is repo-wide:

- **Python**: Ruff. Config in root `pyproject.toml` — line length **100**, target **py311**, double quotes, rules `E,W,F,I,B,C4,UP`, ignores `E501,B008`. `known-first-party = ["oracle", "oci"]`.
- **JS/TS/JSON/YAML/MD**: Prettier. `printWidth: 100`, `tabWidth: 2`, double quotes, semis, `trailingComma: "es5"`.
- **Pre-commit hooks** required: `pre-commit install` after cloning. Adds trailing-whitespace, end-of-file, large-file (max **2 MB**), JSON/YAML check, merge-conflict, private-key detection.

In the demo machine setup we already run `ruff` formatted code by default — re-run before committing:

```bash
.venv/bin/pip install pre-commit ruff prettier   # if not already installed via requirements.txt
pre-commit install                                # only when working inside a clone of the hub
pre-commit run --all-files                        # format everything before pushing
```

### 18.4. Per-app directory layout (consensus across `agentic_rag` / `finance-ai-agent-demo` / `FitTracker`)

Match this skeleton exactly so the diff reads naturally:

```
apps/ai-incident-copilot/
├── README.md                  # required, see §18.5 for required sections
├── requirements.txt           # pinned Python deps for the app
├── docker-compose.yml         # demo stack: oracle DB + app
├── Dockerfile                 # only if the app itself ships as a container
├── .env.example               # commit; .env stays in .gitignore
├── src/
│   └── copilot/               # importable package
│       ├── __init__.py
│       ├── api/main.py        # FastAPI app
│       ├── ui/app.py          # Streamlit UI
│       ├── agent/copilot.py   # LangChain agent + 4 tools
│       ├── rag/{embedder,vectorstore}.py
│       └── db/{connection,schema.sql,seed.py}
├── scripts/                   # setup / data / smoke scripts (peers all use this)
│   └── setup_db.sh
├── tests/
│   ├── test_retrieval.py      # 5 golden retrieval tests (unit-fast)
│   └── integration/           # marker: integration; opt-in with `pytest -m integration`
├── img/                       # screenshots for the README (peer convention)
└── docs/                      # optional, for the demo script + architecture diagram
```

### 18.5. Per-app README — required sections (peer pattern)

Every existing app's README has, in this order:

1. **Title + 1-paragraph description** ("what this app demonstrates")
2. **Architecture diagram** (ASCII or `img/architecture.png`)
3. **Prerequisites** (Docker, Python 3.10+, Ollama, etc.)
4. **Quick Start** — numbered steps to a running demo
5. **Features** — what's noteworthy (vector search, hybrid retrieval, etc.)
6. (optional) **API endpoints**, **Configuration**, **Deployment**
7. **License** — UPL note

### 18.6. UPL license header — required on every source file

`license_audit.yml` (scancode-toolkit) gates the PR. Add this header to every Python source file (and adapt for SQL `--`, YAML `#`, etc.):

```python
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
```

### 18.7. Pytest markers — already defined repo-wide

Use these in our tests so `pytest` (the default fast run) skips heavy work:

```python
import pytest

@pytest.mark.integration
@pytest.mark.requires_oracle
@pytest.mark.requires_ollama
def test_full_diagnose_flow():
    ...
```

The repo's `pyproject.toml` already declares these markers; do not redefine them. `pytest` (default) skips integration; `pytest -m integration` runs the full stack.

### 18.8. Top-level README table — add a row

After the app lands, the top-level `README.md` `Apps` table needs a row for ours:

```markdown
| ai-incident-copilot | AI on-call copilot — semantic retrieval over incidents, runbooks, and service catalog with Oracle 26ai vector search + LangChain. | [![View App](https://img.shields.io/badge/View%20App-blue?style=flat-square)](./apps/ai-incident-copilot) |
```

### 18.9. LangChain integration choice — note for scaffolding

Peer apps use **`langchain-oracledb`** (the dedicated Oracle integration: `OracleVS`, `OracleEmbeddings`, `OracleTextSplitter`) — see `apps/agentic_rag/requirements.txt` and `notebooks/agentic_rag_langchain_oracledb_demo.ipynb`. Our local `requirements.txt` currently uses `langchain-community`'s older `OracleVS`. Before scaffolding upstream, **swap to `langchain-oracledb`** to align with the hub.

### 18.10. PR pre-flight checklist

Before opening the PR, verify all of these:

- [ ] App lives at `apps/ai-incident-copilot/`
- [ ] OCA / CLA signed (commit with `--signoff` AND respond to the CLA bot)
- [ ] UPL header on every source file
- [ ] Per-app `README.md` has the 7 required sections
- [ ] `pre-commit run --all-files` exits clean
- [ ] No file >2 MB committed (sample data must be small or external)
- [ ] No `.env` or secrets — only `.env.example`
- [ ] At least one smoke test (`tests/test_smoke.py`) and one path-filtered workflow at `.github/workflows/ai_incident_copilot_smoke.yml`
- [ ] Top-level `README.md` Apps table has the new row
- [ ] PR description: what it does, how to validate, link to the issue (per `apps/oci-generative-ai-jet-ui/CONTRIBUTING.md` §"Pull request process")

---

## Appendix A — Phase-result archive (audit trail)

These notes were captured as each phase landed. They're preserved here for the record; the linear instructions above already incorporate everything actionable.

### Phase 4 result — seed data (applied 2026-05-05)

`src/copilot/db/seed.py` populates a fresh schema in **~23 s** (well under the 2-min exit criterion).

Run from `apps/ai-incident-copilot/` with the venv:

```bash
PYTHONPATH=src .venv/bin/python -m copilot.db.seed
```

Final state:

| Table | Rows |
|---|---|
| `services` | 20 |
| `incidents` | 50 (anchor block: 12 are `payment-service` — 1 per category + 6 latency, with one latency incident pinned to `us-east` so the canonical filtered demo always has a hit) |
| `runbooks` | 15 (≥2 per category across 7 categories) |
| `incident_runbooks` | 107 (joined by category) |

Verified queries:

```sql
-- Pure semantic top-5 for the canonical query
-- → 5 payment-service latency incidents, distances 0.26–0.30
SELECT incident_id, service_name, category, region,
       VECTOR_DISTANCE(embedding, :v, COSINE) AS dist
FROM incidents
ORDER BY VECTOR_DISTANCE(embedding, :v, COSINE)
FETCH FIRST 5 ROWS ONLY;

-- Filtered (service + region) — guaranteed ≥1 hit at dist ≈ 0.27
SELECT … WHERE service_name='payment-service' AND region='us-east' …;
```

Notes carried forward into Phase 5:
- The seeder uses `array.array("f", embedding)` to bind VECTOR(384, FLOAT32). Same pattern works for retrieval-side queries.
- IDENTITY sequences advance across re-seeds (rows are DELETEd not TRUNCATEd) — harmless, but if cosmetic ID stability matters later, switch `_wipe()` to `TRUNCATE TABLE … DROP STORAGE`.
- `.env` lives at `apps/ai-incident-copilot/.env` (copied from `.env.example`); `connection.py` loads it via `load_dotenv()`.

### Phase 5 result — agent + tools (applied 2026-05-05)

Files added:
- `src/copilot/agent/tools.py` — 4 `@tool` functions, each with a parallel `_impl` for tests.
- `src/copilot/agent/copilot.py` — `ChatOllama(llama3.1:8b)` + `langchain.agents.create_agent` (the langchain-1.x replacement for the deprecated `langgraph.prebuilt.create_react_agent`). Exposes `diagnose(query) -> {answer, tool_calls, tool_results}`.
- `src/copilot/api/main.py` — `/diagnose` now invokes the agent (was 501 stub).
- `tests/test_retrieval.py` — 5 golden tests (all pass in 7 s; run `PYTHONPATH=src pytest -m integration tests/test_retrieval.py`).

End-to-end verified with the canonical query *"payment-service p99 latency spiked to 8s, started 14:32 UTC, only us-east"*. The agent autonomously:
1. Calls `find_similar_incidents_filtered(service_name="payment-service", region="us-east", category="latency", top_k=5)` — extracts all four args from natural language.
2. Calls `get_runbooks_for_incident(108)` on the top hit (the us-east latency anchor pinned in the seeder).
3. Calls `get_service_owner("payment-service")`.
4. Returns: cause hypothesis citing `incident_id: 108`, 3 numbered next steps from the runbook body, on-call handle `@payments-oncall`.

Notes carried forward into Phase 6:
- Run the API: `cd apps/ai-incident-copilot && PYTHONPATH=src .venv/bin/uvicorn copilot.api.main:app --reload`
- Filter inputs to the tools are whitelisted (`_ALLOWED_REGIONS`, `_ALLOWED_CATEGORIES`) so the LLM can't smuggle SQL via free-text WHERE clauses.
- The model occasionally serializes int args as strings (e.g. `top_k: "5"`); the tool wrapper coerces silently via `min(top_k, 20)`.

### Phase 6 result — API + UI (applied 2026-05-05)

Two-process demo stack, both verified end-to-end with the canonical query:

```bash
# Terminal 1 — FastAPI
PYTHONPATH=src .venv/bin/uvicorn copilot.api.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — Streamlit
PYTHONPATH=src .venv/bin/streamlit run src/copilot/ui/app.py --server.port 8501

# Terminal 3 — pre-warm Ollama before the recording (cold ~28 s, warm ~1.7 s per call)
curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"llama3.1:8b","prompt":"warm","stream":false}' >/dev/null
```

Browser: <http://127.0.0.1:8501>. API JSON: `POST http://127.0.0.1:8000/diagnose` with `{"query":"…"}`.

Streamlit page (`src/copilot/ui/app.py`):
- Sidebar: live `/healthz` indicator + 3 sample-query buttons (canonical, auth/JWKS, ownership).
- Main: query textarea → Diagnose button → 4 result panels (Answer markdown, Tool calls, Retrieved incidents dataframe, Runbooks expanders, Service owner metrics).
- Reads `COPILOT_API_URL` (default `http://127.0.0.1:8000`) and `COPILOT_DIAGNOSE_TIMEOUT_S` (default 180).

`POST /diagnose` HTTP smoke matched the in-process Phase 5 result exactly (same 3 tool calls, same `incident_id: 108`, same answer text).

Notes carried forward into Phase 7 (recording):
- Pre-warm Ollama with a throwaway `/api/generate` before recording — first call after launch is ~28 s cold.
- Streamlit's `st.session_state` holds the textarea content, so the sample-query buttons populate the field instantly without re-render delay.
- The `Tool calls` expander defaults to `expanded=True` so the on-screen demo shows the agent's reasoning trace without a click.

### Phase 7 result — recording prep (applied 2026-05-06)

Four deliverables, all at the repo root unless noted:

- **`demo-script.md`** — 8-beat storyboard for the 08:00–55:00 hands-on segment. Each beat = timestamp range + on-screen action + 3–6 narration bullet points (paraphrase, don't memorize). Total 47 min.
- **`demo-queries.md`** — 3 locked on-camera queries + ~13 backup queries grouped by retrieval path (A: pure semantic, B: hybrid, C: ownership, D: compare-and-contrast, E: edge cases).
- **`apps/ai-incident-copilot/scripts/prewarm.sh`** — idempotent 3-step prewarm (Oracle pool → Ollama → agent graph). Run ~30 s before camera. Verified end-to-end.
- **`recording-preflight.md`** — T-30 / T-20 / T-10 / T-5 / T-3 / T-1 checklist (stack health, data integrity, OBS config, secret-hiding, dry-run punch-list template, mid-recording-failure runbook).

Streamlit UI tweaks driven by recording needs:
- Sample-query buttons moved out of the sidebar to an inline 3-column row above the textarea. Sidebar collapses by default. **Why:** sidebars are a recording liability — they depend on viewport width and prior toggle state. On-camera UI must be visible without a click.
- Buttons' visible text matches `demo-queries.md` "On-camera lineup" verbatim, so what you click is what you read in the script.

### Scaffold result — directory structure (applied 2026-05-04)

The directory was scaffolded to match the per-app conventions captured in §18.4–§18.7. Files committed (23 total):

```
apps/ai-incident-copilot/
├── README.md                           # 7-section format from §18.5
├── requirements.txt                    # langchain-oracledb (not -community), langchain-ollama, etc.
├── docker-compose.yml                  # Oracle 26ai service (Ollama runs on host)
├── Dockerfile                          # for the FastAPI app
├── .env.example                        # ORACLE_DSN/USER/PASSWORD, OLLAMA_*, EMBEDDING_*
├── scripts/setup_db.sh                 # idempotent: pull image + start container + bootstrap copilot user
├── src/copilot/
│   ├── __init__.py
│   ├── db/{__init__,connection,seed}.py    # connection: real, seed: stub (Phase 4)
│   ├── db/schema.sql                       # 4 tables + 2 HNSW vector indexes, idempotent DROPs
│   ├── rag/{__init__,embedder,vectorstore}.py  # embedder: real MiniLM, vectorstore: langchain-oracledb wrapper
│   ├── agent/copilot.py                # stub (Phase 5)
│   ├── api/main.py                     # /healthz live, /diagnose stub (returns 501)
│   └── ui/app.py                       # Streamlit shell (input box + placeholder)
├── tests/test_smoke.py                 # 2 fast tests, both passing
└── tests/test_retrieval.py             # 5 stubs, marked integration+requires_oracle (Phase 5)
.github/workflows/ai_incident_copilot_smoke.yml   # path-filtered CI, modeled on agentic_rag_smoke.yml
```

**Verified during scaffolding:**

- `langchain-oracledb 1.3.0`, `langchain-ollama 1.1.0`, `langchain-huggingface 1.2.2` installed cleanly into the venv.
- `pytest tests/test_smoke.py` → 2 passed in 40 s (the 40 s is one-time `sentence-transformers` import; subsequent runs much faster).
- Smoke tests assert that `copilot.*` imports and that `schema.sql` declares `VECTOR(384, FLOAT32)` + a `CREATE VECTOR INDEX` statement.

**Discovered during scaffolding** — two structural changes vs. the original brief (both now in §10):

1. **Cannot connect as `system`.** `ORA-43853: VECTOR type cannot be used in non-automatic segment space management tablespace "SYSTEM"`. The application schema must be a non-SYSTEM user with a default tablespace that uses ASSM (e.g. `USERS`). `setup_db.sh` now bootstraps a dedicated `copilot` user idempotently, and `.env.example` defaults to `ORACLE_USER=copilot`.
2. **Don't read the readiness banner from `docker logs`.** macOS sleep/wake suspends the Docker Desktop VM; on resume `docker logs <container>` can return stale or never-completing streams (we observed a 29-min wall-clock drift event in the Oracle container's own log, after which a `until docker logs ... grep` loop wedged for 15 minutes despite the banner being plainly present). The fix is to probe **connectability**, not log content — see §16.1.

#### Schema applied after Mac restart (resolved 2026-05-05)

Resume sequence after restart completed cleanly:

1. Patched `setup_db.sh` per §16.1 → `copilot` user bootstrapped on first run.
2. `schema.sql` applied as `copilot/Welcome_123@FREEPDB1`.
3. **First run hit ORA-51962** on both `CREATE VECTOR INDEX` statements — `vector_memory_size = 0` in the Free image's default SPFILE. Fix in §10.2.
4. After raising the pool to 512M and restarting the container, both HNSW indexes created cleanly.

**Final state on disk:** 4 tables (`SERVICES`, `INCIDENTS`, `RUNBOOKS`, `INCIDENT_RUNBOOKS`), 2 HNSW vector indexes (`INCIDENTS_EMBEDDING_HNSW`, `RUNBOOKS_EMBEDDING_HNSW`), 3 B-tree indexes for filter columns, plus the auto-generated `VECTOR$…` infra tables that back HNSW. Verified via `USER_TABLES` / `USER_INDEXES` (note: `USER_VECTOR_INDEXES` view does not exist in 26ai — use `USER_INDEXES.INDEX_TYPE='VECTOR'`).

---

## Appendix B — Troubleshooting log

- **2026-05-04 — `ORA-43853` when applying `schema.sql` as `system`.** VECTOR columns require automatic segment space management; SYSTEM tablespace uses manual SSM. Fix: bootstrap a dedicated `copilot` user with `DEFAULT TABLESPACE USERS` and connect as that user. Implemented in `setup_db.sh`. *(See §10.1.)*
- **2026-05-05 — `setup_db.sh` wedged 15 min in until-loop after macOS sleep/wake.** Container's own log showed a 29-min clock drift on resume. `docker logs | grep` probe hung; healthy interactive grep returned exit 0 instantly. Fix: switch to a SQL*Plus connectability probe. *(See §16.1.)*
- **2026-05-05 — first connectability probe (`grep "Connected"`) timed out at 300s despite DB being fully ready.** Cause: `sqlplus -S` (silent) suppresses the "Connected to:" banner. Fix: probe with `SELECT 1 FROM DUAL` and grep for the `^----------` column-header divider that `-S` always emits for a successful query. *(See §16.1.)*
- **2026-05-05 — `CREATE VECTOR INDEX` failed with ORA-51962 on first schema apply.** Cause: Oracle 26ai Free image ships with `vector_memory_size = 0`; HNSW indexes need a non-zero pool. Fix: `ALTER SYSTEM SET vector_memory_size = 512M SCOPE=SPFILE` on the CDB, restart the container. *(See §10.2.)*
