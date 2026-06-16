import os
import time
import json
import uuid
import threading
import redis
import requests
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import uvicorn

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
SCHEDULER_INTERVAL = 5

# --- Redis ---
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)

# --- FastAPI ---
app = FastAPI(title="FleetOS Scheduler")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429, content={"error": "Rate limit exceeded"}
))
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class JobRequest(BaseModel):
    job_type: str
    priority: int = 1
    payload: dict = {}

# --- Session validation ---
def validate_session(session_id: str):
    raw = r.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=403, detail="Invalid or expired session")
    return json.loads(raw)

# --- Helpers ---
def job_queue_key(session_id: str):
    return f"{session_id}:job_queue"

def get_healthy_nodes(session_id: str):
    try:
        response = requests.get(
            f"{REGISTRY_URL}/nodes",
            headers={"x-session-token": session_id}
        )
        nodes = response.json().get("nodes", [])
        return [n for n in nodes if n.get("status") == "healthy"]
    except Exception as e:
        print(f"[Scheduler] Could not reach registry: {e}")
        return []

def pick_best_node(nodes):
    if not nodes:
        return None
    def score(node):
        cpu_score = node.get("cpu", 100) / 100
        latency_score = min(node.get("inference_latency_ms", 100) / 100, 1)
        return (0.7 * cpu_score) + (0.3 * latency_score)
    best = min(nodes, key=score)
    print(f"[Scheduler] Scores: { {n['node_id']: round(score(n), 3) for n in nodes} }")
    return best

def save_job(session_id: str, job: dict):
    r.set(f"job:{session_id}:{job['job_id']}", json.dumps(job))

def get_job(session_id: str, job_id: str):
    raw = r.get(f"job:{session_id}:{job_id}")
    return json.loads(raw) if raw else None

def get_all_jobs(session_id: str):
    keys = r.keys(f"job:{session_id}:*")
    jobs = []
    for key in keys:
        raw = r.get(key)
        if raw:
            jobs.append(json.loads(raw))
    return jobs

# --- Routes ---
@app.post("/jobs/submit")
@limiter.limit("20/minute")
def submit_job(job_request: JobRequest, request: Request, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    job = {
        "job_id": str(uuid.uuid4())[:8],
        "session_id": x_session_token,
        "job_type": job_request.job_type,
        "priority": job_request.priority,
        "payload": job_request.payload,
        "status": "queued",
        "assigned_node": None,
        "submitted_at": time.time(),
        "started_at": None,
        "completed_at": None
    }
    queue_key = job_queue_key(x_session_token)
    if job_request.priority >= 2:
        r.lpush(queue_key, json.dumps(job))
        print(f"[Scheduler] High priority job {job['job_id']} → front of queue (session: {x_session_token[:8]})")
    else:
        r.rpush(queue_key, json.dumps(job))
        print(f"[Scheduler] Job {job['job_id']} queued (session: {x_session_token[:8]})")
    save_job(x_session_token, job)
    return {"job_id": job["job_id"], "status": "queued"}

@app.get("/jobs")
def list_jobs(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    return {"jobs": get_all_jobs(x_session_token)}

@app.get("/jobs/{job_id}")
def get_job_status(job_id: str, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    job = get_job(x_session_token, job_id)
    if not job:
        return {"error": f"Job {job_id} not found"}
    return job

@app.get("/queue/length")
def queue_length(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    length = r.llen(job_queue_key(x_session_token))
    return {"jobs_waiting": length}

# --- Scheduler Loop ---
def scheduler_loop():
    print("[Scheduler] Scheduler loop started...")
    while True:
        time.sleep(SCHEDULER_INTERVAL)
        # Find all active session queues
        session_keys = r.keys("session:*")
        for skey in session_keys:
            raw = r.get(skey)
            if not raw:
                continue
            session = json.loads(raw)
            session_id = session["session_id"]
            queue_key = job_queue_key(session_id)

            if r.llen(queue_key) == 0:
                continue

            healthy_nodes = get_healthy_nodes(session_id)
            if not healthy_nodes:
                continue

            for _ in healthy_nodes:
                raw_job = r.lpop(queue_key)
                if not raw_job:
                    break
                job = json.loads(raw_job)
                best_node = pick_best_node(healthy_nodes)
                job["status"] = "running"
                job["assigned_node"] = best_node["node_id"]
                job["started_at"] = time.time()
                save_job(session_id, job)
                print(f"[Scheduler] Job {job['job_id']} → {best_node['node_id']} (CPU: {best_node['cpu']:.1f}%)")

                def complete_job(j, sid):
                    time.sleep(20)
                    j["status"] = "completed"
                    j["completed_at"] = time.time()
                    save_job(sid, j)
                    print(f"[Scheduler] Job {j['job_id']} completed on {j['assigned_node']}")

                threading.Thread(target=complete_job, args=(job.copy(), session_id), daemon=True).start()

# --- Main ---
if __name__ == "__main__":
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    print("[Scheduler] Starting FleetOS Scheduler on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
