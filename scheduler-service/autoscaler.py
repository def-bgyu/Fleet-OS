import os
import time
import requests

# --- Config ---
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
MANAGER_URL = os.environ.get("MANAGER_URL", "http://localhost:8002")
SCALE_CHECK_INTERVAL = 30  # seconds
SCALE_UP_THRESHOLD = 70    # avg CPU % above this → add node
SCALE_DOWN_THRESHOLD = 30  # avg CPU % below this → remove node
MIN_NODES = 2
MAX_NODES = 6

# --- Cooldown tracking ---
# Prevent rapid scaling up/down — wait 60s between scaling actions
last_scale_time = 0
COOLDOWN_PERIOD = 60  # seconds

def get_fleet_summary():
    """Get current fleet state from registry."""
    try:
        response = requests.get(f"{REGISTRY_URL}/fleet/summary")
        return response.json()
    except Exception as e:
        print(f"[Autoscaler] Could not reach registry: {e}")
        return None

def get_managed_nodes():
    """Get list of nodes managed by docker manager."""
    try:
        response = requests.get(f"{MANAGER_URL}/nodes")
        return response.json().get("nodes", {})
    except Exception as e:
        print(f"[Autoscaler] Could not reach manager: {e}")
        return {}

def scale_up():
    """Add a new node to the fleet."""
    try:
        response = requests.post(f"{MANAGER_URL}/nodes/add")
        data = response.json()
        if data.get("error"):
            print(f"[Autoscaler] Scale up failed: {data['error']}")
            return False
        print(f"[Autoscaler] ✅ Scaled UP — added {data.get('node_id')}")
        return True
    except Exception as e:
        print(f"[Autoscaler] Scale up error: {e}")
        return False

def scale_down(nodes: dict):
    """Remove the node with lowest CPU — least useful node."""
    try:
        # Ask registry for healthy nodes and pick lowest CPU one
        response = requests.get(f"{REGISTRY_URL}/nodes")
        all_nodes = response.json().get("nodes", [])
        healthy = [n for n in all_nodes if n.get("status") == "healthy"]

        if not healthy:
            print("[Autoscaler] No healthy nodes to remove")
            return False

        # Pick node with lowest CPU — least busy
        target = min(healthy, key=lambda n: n.get("cpu", 100))
        node_id = target["node_id"]

        response = requests.post(f"{MANAGER_URL}/nodes/{node_id}/kill")
        data = response.json()
        if data.get("error"):
            print(f"[Autoscaler] Scale down failed: {data['error']}")
            return False
        print(f"[Autoscaler] 📉 Scaled DOWN — removed {node_id} (CPU was {target['cpu']:.1f}%)")
        return True
    except Exception as e:
        print(f"[Autoscaler] Scale down error: {e}")
        return False

def autoscaler_loop():
    global last_scale_time

    print("[Autoscaler] Starting FleetOS Autoscaler...")
    print(f"[Autoscaler] Thresholds: scale up >{SCALE_UP_THRESHOLD}% CPU, scale down <{SCALE_DOWN_THRESHOLD}% CPU")
    print(f"[Autoscaler] Limits: min {MIN_NODES} nodes, max {MAX_NODES} nodes")

    while True:
        time.sleep(SCALE_CHECK_INTERVAL)

        summary = get_fleet_summary()
        if not summary:
            continue

        avg_cpu = summary.get("avg_cpu", 0)
        healthy_count = summary.get("healthy", 0)
        now = time.time()

        print(f"[Autoscaler] Fleet status — avg CPU: {avg_cpu:.1f}% | healthy nodes: {healthy_count}")

        # Check cooldown
        if now - last_scale_time < COOLDOWN_PERIOD:
            remaining = int(COOLDOWN_PERIOD - (now - last_scale_time))
            print(f"[Autoscaler] Cooldown active — {remaining}s remaining")
            continue

        # Scale up decision
        if avg_cpu > SCALE_UP_THRESHOLD and healthy_count < MAX_NODES:
            print(f"[Autoscaler] 🔴 High load detected ({avg_cpu:.1f}% CPU) — scaling UP")
            if scale_up():
                last_scale_time = now

        # Scale down decision
        elif avg_cpu < SCALE_DOWN_THRESHOLD and healthy_count > MIN_NODES:
            print(f"[Autoscaler] 🟢 Low load detected ({avg_cpu:.1f}% CPU) — scaling DOWN")
            nodes = get_managed_nodes()
            if scale_down(nodes):
                last_scale_time = now

        else:
            print(f"[Autoscaler] ✅ Fleet is balanced — no scaling needed")

if __name__ == "__main__":
    autoscaler_loop()