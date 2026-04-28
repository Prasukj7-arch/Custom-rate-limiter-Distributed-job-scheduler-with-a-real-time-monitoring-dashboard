# Sentinel — Distributed Rate Limiter, Job Scheduler & Real-Time Monitoring System

A production-style distributed backend system with strong consistency guarantees that combines high-throughput rate limiting, asynchronous job processing, fault-tolerant crash recovery, and a live monitoring dashboard into a single cohesive architecture.

> Designed to simulate production-grade backend challenges: rate limiting, async processing, fault tolerance, and observability in a single system.

---

## Problem Statement

Most backend projects solve one of these: rate limiting, async queues, or monitoring. This project solves all four together — and makes them work correctly under failure conditions.

- **Abuse prevention** — atomic rate limiting that works across multiple API processes
- **Async processing** — callers get instant responses; heavy work runs in the background
- **Fault tolerance** — workers can crash mid-job; the system self-heals
- **Observability** — live telemetry streamed to a monitoring dashboard in real time

---

## Architecture Overview

> End-to-end flow: request → rate limiter → job queue → worker → PostgreSQL → metrics → dashboard

![System Architecture](./Scalable%20Rate%20Limiter%20+%20Distributed%20Job%20Scheduler%20Architecture.png)

### Request Flow

```
Client Request
      │
      ▼
FastAPI (RateLimiterMiddleware)
      │
      ├─ Redis Lua Script (atomic token bucket check)
      │
      ├─ Blocked ──► HTTP 429 + increment metrics:blocked
      │
      └─ Allowed ──► Route Handler + increment metrics:allowed
                          │
                          ▼
                   Redis ZSET (job_queue)  ◄──── /upload-story
                   Redis ZSET (job_queue)  ◄──── /delayed-story-upload (score = now+5s)
                          │
                          ▼
                    Worker Process (ZPOPMIN)
                          │
                          ├─ Score > now? ──► re-enqueue, sleep 2s
                          │
                          ├─ Execute job
                          │     ├─ Success ──► status = completed, incr metrics:processed
                          │     └─ Failure ──► retries++, backoff re-enqueue or status = dead
                          │
                          └─ PostgreSQL (via SQLAlchemy ORM)
                                │
                                ▼
                         metrics:* counters in Redis
                                │
                                ▼
                     SSE stream (/metrics/stream)
                                │
                                ▼
                      Sentinel Dashboard (index.html)
```

---

## Quick Demo

Run the complete system locally in under a minute:

```bash
# Terminal 1 — API server
uvicorn main:app --reload

# Terminal 2 — Job worker
python worker.py

# Terminal 3 — Submit a job
curl -X POST http://127.0.0.1:8000/upload-story \
  -H "Content-Type: application/json" \
  -d '{"title":"hello","content":"test"}'
```

Then open `index.html` in your browser and watch the metrics update live.

---

## Key Features

### 1. Distributed Rate Limiting — Token Bucket via Redis + Lua

Rate limiting is enforced globally through FastAPI middleware (`RateLimiterMiddleware`). Every request passes through it before reaching any route handler.

**How it works:**
- State (token count + last refill timestamp) is stored in Redis as a hash: `rate_limiter:{user}:{path}`
- A Lua script runs atomically on Redis — reads state, refills tokens based on time elapsed, consumes one token, writes back
- Because Lua runs atomically inside Redis, there are **zero race conditions** even across multiple API processes

**Per-route configuration (`ROUTE_LIMITS`):**

| Route | Capacity | Refill Rate |
|---|---|---|
| `/login` | 5 tokens | 1 token/sec |
| `/upload-story` | 10 tokens | 2 tokens/sec |
| All others | 5 tokens | 1 token/sec (default) |

**Bypass list** — rate limiting is skipped for: `/health/redis`, `/redis-test`, `/metrics/stream`

**Blocked requests** return `HTTP 429` and increment the `metrics:blocked` counter in Redis.

---

### 2. Asynchronous Job Queue — Redis Sorted Set (ZSET)

Jobs are intentionally processed asynchronously. The caller gets an immediate `202`-style response while the job is placed into a Redis ZSET (`job_queue`) with the current Unix timestamp as its score.

- **Immediate jobs**: score = `time.time()` — worker picks up instantly
- **Delayed jobs**: score = `time.time() + 5` — worker skips until the timestamp is reached

The ZSET naturally provides ordering; `ZPOPMIN` always returns the job with the lowest (earliest) score.

---

### 3. Atomic Worker — No Duplicate Execution

The worker uses `ZPOPMIN` to atomically claim a job from the queue. This is the key to correctness:

- **Atomic claim**: `ZPOPMIN` removes and returns the job in one Redis operation — no two workers can claim the same job
- **Future job check**: if `score > now`, the job is re-enqueued and the worker sleeps 2 seconds before retrying
- **DB guard**: after claiming, the worker updates status from `queued → processing` only if the row exists and is in a claimable state (`queued` or `failed`). If `updated == 0`, the job is skipped — preventing double execution on recovery
- **Success path**: status → `completed`, `metrics:processed` incremented
- **Failure path**: status → `failed`, `retries` incremented, re-enqueued with exponential backoff

**Exponential backoff formula:**
```
delay = min(2 ^ retries, 300)   # seconds; caps at 5 minutes
```

Example progression: 2s → 4s → 8s → 16s → 32s → dead (after 5 retries)

**Dead-letter threshold**: after **5 failed retries**, the job is marked `dead` and not re-enqueued.

---

### 4. Reliable Persistence — SQLAlchemy ORM + PostgreSQL

The `Job` model (defined via SQLAlchemy's declarative ORM) tracks the full lifecycle of every job:

```
queued → processing → completed
                   └→ failed → (retry) → dead
```

**Schema (`models.py`):**

| Column | Type | Notes |
|---|---|---|
| `id` | String (PK) | Unix timestamp string at creation |
| `type` | String | e.g. `upload_story` |
| `payload` | JSON | Full job data |
| `status` | String | `queued / processing / completed / failed / dead` |
| `retries` | Integer | Starts at 0, max 4 before dead |
| `created_at` | DateTime | Auto-set on insert |
| `updated_at` | DateTime | Auto-updated on change |

Tables are created automatically via `Base.metadata.create_all()` on first import — no manual `CREATE TABLE` needed.

---

### 5. Crash Recovery Service — `recovery.py`

A separate, independently runnable process that handles workers crashing mid-job:

- Queries PostgreSQL for any job stuck in `processing` for **more than 5 minutes**
- Resets their status back to `queued` so they can be reclaimed
- Runs in an infinite loop, polling every **60 seconds**

This ensures the system self-heals from unexpected crashes without manual intervention.

---

### 6. Real-Time Monitoring — Server-Sent Events (SSE)

The `/metrics/stream` endpoint streams live system metrics every **2 seconds** using SSE (`text/event-stream`). No WebSockets, no polling overhead.

**Metrics tracked (Redis counters):**

| Metric | Redis Key | Description |
|---|---|---|
| Allowed requests | `metrics:allowed` | Requests that passed rate limiting |
| Blocked requests | `metrics:blocked` | Requests that hit HTTP 429 |
| Jobs processed | `metrics:processed` | Successfully completed jobs |
| Job failures | `metrics:failed` | Jobs that raised an exception |
| Queue depth | `ZCARD job_queue` | Current jobs waiting in the ZSET |

The stream gracefully handles disconnects via `asyncio.CancelledError`.

---

### 7. Sentinel Dashboard — `index.html` + `script.js`

A dark-themed, real-time monitoring dashboard named **Sentinel Control Plane**.

**Features:**
- 5 live metric counters (allowed, rate-limited, executed, failed, queue depth)
- Rolling 25-point line chart showing: Jobs Executed / Failures / Queue Backlog
- SSE connection status indicator (CONNECTED / LINK INTERRUPTED)
- Contextual alert system:
  - `failures > 5` → **Critical Job Execution Failures**
  - `queue_depth > 10` → **Task queue depth exceeding threshold**
  - `blocked > 100` → **High volume of rate-limited traffic**

Built with vanilla HTML/CSS/JS + Chart.js (CDN). No build step required.

> Live metrics are streamed every 2 seconds via SSE and rendered directly in the browser — no polling, no WebSocket handshake overhead.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.128 |
| ASGI Server | Uvicorn |
| Rate Limiting | Redis 7 + Lua (atomic) |
| Job Queue | Redis Sorted Set (ZSET) |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL |
| Worker | Python (blocking loop) |
| Crash Recovery | Python (separate process) |
| Monitoring Stream | Server-Sent Events (SSE) |
| Dashboard | HTML + Vanilla JS + Chart.js |

---

## Project Structure

```
.
├── main.py          # FastAPI app — rate limiter middleware, all API routes, SSE stream
├── worker.py        # Job worker — ZPOPMIN claim, execution, retry/backoff logic
├── recovery.py      # Crash recovery — resets stuck 'processing' jobs every 60s
├── models.py        # SQLAlchemy Job model — schema + auto table creation
├── db.py            # Database connection — SQLAlchemy engine + SessionLocal
├── index.html       # Sentinel dashboard — live metrics UI
├── script.js        # Dashboard logic — SSE client, Chart.js, alert system
├── style.css        # Dashboard styles
└── requirements.txt # All pinned dependencies
```

---

## API Reference

### `POST /login`
Authenticate a user. Rate limited: **5 requests / 5 seconds** per user per IP.

**Request:**
```json
{ "username": "alice", "password": "secret" }
```
**Response:**
```json
{ "status": "success", "message": "login successful", "data": { "user": "alice" } }
```

---

### `POST /upload-story`
Submit a story for async processing. Returns immediately; processing happens in the background. Rate limited: **10 requests / 5 seconds**.

**Request:**
```json
{ "title": "My Story", "content": "Once upon a time..." }
```
**Response:**
```json
{ "status": "success", "message": "story queued", "job_id": "1714300000.123" }
```

> **Trigger forced failure:** Send `"title": "fail"` — the worker will raise an exception to test retry/backoff/dead-letter logic.

---

### `POST /delayed-story-upload`
Queue a story job with a **5-second execution delay**. Identical payload to `/upload-story`. Returns `{ "status": "resolved" }` immediately.

---

### `GET /jobs`
Inspect the current Redis ZSET queue. Returns all pending jobs with their scheduled execution timestamps (scores).

---

### `GET /health/redis`
Connectivity check — pings Redis and returns `{ "status": "healthy" }` or `{ "status": "unhealthy" }`.

---

### `GET /redis-test`
Diagnostic endpoint — writes and reads a test key in Redis to verify read/write connectivity.

---

### `GET /metrics/stream`
SSE endpoint. Streams a JSON event every 2 seconds:
```json
{
  "allowed": 142,
  "blocked": 18,
  "processed": 57,
  "failed": 3,
  "queue_depth": 4
}
```
**Not rate-limited** — explicitly excluded from middleware.

---

## Setup & Running

### Prerequisites
- Python 3.11+
- Redis (running locally on port 6379)
- PostgreSQL (running locally on port 5432)

---

### 1. Clone & Install Dependencies

```bash
git clone <repo-url>
cd <repo-directory>
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### 2. Start Redis

```bash
redis-server
```

---

### 3. Create the PostgreSQL Database

```bash
createdb jobs_db
```

> The `jobs` table is created **automatically** by SQLAlchemy (`Base.metadata.create_all()`) when the app or worker first imports `models.py`. No manual `CREATE TABLE` required.

If you need to connect with a different user, update `DATABASE_URL` in `db.py`:
```python
DATABASE_URL = "postgresql://<user>@localhost:5432/jobs_db"
```

---

### 4. Run the API Server

```bash
uvicorn main:app --reload
```

API available at: `http://127.0.0.1:8000`  
Interactive docs: `http://127.0.0.1:8000/docs`

---

### 5. Run the Worker

In a **separate terminal**:

```bash
python worker.py
```

The worker runs an infinite loop, polling the ZSET queue and processing jobs.

---

### 6. (Optional) Run the Crash Recovery Service

In a **third terminal**, for production-level fault tolerance:

```bash
python recovery.py
```

This resets any job stuck in `processing` for over 5 minutes, every 60 seconds.

---

### 7. Open the Dashboard

Open `index.html` directly in your browser. It connects automatically to `http://127.0.0.1:8000/metrics/stream`.

---

## Testing Scenarios

### Rate Limiting — HTTP 429
```bash
# Rapid-fire /login — expect 429 after 5 requests from the same IP
for i in {1..8}; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/login \
    -H "Content-Type: application/json" \
    -d '{"username":"alice","password":"secret"}'
done
```
Expected: first 5 return `200`, remaining return `429`.

---

### Per-User Isolation
```bash
# alice and bob each get their own token bucket
curl -X POST http://127.0.0.1:8000/login -H "user: alice" ...
curl -X POST http://127.0.0.1:8000/login -H "user: bob" ...
```

---

### Immediate Job Execution
```bash
curl -X POST http://127.0.0.1:8000/upload-story \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello","content":"World"}'
```
Watch `worker.py` output and verify PostgreSQL: `status = completed`.

---

### Delayed Job Execution
```bash
curl -X POST http://127.0.0.1:8000/delayed-story-upload \
  -H "Content-Type: application/json" \
  -d '{"title":"Delayed","content":"Runs in 5 seconds"}'
```
Worker ignores it for ~5 seconds, then picks it up.

---

### Forced Failure + Retry + Dead-Letter
```bash
curl -X POST http://127.0.0.1:8000/upload-story \
  -H "Content-Type: application/json" \
  -d '{"title":"fail","content":"trigger error"}'
```
Worker raises an exception. Observe retries with exponential backoff in logs. After 5 retries, PostgreSQL shows `status = dead`.

---

### Crash Recovery
1. Submit a job, then kill the worker (`Ctrl+C`) while it's processing
2. PostgreSQL row stays in `processing` state
3. Run `python recovery.py` — within 60 seconds (or immediately if the stuck time threshold is met), it resets to `queued`
4. Restart the worker — job is re-executed

---

### Live Dashboard
1. Start the API and worker
2. Open `index.html` in your browser
3. Submit jobs and watch counters and the rolling chart update in real time

---

## System Guarantees

| Guarantee | Mechanism |
|---|---|
| No duplicate job execution | `ZPOPMIN` (atomic Redis claim) + DB status guard |
| Atomic rate limiting | Lua script on Redis (single-threaded execution) |
| Retry with backoff | `min(2^retries, 300s)` capped at 5 minutes |
| Crash recovery | `recovery.py` resets stuck jobs every 60s |
| Graceful failure isolation | Dead-letter state after 5 retries — bad jobs don't loop forever |
| Real-time observability | SSE stream with 2-second resolution |

---

## Known Limitations

- **Metrics are cumulative counters** — no time-series storage; a restart resets them
- **No authentication** — rate limiting keys on IP or `user` header (static, not session-based)
- **Single-node worker** — no distributed worker orchestration; one `worker.py` process
- **No alerting delivery** — dashboard alerts are visual-only (no email/Slack/PagerDuty)
- **No metrics persistence** — Redis counters are lost if Redis restarts without persistence enabled
- **Missing DB job warning is intentional** — if a job is claimed from Redis but has no matching DB row, the worker logs a warning and skips it safely; this is a deliberate early-exit guard, not a silent failure

---

## Future Improvements

- **Prometheus + Grafana** — replace Redis counters with proper time-series metrics
- **User-tier rate limiting** — different limits for free vs. paid users
- **Priority queues** — multiple ZSET queues with different worker priorities
- **Distributed workers** — Kubernetes-based horizontal scaling of `worker.py`
- **Dead-letter queue UI** — visualize and replay failed jobs from the dashboard
- **Redis persistence** — enable RDB/AOF snapshots so metrics survive restarts

---

## Summary

Built a fault-tolerant distributed backend system with atomic rate limiting (Redis + Lua), async job processing (Redis ZSET), exponential retry with dead-letter isolation, automatic crash recovery, and real-time monitoring via Server-Sent Events.

This system demonstrates how real-world backend services balance performance, reliability, and observability under distributed conditions.
