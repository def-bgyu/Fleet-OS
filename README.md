# ⚡ FleetOS

**A distributed AI inference node fleet management platform — self-registering, self-healing, and self-scaling.**

---

## What is FleetOS?

FleetOS is a production-style infrastructure platform that manages fleets of AI inference nodes at scale. It handles everything from node onboarding to failure recovery to auto-scaling — with no human intervention. It mirrors the kind of internal tooling AI teams build to manage large accelerator fleets.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        React Dashboard                       │
│         (live fleet view, job submission, activity log)      │
└────────────────────────────┬────────────────────────────────┘
                             │ REST API (port 3000)
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
   Registry Service   Scheduler Service   Docker Manager
   (port 8000)        (port 8001)         (port 8002)
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                         Redis Queue
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
      Healer            Autoscaler         Prometheus
   (background)        (background)        (port 9090)
                                               │
                                           Grafana
                                          (port 3001)
                                               │
                          ┌────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
      node-001        node-002  ...   node-006
   (Docker container, exposes metrics on port 910x)
```

---

## Services

### Registry Service (`/registry-service`)
The central source of truth for the fleet. Nodes self-register on boot and send heartbeats every 10 seconds. A background health check runs every 15 seconds — if a node exceeds the 30-second heartbeat threshold it's automatically marked dead.

**Endpoints:**
- `POST /register` — node self-registration on boot
- `POST /heartbeat` — node health update every 10s
- `GET /nodes` — all node statuses
- `GET /fleet/summary` — fleet-wide health summary
- `POST /fleet/clear-dead` — remove dead nodes from registry

### Scheduler Service (`/scheduler-service`)
Distributes inference jobs across healthy nodes using a weighted load balancing algorithm (70% CPU, 30% latency). Supports priority queuing — urgent jobs jump to the front of the Redis queue via `lpush`.

**Endpoints:**
- `POST /jobs/submit` — submit a new job (priority 1-3)
- `GET /jobs` — all jobs and their statuses
- `GET /queue/length` — current queue depth

### Self-Healer (`/scheduler-service/healer.py`)
A background service that scans for dead nodes every 15 seconds. When a dead node is detected, it finds all orphaned jobs (status `running`, assigned to dead node) and requeues them at the front of the Redis queue. End-to-end recovery happens in under 30 seconds.

### Autoscaler (`/scheduler-service/autoscaler.py`)
A background service that monitors fleet-wide avg CPU every 30 seconds and makes scaling decisions automatically:
- avg CPU > 70% AND nodes < 6 → scale up (add node)
- avg CPU < 30% AND nodes > 2 → scale down (remove least busy node)

Includes a 60-second cooldown to prevent thrashing.

### Docker Manager (`/docker-manager`)
Manages the lifecycle of node containers dynamically. Handles spinning up new nodes, killing nodes, and restarting them. Syncs with existing Docker containers on startup to prevent conflicts after restarts.

**Endpoints:**
- `POST /nodes/add` — spin up a new node container
- `POST /nodes/{id}/kill` — kill a node
- `POST /nodes/{id}/restart` — restart a killed node
- `POST /nodes/{id}/remove` — kill and fully remove a node

### Node Agent (`/node-agent`)
Runs inside each Docker container. On boot it self-registers with the registry, then enters a heartbeat loop — running a simulated inference workload (matrix multiplication) every 10 seconds and reporting CPU usage, latency, and job count. Exposes Prometheus metrics on a dedicated port.

**Node lifecycle:** `starting → healthy → dead → recovering → healthy`

### React Dashboard (`/dashboard`)
A live fleet management UI with sidebar navigation. Auto-refreshes every 3 seconds.

**Pages:**
- **Overview** — fleet summary stats, health pie chart, activity log, node cards
- **Nodes** — full node grid with kill/restart controls
- **Jobs** — last 50 jobs with status, assigned node, and duration
- **Metrics** — CPU and latency time-series graphs per node (Recharts)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend services | Python, FastAPI |
| Job queue | Redis |
| Node simulation | Docker containers |
| Monitoring | Prometheus, Grafana |
| Frontend | React, Recharts |
| Container management | Docker SDK for Python |

---

## Getting Started

### Prerequisites
- Python 3.11+
- Docker Desktop
- Node.js 18+
- Redis (via Docker)

### Install dependencies

```bash
# Backend
pip install fastapi uvicorn redis celery requests numpy prometheus-client docker grpcio grpcio-tools

# Frontend
cd dashboard
npm install
```

### Run Redis
```bash
docker run -p 6379:6379 redis
```

### Start all services (separate terminals)

```bash
# Registry
cd registry-service && python registry.py

# Scheduler
cd scheduler-service && python scheduler.py

# Healer
cd scheduler-service && python healer.py

# Autoscaler
cd scheduler-service && python autoscaler.py

# Docker Manager
cd docker-manager && python manager.py

# Dashboard
cd dashboard && npm start
```

### Build the node Docker image
```bash
cd node-agent
docker build -t fleetos-node .
```

### Add nodes
Click **"+ Add Node"** on the dashboard, or call:
```bash
curl -X POST http://localhost:8002/nodes/add
```

---

## Key Engineering Decisions

**Heartbeat-based failure detection** — nodes are declared dead by absence of signal, not an explicit death message. This catches crashes, network failures, and silent hangs.

**Separation of concerns** — registry, scheduler, healer, and autoscaler are independent services. Each has a single responsibility. The healer doesn't know how scheduling works; the scheduler doesn't know about healing.

**Redis list for priority queue** — `lpush` for urgent jobs (front), `rpush` for normal jobs (back). O(1) operations, no polling overhead.

**Weighted load balancing** — node selection uses a scoring function: `score = 0.7 × CPU + 0.3 × latency`. A node with low CPU but high latency loses to one with slightly higher CPU but healthy latency — catching degraded nodes that appear fine on CPU alone.

**Autoscaler cooldown** — a 60-second cooldown between scaling actions prevents thrashing (rapid oscillation between scale up and scale down).

**Docker sync on startup** — the manager syncs `active_nodes` with actually running Docker containers on boot, preventing name conflicts after restarts.

---

## Monitoring

- **Prometheus** — `http://localhost:9090` — scrapes per-node metrics every 15s
- **Grafana** — `http://localhost:3001` — CPU usage, inference latency, jobs processed dashboards
- **Registry API** — `http://localhost:8000/fleet/summary` — live fleet summary
- **Scheduler API** — `http://localhost:8001/docs` — interactive job submission

---

## Project Structure

```
Fleet-OS/
├── registry-service/
│   ├── registry.py
│   └── Dockerfile
├── scheduler-service/
│   ├── scheduler.py
│   ├── healer.py
│   ├── autoscaler.py
│   └── Dockerfile
├── node-agent/
│   ├── agent.py
│   └── Dockerfile
├── docker-manager/
│   └── manager.py
├── dashboard/
│   └── src/
│       ├── App.js
│       └── App.css
├── k8s/
│   └── prometheus.yml
└── render.yaml
```