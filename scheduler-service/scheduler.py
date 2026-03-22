import os
import time
import json
import uuid
import threading
import redis
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
JOB_QUEUE_KEY = "cityfleet:job_queue"
SCHEDULER_INTERVAL = 5  # seconds — how often scheduler checks the queue

# --- FastAPI App ---
app = FastAPI(title="CityFleet Scheduler")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Redis Connection ---
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Data Models ---
class JobRequest(BaseModel):
    job_type: str  # e.g. "inference", "evaluation", "simulation"
    priority: int = 1  # 1 = normal, 2 = high, 3 = urgent
    payload: dict = {}

# --- Helper Functions ---
def get_healthy_nodes():
    """Ask the registry for all healthy nodes."""
    try:
        response = requests.get(f"{REGISTRY_URL}/nodes")
        nodes = response.json().get("nodes", [])
        return [n for n in nodes if n.get("status") == "healthy"]
    except Exception as e:
        print(f"[Scheduler] Could not reach registry: {e}")
        return []

def pick_best_node(nodes):
    """Pick the node with the lowest CPU usage — load balancing."""
    if not nodes:
        return None
    return min(nodes, key=lambda n: n.get("cpu", 100))

def save_job(job: dict):
    """Save job to Redis."""
    r.set(f"job:{job['job_id']}", json.dumps(job))

def get_job(job_id: str):
    """Get job from Redis."""
    raw = r.get(f"job:{job_id}")
    return json.loads(raw) if raw else None

def get_all_jobs():
    """Get all jobs from Redis."""
    keys = r.keys("job:*")
    jobs = []
    for key in keys:
        raw = r.get(key)
        if raw:
            jobs.append(json.loads(raw))
    return jobs

# --- API Routes ---
@app.post("/jobs/submit")
def submit_job(job_request: JobRequest):
    """Submit a new job to the queue."""
    job = {
        "job_id": str(uuid.uuid4())[:8],
        "job_type": job_request.job_type,
        "priority": job_request.priority,
        "payload": job_request.payload,
        "status": "queued",
        "assigned_node": None,
        "submitted_at": time.time(),
        "started_at": None,
        "completed_at": None
    }

    # Higher priority jobs go to front of queue
    if job_request.priority >= 2:
        r.lpush(JOB_QUEUE_KEY, json.dumps(job))
        print(f"[Scheduler] ⚡ High priority job {job['job_id']} pushed to front of queue")
    else:
        r.rpush(JOB_QUEUE_KEY, json.dumps(job))
        print(f"[Scheduler] Job {job['job_id']} added to queue")

    save_job(job)
    return {"job_id": job["job_id"], "status": "queued"}

@app.get("/jobs")
def list_jobs():
    """Return all jobs and their statuses."""
    return {"jobs": get_all_jobs()}

@app.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Return status of a specific job."""
    job = get_job(job_id)
    if not job:
        return {"error": f"Job {job_id} not found"}
    return job

@app.get("/queue/length")
def queue_length():
    """Return how many jobs are waiting in the queue."""
    length = r.llen(JOB_QUEUE_KEY)
    return {"jobs_waiting": length}

# --- Scheduler Loop ---
def scheduler_loop():
    """
    Core scheduler — runs every 5 seconds.
    Picks jobs from queue and assigns them to the best available node.
    """
    print("[Scheduler] Scheduler loop started...")
    while True:
        time.sleep(SCHEDULER_INTERVAL)

        # Check if there are jobs waiting
        queue_len = r.llen(JOB_QUEUE_KEY)
        if queue_len == 0:
            continue

        print(f"[Scheduler] {queue_len} jobs in queue — finding available nodes...")

        # Get healthy nodes
        healthy_nodes = get_healthy_nodes()
        if not healthy_nodes:
            print("[Scheduler] No healthy nodes available — jobs will wait")
            continue

        # Process as many jobs as we have healthy nodes
        for node in healthy_nodes:
            # Pop next job from queue
            raw_job = r.lpop(JOB_QUEUE_KEY)
            if not raw_job:
                break  # Queue is empty

            job = json.loads(raw_job)

            # Pick best node (lowest CPU)
            best_node = pick_best_node(healthy_nodes)

            # Assign job to node
            job["status"] = "running"
            job["assigned_node"] = best_node["node_id"]
            job["started_at"] = time.time()
            save_job(job)

            print(f"[Scheduler] ✅ Job {job['job_id']} ({job['job_type']}) → {best_node['node_id']} (CPU: {best_node['cpu']:.1f}%)")

            # Simulate job completion after 5 seconds
            def complete_job(j):
                time.sleep(20)
                j["status"] = "completed"
                j["completed_at"] = time.time()
                save_job(j)
                print(f"[Scheduler] 🏁 Job {j['job_id']} completed on {j['assigned_node']}")

            thread = threading.Thread(target=complete_job, args=(job.copy(),), daemon=True)
            thread.start()

# --- Main ---
if __name__ == "__main__":
    # Start scheduler loop in background
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    print("[Scheduler] Starting CityFleet Scheduler on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)