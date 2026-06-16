import os
import time
import json
import requests
import redis

# --- Config ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
MANAGER_URL = os.environ.get("MANAGER_URL", "http://localhost:8002")
SCALE_CHECK_INTERVAL = 30
SCALE_UP_THRESHOLD = 70
SCALE_DOWN_THRESHOLD = 30
MIN_NODES = 2
MAX_NODES = int(os.environ.get("MAX_NODES_PER_SESSION", "6"))
COOLDOWN_PERIOD = 60

r = redis.from_url(REDIS_URL, decode_responses=True)

# Per-session cooldown tracking
last_scale_time: dict[str, float] = {}

def get_active_sessions():
    keys = r.keys("session:*")
    sessions = []
    for key in keys:
        raw = r.get(key)
        if raw:
            sessions.append(json.loads(raw))
    return sessions

def get_fleet_summary(session_id: str):
    try:
        response = requests.get(
            f"{REGISTRY_URL}/fleet/summary",
            headers={"x-session-token": session_id}
        )
        return response.json()
    except Exception as e:
        print(f"[Autoscaler] Could not reach registry for session {session_id[:8]}: {e}")
        return None

def get_managed_nodes(session_id: str):
    try:
        response = requests.get(
            f"{MANAGER_URL}/nodes",
            headers={"x-session-token": session_id}
        )
        return response.json().get("nodes", {})
    except Exception as e:
        print(f"[Autoscaler] Could not reach manager: {e}")
        return {}

def scale_up(session_id: str):
    try:
        response = requests.post(
            f"{MANAGER_URL}/nodes/add",
            headers={"x-session-token": session_id}
        )
        data = response.json()
        if data.get("error") or response.status_code >= 400:
            print(f"[Autoscaler] Scale up failed: {data}")
            return False
        print(f"[Autoscaler] Scaled UP — added {data.get('node_id')} (session: {session_id[:8]})")
        return True
    except Exception as e:
        print(f"[Autoscaler] Scale up error: {e}")
        return False

def scale_down(session_id: str):
    try:
        response = requests.get(
            f"{REGISTRY_URL}/nodes",
            headers={"x-session-token": session_id}
        )
        all_nodes = response.json().get("nodes", [])
        healthy = [n for n in all_nodes if n.get("status") == "healthy"]
        if not healthy:
            return False
        target = min(healthy, key=lambda n: n.get("cpu", 100))
        node_id = target["node_id"]
        response = requests.post(
            f"{MANAGER_URL}/nodes/{node_id}/kill",
            headers={"x-session-token": session_id}
        )
        data = response.json()
        if data.get("error"):
            print(f"[Autoscaler] Scale down failed: {data['error']}")
            return False
        print(f"[Autoscaler] Scaled DOWN — removed {node_id} (session: {session_id[:8]})")
        return True
    except Exception as e:
        print(f"[Autoscaler] Scale down error: {e}")
        return False

def autoscaler_loop():
    print("[Autoscaler] Starting FleetOS Autoscaler...")
    while True:
        time.sleep(SCALE_CHECK_INTERVAL)
        sessions = get_active_sessions()

        for session in sessions:
            session_id = session["session_id"]
            summary = get_fleet_summary(session_id)
            if not summary:
                continue

            avg_cpu = summary.get("avg_cpu", 0)
            healthy_count = summary.get("healthy", 0)
            now = time.time()

            if now - last_scale_time.get(session_id, 0) < COOLDOWN_PERIOD:
                continue

            if avg_cpu > SCALE_UP_THRESHOLD and healthy_count < MAX_NODES:
                print(f"[Autoscaler] High load ({avg_cpu:.1f}%) on session {session_id[:8]} — scaling UP")
                if scale_up(session_id):
                    last_scale_time[session_id] = now
            elif avg_cpu < SCALE_DOWN_THRESHOLD and healthy_count > MIN_NODES:
                print(f"[Autoscaler] Low load ({avg_cpu:.1f}%) on session {session_id[:8]} — scaling DOWN")
                if scale_down(session_id):
                    last_scale_time[session_id] = now

if __name__ == "__main__":
    autoscaler_loop()
