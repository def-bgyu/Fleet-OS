import os
import time
import json
import threading
import redis
import requests

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
HEALER_INTERVAL = 15

r = redis.from_url(REDIS_URL, decode_responses=True)

def get_active_sessions():
    keys = r.keys("session:*")
    sessions = []
    for key in keys:
        raw = r.get(key)
        if raw:
            sessions.append(json.loads(raw))
    return sessions

def get_dead_nodes(session_id: str):
    keys = r.keys(f"node:{session_id}:*")
    dead = []
    for key in keys:
        raw = r.get(key)
        if raw:
            node = json.loads(raw)
            if node.get("status") == "dead":
                dead.append(node)
    return dead

def get_orphaned_jobs(session_id: str, node_id: str):
    keys = r.keys(f"job:{session_id}:*")
    orphaned = []
    for key in keys:
        raw = r.get(key)
        if raw:
            job = json.loads(raw)
            if job.get("assigned_node") == node_id and job.get("status") == "running":
                orphaned.append(job)
    return orphaned

def requeue_job(session_id: str, job: dict):
    job["status"] = "queued"
    job["assigned_node"] = None
    job["started_at"] = None
    r.set(f"job:{session_id}:{job['job_id']}", json.dumps(job))
    r.lpush(f"{session_id}:job_queue", json.dumps(job))
    print(f"[Healer] Job {job['job_id']} requeued (session: {session_id[:8]})")

def mark_node_recovering(session_id: str, node_id: str):
    key = f"node:{session_id}:{node_id}"
    raw = r.get(key)
    if raw:
        node = json.loads(raw)
        node["status"] = "recovering"
        r.set(key, json.dumps(node))

def healing_loop():
    healed = set()  # track (session_id, node_id) pairs already healed
    print("[Healer] Self-healing service started...")

    while True:
        time.sleep(HEALER_INTERVAL)

        sessions = get_active_sessions()
        for session in sessions:
            session_id = session["session_id"]
            dead_nodes = get_dead_nodes(session_id)

            for node in dead_nodes:
                node_id = node["node_id"]
                key = (session_id, node_id)
                if key in healed:
                    continue

                print(f"[Healer] Dead node: {node_id} (session: {session_id[:8]}) — scanning for orphaned jobs...")
                orphaned = get_orphaned_jobs(session_id, node_id)

                if orphaned:
                    print(f"[Healer] Found {len(orphaned)} orphaned job(s) — requeuing...")
                    for job in orphaned:
                        requeue_job(session_id, job)
                else:
                    print(f"[Healer] No orphaned jobs for {node_id}")

                mark_node_recovering(session_id, node_id)
                healed.add(key)
                print(f"[Healer] Recovery complete for {node_id}")

if __name__ == "__main__":
    thread = threading.Thread(target=healing_loop, daemon=True)
    thread.start()
    print("[Healer] Starting FleetOS Self-Healer...")
    while True:
        time.sleep(1)
