import os
import time
import uuid
import json
import threading
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
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
MAX_CONCURRENT_SESSIONS = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "3"))
SESSION_IDLE_TIMEOUT = int(os.environ.get("SESSION_IDLE_TIMEOUT", "600"))  # 10 min
CLEANUP_INTERVAL = 60  # check for expired sessions every 60s
MANAGER_URL = os.environ.get("MANAGER_URL", "http://localhost:8002")

# --- Redis ---
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)

# --- FastAPI ---
app = FastAPI(title="FleetOS Session Service")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429, content={"error": "Rate limit exceeded — slow down"}
))
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helpers ---
def get_active_sessions():
    keys = r.keys("session:*")
    sessions = []
    for key in keys:
        raw = r.get(key)
        if raw:
            sessions.append(json.loads(raw))
    return sessions

def get_session(session_id: str):
    raw = r.get(f"session:{session_id}")
    return json.loads(raw) if raw else None

def save_session(session: dict):
    r.set(f"session:{session['session_id']}", json.dumps(session))

def delete_session(session_id: str):
    r.delete(f"session:{session_id}")

def cleanup_session(session_id: str):
    """Tear down all containers for a session, then delete the session."""
    # Ask manager for all nodes in this session and remove them
    try:
        res = requests.get(
            f"{MANAGER_URL}/nodes",
            headers={"x-session-token": session_id},
            timeout=5
        )
        nodes = res.json().get("nodes", {})
        for node_id in list(nodes.keys()):
            try:
                requests.post(
                    f"{MANAGER_URL}/nodes/{node_id}/remove",
                    headers={"x-session-token": session_id},
                    timeout=5
                )
                print(f"[Sessions] Removed container {node_id} for expired session {session_id[:8]}")
            except Exception as e:
                print(f"[Sessions] Could not remove {node_id}: {e}")
    except Exception as e:
        print(f"[Sessions] Could not reach manager for session cleanup {session_id[:8]}: {e}")

    delete_session(session_id)

# --- Routes ---
@app.post("/sessions/create")
@limiter.limit("5/minute")
def create_session(request: Request):
    active = get_active_sessions()
    if len(active) >= MAX_CONCURRENT_SESSIONS:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {MAX_CONCURRENT_SESSIONS} concurrent sessions reached. Try again later."
        )

    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "created_at": time.time(),
        "last_active": time.time(),
        "node_count": 0,
        "status": "active"
    }
    save_session(session)
    print(f"[Sessions] New session created: {session_id} ({len(active) + 1}/{MAX_CONCURRENT_SESSIONS} active)")
    return {
        "session_id": session_id,
        "max_nodes": int(os.environ.get("MAX_NODES_PER_SESSION", "6")),
        "active_sessions": len(active) + 1,
        "max_sessions": MAX_CONCURRENT_SESSIONS
    }

@app.post("/sessions/{session_id}/end")
def end_session(session_id: str, x_session_token: str = Header(...)):
    if x_session_token != session_id:
        raise HTTPException(status_code=403, detail="Invalid session token")
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    cleanup_session(session_id)
    print(f"[Sessions] Session ended: {session_id}")
    return {"message": "Session ended"}

@app.post("/sessions/{session_id}/heartbeat")
def session_heartbeat(session_id: str, x_session_token: str = Header(...)):
    if x_session_token != session_id:
        raise HTTPException(status_code=403, detail="Invalid session token")
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    session["last_active"] = time.time()
    save_session(session)
    return {"status": "ok"}

@app.get("/sessions/count")
def session_count():
    active = get_active_sessions()
    return {
        "active_sessions": len(active),
        "max_sessions": MAX_CONCURRENT_SESSIONS,
        "slots_available": MAX_CONCURRENT_SESSIONS - len(active)
    }

@app.get("/sessions/{session_id}/validate")
def validate_session(session_id: str, x_session_token: str = Header(...)):
    if x_session_token != session_id:
        raise HTTPException(status_code=403, detail="Invalid session token")
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return {"valid": True, "session": session}

# --- Background: expire idle sessions ---
def cleanup_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL)
        now = time.time()
        sessions = get_active_sessions()
        for session in sessions:
            idle_for = now - session.get("last_active", 0)
            if idle_for > SESSION_IDLE_TIMEOUT:
                print(f"[Sessions] Expiring idle session {session['session_id'][:8]} (idle {int(idle_for)}s) — cleaning up containers...")
                cleanup_session(session["session_id"])

# --- Main ---
if __name__ == "__main__":
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    print(f"[Sessions] Starting session service on port 8003...")
    print(f"[Sessions] Max sessions: {MAX_CONCURRENT_SESSIONS}, idle timeout: {SESSION_IDLE_TIMEOUT}s")
    uvicorn.run(app, host="0.0.0.0", port=8003)
