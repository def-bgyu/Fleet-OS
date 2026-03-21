import os
import time
import random
import requests
import numpy as np
from prometheus_client import start_http_server, Gauge
import threading

# --- Config ---
NODE_ID = os.environ.get("NODE_ID", "node-001")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
HEARTBEAT_INTERVAL = 10  # seconds

# --- Prometheus Metrics ---
cpu_usage = Gauge("node_cpu_usage", "Simulated CPU usage", ["node_id"])
inference_latency = Gauge("node_inference_latency_ms", "Simulated inference latency", ["node_id"])
job_count = Gauge("node_job_count", "Number of jobs processed", ["node_id"])

# --- Simulated Inference Workload ---
def run_inference():
    """Simulate an AI inference workload using matrix multiplication."""
    size = random.randint(128, 512)
    a = np.random.rand(size, size)
    b = np.random.rand(size, size)
    start = time.time()
    _ = np.dot(a, b)
    latency = (time.time() - start) * 1000  # ms
    return latency

# --- Register with Registry ---
def register():
    payload = {
        "node_id": NODE_ID,
        "status": "healthy",
        "cpu": random.uniform(10, 40),
        "model_version": "v1.0",
        "jobs_processed": 0
    }
    try:
        response = requests.post(f"{REGISTRY_URL}/register", json=payload)
        if response.status_code == 200:
            print(f"[{NODE_ID}] Registered successfully")
        else:
            print(f"[{NODE_ID}] Registration failed: {response.status_code}")
    except Exception as e:
        print(f"[{NODE_ID}] Could not reach registry: {e}")

# --- Heartbeat Loop ---
def heartbeat_loop():
    jobs = 0
    while True:
        latency = run_inference()
        cpu = random.uniform(20, 85)
        jobs += 1

        # Update prometheus metrics
        cpu_usage.labels(node_id=NODE_ID).set(cpu)
        inference_latency.labels(node_id=NODE_ID).set(latency)
        job_count.labels(node_id=NODE_ID).set(jobs)

        # Send heartbeat to registry
        payload = {
            "node_id": NODE_ID,
            "status": "healthy",
            "cpu": cpu,
            "inference_latency_ms": latency,
            "jobs_processed": jobs,
            "model_version": "v1.0"
        }
        try:
            requests.post(f"{REGISTRY_URL}/heartbeat", json=payload)
            print(f"[{NODE_ID}] Heartbeat sent — CPU: {cpu:.1f}% | Latency: {latency:.1f}ms | Jobs: {jobs}")
        except Exception as e:
            print(f"[{NODE_ID}] Heartbeat failed: {e}")

        time.sleep(HEARTBEAT_INTERVAL)

# --- Main ---
if __name__ == "__main__":
    # Start prometheus metrics server on port 9100
    start_http_server(9100)
    print(f"[{NODE_ID}] Starting up...")
    
    # Register with registry
    register()
    
    # Start heartbeat in background
    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    
    # Keep alive
    while True:
        time.sleep(1)