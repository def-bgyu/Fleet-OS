import os
import time
import json
import threading
import redis
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
DEAD_NODE_THRESHOLD = 30  # seconds — if no heartbeat in 30s, node is dead
HEALTH_CHECK_INTERVAL = 15  # seconds — how often we scan for dead nodes

# --- FastAPI App ---
app = FastAPI(title="FleetOS Registry")

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
class NodeRegistration(BaseModel):
    node_id: str
    status: str
    cpu: float
    model_version: str
    jobs_processed: int

class Heartbeat(BaseModel):
    node_id: str
    status: str
    cpu: float
    inference_latency_ms: float
    jobs_processed: int
    model_version: str

# --- Helper Functions ---
def save_node(node_id: str, data: dict):
    """Save node data to Redis."""
    data["last_seen"] = time.time()
    r.set(f"node:{node_id}", json.dumps(data))

def get_node(node_id: str):
    """Get node data from Redis."""
    raw = r.get(f"node:{node_id}")
    return json.loads(raw) if raw else None

def get_all_nodes():
    """Get all nodes from Redis."""
    keys = r.keys("node:*")
    nodes = []
    for key in keys:
        raw = r.get(key)
        if raw:
            nodes.append(json.loads(raw))
    return nodes

# --- API Routes ---
@app.post("/register")
def register_node(node: NodeRegistration):
    """Called by a node when it boots up."""
    data = node.dict()
    data["status"] = "starting"  # NEW — node starts in 'starting' state
    save_node(node.node_id, data)
    print(f"[Registry] Node registered: {node.node_id} — status: starting")
    return {"message": f"{node.node_id} registered successfully"}

@app.post("/heartbeat")
def receive_heartbeat(heartbeat: Heartbeat):
    """Called by a node every 10 seconds."""
    data = heartbeat.dict()
    data["status"] = "healthy"
    save_node(heartbeat.node_id, data)
    print(f"[Registry] Heartbeat from {heartbeat.node_id} — CPU: {heartbeat.cpu:.1f}%")
    return {"message": "heartbeat received"}

@app.get("/nodes")
def get_nodes():
    """Return status of all nodes in the fleet."""
    return {"nodes": get_all_nodes()}

@app.get("/nodes/{node_id}")
def get_single_node(node_id: str):
    """Return status of a single node."""
    node = get_node(node_id)
    if not node:
        return {"error": f"{node_id} not found"}
    return node

@app.get("/fleet/summary")
def fleet_summary():
    """Return a high level summary of the fleet."""
    nodes = get_all_nodes()
    healthy = [n for n in nodes if n.get("status") == "healthy"]
    dead = [n for n in nodes if n.get("status") == "dead"]
    return {
        "total_nodes": len(nodes),
        "healthy": len(healthy),
        "dead": len(dead),
        "avg_cpu": round(sum(n.get("cpu", 0) for n in healthy) / max(len(healthy), 1), 2),
        "avg_latency_ms": round(sum(n.get("inference_latency_ms", 0) for n in healthy) / max(len(healthy), 1), 2)
    }

@app.post("/fleet/clear-dead")
def clear_dead_nodes():
    """Remove all dead nodes from the registry."""
    nodes = get_all_nodes()
    cleared = 0
    for node in nodes:
        if node.get("status") in ["dead", "recovering"]:
            r.delete(f"node:{node['node_id']}")
            cleared += 1
    print(f"[Registry] Cleared {cleared} dead nodes from registry")
    return {"message": f"Cleared {cleared} dead nodes"}

# --- Dead Node Detection ---
def health_check_loop():
    """Background thread — scans for dead nodes every 15 seconds."""
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        now = time.time()
        nodes = get_all_nodes()
        for node in nodes:
            last_seen = node.get("last_seen", 0)
            if now - last_seen > DEAD_NODE_THRESHOLD:
                node["status"] = "dead"
                save_node(node["node_id"], node)
                print(f"[Registry] ⚠️  Node {node['node_id']} marked as DEAD — no heartbeat for {int(now - last_seen)}s")

# --- Main ---
if __name__ == "__main__":
    # Start dead node detection in background
    thread = threading.Thread(target=health_check_loop, daemon=True)
    thread.start()
    print("[Registry] Starting CityFleet Registry on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)