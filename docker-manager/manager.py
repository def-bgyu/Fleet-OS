import os
import time
import json
import docker
import redis
import requests
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
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
MAX_NODES_PER_SESSION = int(os.environ.get("MAX_NODES_PER_SESSION", "6"))

# --- Clients ---
docker_client = docker.from_env()
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)

# --- FastAPI ---
app = FastAPI(title="FleetOS Docker Manager")
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

# session_id -> { node_id -> { container_id, port, status } }
# Backed by Redis so manager restarts don't lose state
def load_active_nodes() -> dict:
    for attempt in range(10):
        try:
            raw = r.get("manager:active_nodes")
            return json.loads(raw) if raw else {}
        except Exception as e:
            print(f"[Manager] Redis not ready, retrying ({attempt+1}/10)... {e}")
            time.sleep(3)
    print("[Manager] Could not connect to Redis after retries — starting with empty state")
    return {}

def persist_active_nodes():
    try:
        r.set("manager:active_nodes", json.dumps(active_nodes))
    except Exception as e:
        print(f"[Manager] Could not persist active_nodes: {e}")

active_nodes: dict = load_active_nodes()

# --- Session validation ---
def validate_session(session_id: str):
    raw = r.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=403, detail="Invalid or expired session")
    return json.loads(raw)

def get_session_nodes(session_id: str) -> dict:
    return active_nodes.get(session_id, {})

def get_next_node_id(session_id: str) -> str | None:
    existing = set(get_session_nodes(session_id).keys())
    for i in range(1, MAX_NODES_PER_SESSION + 1):
        node_id = f"node-{str(i).zfill(3)}"
        if node_id not in existing:
            return node_id
    return None

def get_next_port() -> int | None:
    # Check ports actually bound by running Docker containers, not just in-memory state
    used_ports = set()
    try:
        for container in docker_client.containers.list():
            for bindings in container.ports.values():
                if bindings:
                    for b in bindings:
                        used_ports.add(int(b["HostPort"]))
    except Exception:
        pass
    # Also include in-memory tracked ports as a safety net
    for session_nodes in active_nodes.values():
        for node_data in session_nodes.values():
            used_ports.add(node_data["port"])
    for port in range(9110, 9110 + 50):
        if port not in used_ports:
            return port
    return None

# --- Routes ---
@app.post("/nodes/add")
@limiter.limit("10/minute")
def add_node(request: Request, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    session_nodes = get_session_nodes(x_session_token)

    if len(session_nodes) >= MAX_NODES_PER_SESSION:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_NODES_PER_SESSION} nodes per session reached"
        )

    node_id = get_next_node_id(x_session_token)
    port = get_next_port()

    if not node_id or not port:
        raise HTTPException(status_code=500, detail="No available node slots")

    # Scoped container name: session prefix + node id
    session_prefix = x_session_token[:8]
    container_name = f"fleetos-{session_prefix}-{node_id}"

    try:
        # Remove any existing container with this name (e.g. from a previous recovering state)
        try:
            old = docker_client.containers.get(container_name)
            old.remove(force=True)
            print(f"[Manager] Removed stale container {container_name} before recreating")
        except docker.errors.NotFound:
            pass

        container = docker_client.containers.run(
            "fleetos-node",
            detach=True,
            name=container_name,
            environment={
                "NODE_ID": node_id,
                "SESSION_ID": x_session_token,
                "REGISTRY_URL": os.environ.get("REGISTRY_URL", "http://host.docker.internal:8000"),
                "METRICS_PORT": str(port)
            },
            ports={f"{port}/tcp": port}
        )

        if x_session_token not in active_nodes:
            active_nodes[x_session_token] = {}

        active_nodes[x_session_token][node_id] = {
            "container_id": container.id[:12],
            "container_name": container_name,
            "port": port,
            "status": "running"
        }
        persist_active_nodes()
        print(f"[Manager] Started {node_id} for session {session_prefix} (container: {container.id[:12]})")
        return {
            "message": f"{node_id} started successfully",
            "node_id": node_id,
            "container_id": container.id[:12]
        }

    except Exception as e:
        print(f"[Manager] Failed to start node: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/nodes/{node_id}/kill")
def kill_node(node_id: str, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    session_nodes = get_session_nodes(x_session_token)

    if node_id not in session_nodes:
        raise HTTPException(status_code=404, detail=f"{node_id} not found in your session")

    container_name = session_nodes[node_id]["container_name"]
    try:
        container = docker_client.containers.get(container_name)
        container.kill()
        # Keep slot occupied so name isn't reused and restart is possible
        active_nodes[x_session_token][node_id]["status"] = "killed"
        persist_active_nodes()
        print(f"[Manager] Killed {node_id} (session: {x_session_token[:8]})")
        return {"message": f"{node_id} killed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/nodes/{node_id}/restart")
def restart_node(node_id: str, x_session_token: str = Header(...)):
    validate_session(x_session_token)
    session_nodes = get_session_nodes(x_session_token)

    if node_id not in session_nodes:
        raise HTTPException(status_code=404, detail=f"{node_id} not found in your session")

    container_name = session_nodes[node_id]["container_name"]
    try:
        container = docker_client.containers.get(container_name)
        container.restart()
        active_nodes[x_session_token][node_id]["status"] = "running"
        persist_active_nodes()
        print(f"[Manager] Restarted {node_id} (session: {x_session_token[:8]})")
        return {"message": f"{node_id} restarted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/nodes/{node_id}/remove")
def remove_node(node_id: str, x_session_token: str = Header(...)):
    """Permanently remove a node — frees the slot so a new node can take its place."""
    validate_session(x_session_token)
    session_nodes = get_session_nodes(x_session_token)

    if node_id not in session_nodes:
        raise HTTPException(status_code=404, detail=f"{node_id} not found in your session")

    container_name = session_nodes[node_id]["container_name"]
    try:
        container = docker_client.containers.get(container_name)
        container.remove(force=True)
    except docker.errors.NotFound:
        pass  # already gone, still free the slot
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    del active_nodes[x_session_token][node_id]
    persist_active_nodes()

    # Remove from registry so the slot is fully freed
    try:
        requests.delete(
            f"{REGISTRY_URL}/nodes/{node_id}",
            headers={"x-session-token": x_session_token}
        )
    except Exception as e:
        print(f"[Manager] Could not remove {node_id} from registry: {e}")

    print(f"[Manager] Removed {node_id} (session: {x_session_token[:8]}) — slot freed")
    return {"message": f"{node_id} removed — slot available"}

@app.get("/nodes")
def list_managed_nodes(x_session_token: str = Header(...)):
    validate_session(x_session_token)
    return {"nodes": get_session_nodes(x_session_token)}

# --- Main ---
if __name__ == "__main__":
    # Sync existing fleetos containers on startup
    print("[Manager] Syncing with existing Docker containers...")
    try:
        for container in docker_client.containers.list():
            if container.name.startswith("fleetos-") and len(container.name.split("-")) >= 3:
                parts = container.name.split("-")
                # Expected format: fleetos-{session_prefix}-node-{num}
                if len(parts) == 4 and parts[2] == "node":
                    session_prefix = parts[1]
                    node_id = f"node-{parts[3]}"
                    port = 9110
                    for cp, hb in container.ports.items():
                        if hb:
                            port = int(hb[0]["HostPort"])
                            break
                    # We don't have full session ID from prefix alone — skip auto-sync
                    # Containers will be cleaned up naturally via session expiry
                    print(f"[Manager] Found existing container: {container.name} (manual cleanup may be needed)")
    except Exception as e:
        print(f"[Manager] Sync error: {e}")

    print("[Manager] Starting FleetOS Docker Manager on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)
