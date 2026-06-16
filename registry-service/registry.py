import os
import time
import json
import threading
import redis
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import uvicorn

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
DEAD_NODE_THRESHOLD = 30
HEALTH_CHECK_INTERVAL = 15

# --- Redis ---
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)

# --- FastAPI ---
app = FastAPI(title="FleetOS Registry")
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

# --- Session validation helper ---
def validate_session(session_id: str):
    """Check session exists in Redis."""
    raw = r.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=403, detail="Invalid or expired session")
    return json.loads(raw)

def touch_session(session_id: str):
    """Update session last_active timestamp."""
    raw = r.get(f"session:{session_id}")
    if raw:
        session = json.loads(raw)
        session["last_active"] = time.time()
        r.set(f"session:{session_id}", json.dumps(session))

# --- Data Models ---
class NodeRegistration(BaseModel):
    node_id: str
    status: str
    cpu: float
    model_version: str
    jobs_processed: int
    session_id: Optional[str] = None

class Heartbeat(BaseModel):
    node_id: str
    status: str
    cpu: float
    inference_latency_ms: float
    jobs_processed: int
    model_version: str
    session_id: Optional[str] = None

# --- Helpers ---
def node_key(session_id: str, node_id: str):
    return f"node:{session_id}:{node_id}"

def save_node(session_id: str, node_id: str, data: dict):
    data["last_seen"] = time.time()
    r.set(node_key(session_id, node_id), json.dumps(data))

def get_node(session_id: str, node_id: str):
    raw = r.get(node_key(session_id, node_id))
    return json.loads(raw) if raw else None

def get_all_nodes(session_id: str):
    keys = r.keys(f"node:{session_id}:*")
    nodes = []
    for key in keys:
        raw = r.get(key)
        if raw:
            nodes.append(json.loads(raw))
    return nodes

# --- Routes ---
@app.post("/register")
@limiter.limit("30/minute")
def register_node(node: NodeRegistration, request: Request):
    if not node.session_id:
        raise HTTPException(status_code=400, detail="session_id required — node must be started via session-aware manager")
    validate_session(node.session_id)
    data = node.dict()
    data["status"] = "starting"
    save_node(node.session_id, node.node_id, data)
    touch_session(node.session_id)
    print(f"[Registry] Node registered: {node.node_id} (session: {node.session_id[:8]})")
    return {"message": f"{node.node_id} registered successfully"}

@app.post("/heartbeat")
@limiter.limit("60/minute")
def receive_heartbeat(heartbeat: Heartbeat, request: Request):
    if not heartbeat.session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    validate_session(heartbeat.session_id)
    data = heartbeat.dict()
    data["status"] = "healthy"
    save_node(heartbeat.session_id, heartbeat.node_id, data)
    touch_session(heartbeat.session_id)
    print(f"[Registry] Heartbeat from {heartbeat.node_id} — CPU: {heartbeat.cpu:.1f}%")
    return {"message": "heartbeat received"}

@app.get("/nodes")
def get_nodes(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    return {"nodes": get_all_nodes(x_session_token)}

@app.get("/nodes/{node_id}")
def get_single_node(node_id: str, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    node = get_node(x_session_token, node_id)
    if not node:
        return {"error": f"{node_id} not found"}
    return node

@app.get("/fleet/summary")
def fleet_summary(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    nodes = get_all_nodes(x_session_token)
    healthy = [n for n in nodes if n.get("status") == "healthy"]
    dead = [n for n in nodes if n.get("status") == "dead"]
    return {
        "total_nodes": len(nodes),
        "healthy": len(healthy),
        "dead": len(dead),
        "avg_cpu": round(sum(n.get("cpu", 0) for n in healthy) / max(len(healthy), 1), 2),
        "avg_latency_ms": round(sum(n.get("inference_latency_ms", 0) for n in healthy) / max(len(healthy), 1), 2)
    }

@app.delete("/nodes/{node_id}")
def delete_node(node_id: str, x_session_token: str = Header(...)):
    """Remove a single node from the registry — called by manager on node removal."""
    validate_session(x_session_token)
    key = node_key(x_session_token, node_id)
    deleted = r.delete(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{node_id} not found")
    print(f"[Registry] Node {node_id} deleted from registry (session: {x_session_token[:8]})")
    return {"message": f"{node_id} removed from registry"}

@app.post("/fleet/clear-dead")
def clear_dead_nodes(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    nodes = get_all_nodes(x_session_token)
    cleared = 0
    for node in nodes:
        if node.get("status") in ["dead", "recovering"]:
            r.delete(node_key(x_session_token, node["node_id"]))
            cleared += 1
    print(f"[Registry] Cleared {cleared} dead nodes for session {x_session_token}")
    return {"message": f"Cleared {cleared} dead nodes"}

# --- Dead Node Detection ---
def health_check_loop():
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        now = time.time()
        keys = r.keys("node:*")
        for key in keys:
            raw = r.get(key)
            if not raw:
                continue
            node = json.loads(raw)
            last_seen = node.get("last_seen", 0)
            if now - last_seen > DEAD_NODE_THRESHOLD and node.get("status") not in ["dead", "recovering"]:
                node["status"] = "dead"
                r.set(key, json.dumps(node))
                print(f"[Registry] Node {node['node_id']} marked DEAD — no heartbeat for {int(now - last_seen)}s")

# --- Main ---
if __name__ == "__main__":
    thread = threading.Thread(target=health_check_loop, daemon=True)
    thread.start()
    print("[Registry] Starting FleetOS Registry on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
