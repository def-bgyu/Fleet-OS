import os
import time
import random
import queue
import threading
import requests
import psutil
from prometheus_client import start_http_server, Gauge, Histogram
from transformers import pipeline

# --- Config ---
NODE_ID = os.environ.get("NODE_ID", "node-001")
SESSION_ID = os.environ.get("SESSION_ID", "")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8000")
HEARTBEAT_INTERVAL = 10
BATCH_WINDOW_MS = 100   # wait up to 100ms to accumulate a batch
MAX_BATCH_SIZE = 8      # maximum requests per forward pass
REQUEST_INTERVAL = 2.0  # seconds between simulated incoming requests (idle-friendly)

# --- Prometheus Metrics ---
cpu_usage = Gauge("node_cpu_usage", "CPU usage %", ["node_id"])
inference_latency = Gauge("node_inference_latency_ms", "Batch inference latency ms", ["node_id"])
job_count = Gauge("node_job_count", "Total requests processed", ["node_id"])
batch_size_gauge = Gauge("node_batch_size", "Requests per forward pass", ["node_id"])
throughput_gauge = Gauge("node_throughput_rps", "Requests per second", ["node_id"])
latency_histogram = Histogram(
    "node_inference_latency_histogram_ms",
    "Inference latency distribution",
    ["node_id"],
    buckets=[5, 10, 25, 50, 100, 200, 500]
)

# --- Request queue for dynamic batching ---
request_queue: queue.Queue = queue.Queue()

# Sample texts to run sentiment classification on
SAMPLE_TEXTS = [
    "The model achieved state-of-the-art performance on the benchmark.",
    "Inference latency increased significantly under high load.",
    "The GPU cluster was fully utilized during peak hours.",
    "Batch processing reduced per-request overhead substantially.",
    "The deployment pipeline completed without errors.",
    "Throughput degraded after the memory threshold was exceeded.",
    "The quantized model maintained accuracy with lower resource usage.",
    "Request queuing introduced unacceptable tail latency.",
]

# --- Load model once at startup ---
print(f"[{NODE_ID}] Loading distilbert model...")
classifier = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english",
    device=-1  # CPU
)
print(f"[{NODE_ID}] Model loaded.")

# --- Dynamic Batching Engine ---
def batching_loop(total_requests: list, latency_tracker: list):
    """
    Collects incoming requests for up to BATCH_WINDOW_MS, then runs
    them as a single batched forward pass through the model.
    """
    while True:
        batch = []
        deadline = time.time() + (BATCH_WINDOW_MS / 1000)

        # Collect requests until batch is full or window closes
        while time.time() < deadline and len(batch) < MAX_BATCH_SIZE:
            try:
                remaining = max(0, deadline - time.time())
                item = request_queue.get(timeout=remaining)
                batch.append(item)
            except queue.Empty:
                break

        if not batch:
            continue

        texts = [item["text"] for item in batch]
        start = time.time()
        results = classifier(texts, truncation=True, max_length=128)
        latency_ms = (time.time() - start) * 1000

        # Per-request latency = batch latency / batch size (amortized)
        per_request_ms = latency_ms / len(batch)

        total_requests[0] += len(batch)
        latency_tracker[0] = latency_ms
        latency_tracker[1] = len(batch)

        latency_histogram.labels(node_id=NODE_ID).observe(per_request_ms)

        print(
            f"[{NODE_ID}] Batch processed — size: {len(batch)} | "
            f"latency: {latency_ms:.1f}ms | per-req: {per_request_ms:.1f}ms | "
            f"labels: {[r['label'] for r in results]}"
        )

def request_producer():
    """
    Simulates incoming inference requests at a controlled rate.
    Bursts 2-4 requests close together every REQUEST_INTERVAL seconds
    so the batching engine has something to group.
    """
    while True:
        # Send a small burst to give the batcher something to batch
        burst = random.randint(2, 4)
        for _ in range(burst):
            text = random.choice(SAMPLE_TEXTS)
            request_queue.put({"text": text, "arrived_at": time.time()})
            time.sleep(0.05)  # 50ms between requests in burst
        # Then idle until next burst
        time.sleep(REQUEST_INTERVAL)

# --- Register with Registry ---
def register():
    payload = {
        "node_id": NODE_ID,
        "session_id": SESSION_ID,
        "status": "healthy",
        "cpu": 10.0,
        "model_version": "distilbert-sst2",
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
def heartbeat_loop(total_requests: list, latency_tracker: list):
    last_request_count = 0
    last_time = time.time()

    while True:
        time.sleep(HEARTBEAT_INTERVAL)

        cpu = psutil.cpu_percent(interval=1)
        latency_ms = latency_tracker[0]
        batch_sz = latency_tracker[1]
        total = total_requests[0]

        # Throughput: requests processed since last heartbeat
        now = time.time()
        elapsed = now - last_time
        rps = (total - last_request_count) / elapsed if elapsed > 0 else 0
        last_request_count = total
        last_time = now

        # Update Prometheus metrics
        cpu_usage.labels(node_id=NODE_ID).set(cpu)
        inference_latency.labels(node_id=NODE_ID).set(latency_ms)
        job_count.labels(node_id=NODE_ID).set(total)
        batch_size_gauge.labels(node_id=NODE_ID).set(batch_sz)
        throughput_gauge.labels(node_id=NODE_ID).set(round(rps, 2))

        payload = {
            "node_id": NODE_ID,
            "session_id": SESSION_ID,
            "status": "healthy",
            "cpu": cpu,
            "inference_latency_ms": latency_ms,
            "jobs_processed": total,
            "model_version": "distilbert-sst2"
        }
        try:
            requests.post(f"{REGISTRY_URL}/heartbeat", json=payload)
            print(
                f"[{NODE_ID}] Heartbeat — CPU: {cpu:.1f}% | "
                f"Latency: {latency_ms:.1f}ms | Batch: {batch_sz} | "
                f"Throughput: {rps:.1f} req/s | Total: {total}"
            )
        except Exception as e:
            print(f"[{NODE_ID}] Heartbeat failed: {e}")

# --- Main ---
if __name__ == "__main__":
    METRICS_PORT = int(os.environ.get("METRICS_PORT", "9100"))
    start_http_server(METRICS_PORT)
    print(f"[{NODE_ID}] Starting up (session: {SESSION_ID[:8] if SESSION_ID else 'none'})...")

    register()

    # Shared state between threads (using lists for mutability)
    total_requests = [0]       # [count]
    latency_tracker = [0.0, 1] # [last_batch_latency_ms, last_batch_size]

    # Start dynamic batching engine
    threading.Thread(target=batching_loop, args=(total_requests, latency_tracker), daemon=True).start()

    # Start request producer (simulates incoming traffic)
    threading.Thread(target=request_producer, daemon=True).start()

    # Start heartbeat
    threading.Thread(target=heartbeat_loop, args=(total_requests, latency_tracker), daemon=True).start()

    while True:
        time.sleep(1)
