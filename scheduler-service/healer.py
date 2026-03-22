import os
import time
import json
import threading
import redis
import requests

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
SCHEDULER_URL = os.environ.get("SCHEDULER_URL", "http://localhost:8001")
HEALER_INTERVAL = 15  # seconds — how often we scan for dead nodes
JOB_QUEUE_KEY = "cityfleet:job_queue"

# --- Redis Connection ---
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Helper Functions ---
def get_dead_nodes():
    """Ask registry for all dead nodes."""
    try:
        response = requests.get(f"{REGISTRY_URL}/nodes")
        nodes = response.json().get("nodes", [])
        return [n for n in nodes if n.get("status") == "dead"]
    except Exception as e:
        print(f"[Healer] Could not reach registry: {e}")
        return []

def get_orphaned_jobs(node_id: str):
    """Find all jobs that were running on a dead node."""
    keys = r.keys("job:*")
    orphaned = []
    for key in keys:
        raw = r.get(key)
        if raw:
            job = json.loads(raw)
            if job.get("assigned_node") == node_id and job.get("status") == "running":
                orphaned.append(job)
    return orphaned

def requeue_job(job: dict):
    """Put a job back in the queue for rescheduling."""
    job["status"] = "queued"
    job["assigned_node"] = None
    job["started_at"] = None

    # Save updated status to Redis
    r.set(f"job:{job['job_id']}", json.dumps(job))

    # Push back to front of queue — orphaned jobs are urgent
    r.lpush(JOB_QUEUE_KEY, json.dumps(job))
    print(f"[Healer] 🔄 Job {job['job_id']} requeued — was running on dead node")

def mark_node_recovering(node_id: str):
    """Mark a dead node as 'recovering' so we don't requeue its jobs twice."""
    key = f"node:{node_id}"
    raw = r.get(key)
    if raw:
        node = json.loads(raw)
        node["status"] = "recovering"
        r.set(key, json.dumps(node))

# --- Self Healing Loop ---
def healing_loop():
    """
    Background loop — scans for dead nodes every 15 seconds.
    Finds their orphaned jobs and requeues them.
    """
    # Track which nodes we've already healed
    healed_nodes = set()

    print("[Healer] Self-healing service started...")
    while True:
        time.sleep(HEALER_INTERVAL)

        dead_nodes = get_dead_nodes()
        if not dead_nodes:
            continue

        for node in dead_nodes:
            node_id = node["node_id"]

            # Skip if we've already handled this node
            if node_id in healed_nodes:
                continue

            print(f"[Healer] 💀 Dead node detected: {node_id} — scanning for orphaned jobs...")

            # Find jobs that were running on this node
            orphaned_jobs = get_orphaned_jobs(node_id)

            if not orphaned_jobs:
                print(f"[Healer] No orphaned jobs found for {node_id}")
            else:
                print(f"[Healer] Found {len(orphaned_jobs)} orphaned job(s) on {node_id} — requeuing...")
                for job in orphaned_jobs:
                    requeue_job(job)

            # Mark node as recovering so we don't process it again
            mark_node_recovering(node_id)
            healed_nodes.add(node_id)
            print(f"[Healer] ✅ Node {node_id} recovery complete")

# --- Main ---
if __name__ == "__main__":
    thread = threading.Thread(target=healing_loop, daemon=True)
    thread.start()
    print("[Healer] Starting FleetOS Self-Healer...")

    # Keep alive
    while True:
        time.sleep(1)