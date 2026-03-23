# FleetOS 🚀

**A distributed AI inference node fleet management platform** — orchestrating nodes, scheduling jobs, healing itself, and giving you full observability in real time.

---

## Overview

FleetOS is a self-managing platform built to orchestrate a fleet of AI inference nodes. It handles everything from node registration and health monitoring to job scheduling, failure recovery, and live dashboarding — with zero human intervention required.

---

## Features

- **Zero-Touch Node Registration** — Nodes self-register on startup and emit heartbeats every few seconds. Failures are detected within 30 seconds automatically.
- **Priority-Based Job Scheduler** — A Redis-backed queue (lpush/rpush) distributes inference workloads across healthy nodes using greedy CPU load balancing. Full job lifecycle tracked: `queued → running → completed`.
- **Autonomous Self-Healing** — Detects orphaned jobs on dead nodes and requeues them automatically. End-to-end recovery in under 30 seconds, no human intervention needed.
- **Observability Stack** — Prometheus + Grafana scrape per-node metrics (CPU, latency, job throughput) every 15 seconds across the entire fleet.
- **Live React Dashboard** — Real-time node health cards, CPU/latency time-series graphs, fleet health pie chart, priority job submission, and an activity log — auto-refreshing every 3 seconds.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  React Dashboard                │
│   Health Cards │ Charts │ Job Submission │ Logs │
└────────────────────────┬────────────────────────┘
                         │
┌────────────────────────▼────────────────────────┐
│               Fleet Manager (API)               │
│   Node Registry │ Heartbeat Monitor │ Scheduler │
└──────┬──────────────────────────┬───────────────┘
       │                          │
┌──────▼──────┐          ┌────────▼────────┐
│    Redis    │          │  Inference Nodes │
│  Job Queue  │          │  (6x Docker)     │
└─────────────┘          └─────────────────┘
                         │
              ┌──────────▼──────────┐
              │ Prometheus + Grafana │
              │  Metrics & Alerts    │
              └─────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Nodes | Docker (6 simulated inference nodes) |
| Queue | Redis (lpush / rpush) |
| Observability | Prometheus + Grafana |
| Dashboard | React |
| Scheduling | Greedy CPU load balancing |

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Node.js (for the React dashboard)
- Redis
- Prometheus + Grafana

### Running the Fleet

```bash
# Clone the repo
git clone https://github.com/your-username/fleetos.git
cd fleetos

# Start all nodes and services
docker-compose up --build

# Start the dashboard
cd dashboard
npm install
npm start
```

The dashboard will be available at `http://localhost:3000`.

---

## How It Works

### Node Registration
Each inference node registers itself with the Fleet Manager on startup and sends periodic heartbeats. If a node misses heartbeats for 30 seconds, it is marked as dead.

### Job Scheduling
Jobs are submitted with a priority level and pushed into a Redis queue. The scheduler polls the queue and assigns jobs to the healthy node with the lowest current CPU load.

### Self-Healing
A background service continuously monitors for orphaned jobs — jobs assigned to nodes that have since died. These jobs are automatically requeued and reassigned to a healthy node, achieving full recovery in under 30 seconds.

### Observability
Prometheus scrapes CPU usage, inference latency, and job throughput from each node every 15 seconds. Grafana visualizes these metrics in real time.

---

## Dashboard

The React dashboard provides:
- **Node Health Cards** — live status for each of the 6 nodes
- **Time-Series Graphs** — CPU usage and latency per node
- **Fleet Health Pie Chart** — healthy vs. dead node ratio
- **Job Submission Panel** — submit jobs with custom priority levels
- **Activity Log** — real-time narration of system events

Auto-refreshes every **3 seconds**.

---

## License

MIT
