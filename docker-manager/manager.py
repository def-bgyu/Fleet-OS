import os
import time
import docker
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="FleetOS Docker Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = docker.from_env()

REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://host.docker.internal:8000")
MAX_NODES = 8

# Track which nodes we've created
active_nodes = {}

def get_next_node_id():
    """Generate next available node ID."""
    existing = set(active_nodes.keys())
    for i in range(1, MAX_NODES + 1):
        node_id = f"node-{str(i).zfill(3)}"
        if node_id not in existing:
            return node_id
    return None

def get_next_port():
    """Get next available metrics port."""
    used_ports = {v['port'] for v in active_nodes.values()}
    for port in range(9110, 9118):
        if port not in used_ports:
            return port
    return None

@app.post("/nodes/add")
def add_node():
    """Spin up a new node container."""
    if len(active_nodes) >= MAX_NODES:
        return {"error": f"Maximum {MAX_NODES} nodes reached"}

    node_id = get_next_node_id()
    port = get_next_port()

    if not node_id or not port:
        return {"error": "No available node slots"}

    try:
        container = client.containers.run(
            "fleetos-node",
            detach=True,
            name=f"fleetos-{node_id}",
            environment={
                "NODE_ID": node_id,
                "REGISTRY_URL": "http://host.docker.internal:8000",
                "METRICS_PORT": str(port)
            },
            ports={f"{port}/tcp": port}
        )

        active_nodes[node_id] = {
            "container_id": container.id[:12],
            "port": port,
            "status": "running"
        }

        print(f"[Manager] ✅ Started {node_id} (container: {container.id[:12]})")
        return {
            "message": f"{node_id} started successfully",
            "node_id": node_id,
            "container_id": container.id[:12]
        }

    except Exception as e:
        print(f"[Manager] ❌ Failed to start node: {e}")
        return {"error": str(e)}

@app.post("/nodes/{node_id}/kill")
def kill_node(node_id: str):
    """Kill a node container."""
    if node_id not in active_nodes:
        return {"error": f"{node_id} not found"}

    try:
        container = client.containers.get(f"fleetos-{node_id}")
        container.kill()
        del active_nodes[node_id]
        print(f"[Manager] 💀 Killed {node_id}")
        return {"message": f"{node_id} killed successfully"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/nodes/{node_id}/restart")
def restart_node(node_id: str):
    """Restart a killed node container."""
    if node_id not in active_nodes:
        return {"error": f"{node_id} not found"}

    try:
        container = client.containers.get(f"fleetos-{node_id}")
        container.restart()
        active_nodes[node_id]["status"] = "running"
        print(f"[Manager] 🔄 Restarted {node_id}")
        return {"message": f"{node_id} restarted successfully"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/nodes")
def list_managed_nodes():
    """List all nodes managed by this service."""
    return {"nodes": active_nodes}

if __name__ == "__main__":
    # On startup, sync active_nodes with actually running Docker containers
    print("[Manager] Syncing with existing Docker containers...")
    try:
        for container in client.containers.list():
            if container.name.startswith("fleetos-node-"):
                node_id = container.name.replace("fleetos-", "")
                # Figure out which port it's using
                ports = container.ports
                port = 9110  # default
                for container_port, host_bindings in ports.items():
                    if host_bindings:
                        port = int(host_bindings[0]['HostPort'])
                        break
                active_nodes[node_id] = {
                    "container_id": container.id[:12],
                    "port": port,
                    "status": "running"
                }
                print(f"[Manager] Synced existing container: {node_id}")
    except Exception as e:
        print(f"[Manager] Sync error: {e}")

    print(f"[Manager] Found {len(active_nodes)} existing nodes")
    print("[Manager] Starting FleetOS Docker Manager on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)