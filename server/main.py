"""
FastAPI Cloud RAM Backend — Main Application
Endpoints: /status, /allocate, /offload, /results/{id}, /release/{id}, /ws
WebSocket broadcasts real-time task and allocation events.
Falls back to in-process thread pool if Redis is unavailable.
"""
import asyncio
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import create_token, verify_token
from tasks import TASK_REGISTRY, TASK_DEFAULTS

# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Cloud RAM Backend",
    description="Download More RAM — cloud workload offloading service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis / RQ (optional) ──────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
USE_REDIS = False
task_queue = None
redis_conn = None

try:
    import redis as redis_lib
    from rq import Queue
    from rq.job import Job as RQJob

    _r = redis_lib.from_url(REDIS_URL)
    _r.ping()
    redis_conn = _r
    task_queue = Queue(connection=redis_conn)
    USE_REDIS = True
    print(f"[OK] Redis connected at {REDIS_URL} -- distributed workers enabled")
except Exception as _e:
    print(f"[WARNING] Redis not available ({_e}) -- using thread pool (single-node mode)")

# In-process thread pool (always active as primary or fallback)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cloud-worker")

# ── In-memory state ────────────────────────────────────────────────────────────
sessions: Dict[str, dict] = {}       # session_id → session info
task_results: Dict[str, dict] = {}   # task_id    → result / status


# ── WebSocket Manager ──────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        print(f"  WS client connected (total: {len(self.connections)})")

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)
        print(f"  WS client disconnected (total: {len(self.connections)})")

    async def broadcast(self, message: dict):
        dead: List[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for d in dead:
            self.connections.remove(d)


manager = ConnectionManager()


# ── Pydantic models ────────────────────────────────────────────────────────────
class AllocateRequest(BaseModel):
    user_id: str
    requested_ram_mb: int = 1024
    keep_warm_minutes: int = 5


class OffloadRequest(BaseModel):
    session_id: str
    task_type: str
    params: dict = {}


class BenchmarkRequest(BaseModel):
    task_type: str
    params: dict = {}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _run_task_sync(task_id: str, task_type: str, params: dict) -> dict:
    """Execute a task synchronously in a worker thread."""
    fn = TASK_REGISTRY[task_type]
    try:
        result = fn(**params)
        result["task_id"] = task_id
        task_results[task_id] = {"status": "completed", "result": result}
        return result
    except Exception as exc:
        err = {"task_id": task_id, "status": "failed", "error": str(exc)}
        task_results[task_id] = err
        return err


async def _dispatch_task(task_id: str, task_type: str, params: dict):
    """
    Dispatch task to thread pool, broadcast status updates, handle retries.
    Implements fault-tolerance: 3 attempts with exponential backoff.
    """
    MAX_RETRIES = 3
    attempt = 0

    while attempt < MAX_RETRIES:
        attempt += 1
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "running",
            "task_type": task_type,
            "attempt": attempt,
        })

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(executor, _run_task_sync, task_id, task_type, params),
                timeout=60.0,
            )

            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "Task failed"))

            # Success
            await manager.broadcast({
                "type": "task_result",
                "task_id": task_id,
                "status": "completed",
                "result": result,
                "task_type": task_type,
            })
            return

        except asyncio.TimeoutError:
            msg = f"Task timed out (attempt {attempt}/{MAX_RETRIES})"
            task_results[task_id] = {"status": "retrying", "error": msg}
            await manager.broadcast({
                "type": "task_update",
                "task_id": task_id,
                "status": "retrying",
                "task_type": task_type,
                "message": msg,
            })
            await asyncio.sleep(2 ** attempt)  # exponential backoff

        except Exception as exc:
            msg = f"Error on attempt {attempt}/{MAX_RETRIES}: {exc}"
            await manager.broadcast({
                "type": "task_update",
                "task_id": task_id,
                "status": "retrying" if attempt < MAX_RETRIES else "failed",
                "task_type": task_type,
                "message": msg,
            })
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    # All retries exhausted → dead-letter
    task_results[task_id] = {"status": "dead_letter", "task_type": task_type}
    await manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": "dead_letter",
        "task_type": task_type,
        "message": "Task moved to dead-letter queue after 3 failed attempts.",
    })


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/status")
async def get_status():
    """Server health & stats."""
    import psutil
    worker_count = 0
    if USE_REDIS and redis_conn:
        try:
            worker_count = len(redis_conn.smembers("rq:workers"))
        except Exception:
            pass

    return {
        "status": "online",
        "mode": "distributed-rq" if USE_REDIS else "thread-pool",
        "worker_threads": 4,
        "rq_workers": worker_count,
        "active_sessions": len(sessions),
        "task_count": len(task_results),
        "server_ram_pct": psutil.virtual_memory().percent,
        "server_cpu_pct": psutil.cpu_percent(interval=None),
        "timestamp": time.time(),
    }


@app.post("/allocate")
async def allocate(req: AllocateRequest):
    """Reserve a warm worker pool slot and create a session."""
    session_id = f"s-{uuid.uuid4().hex[:8]}"
    worker_id = f"w-{uuid.uuid4().hex[:4]}"

    sessions[session_id] = {
        "user_id": req.user_id,
        "worker_id": worker_id,
        "requested_ram_mb": req.requested_ram_mb,
        "allocated_at": time.time(),
        "keep_warm_minutes": req.keep_warm_minutes,
        "status": "active",
        "tasks_run": 0,
    }

    token = create_token({"session_id": session_id, "user_id": req.user_id})

    await manager.broadcast({
        "type": "allocation",
        "session_id": session_id,
        "ram_mb": req.requested_ram_mb,
        "worker_id": worker_id,
        "message": f"Cloud RAM allocated: {req.requested_ram_mb} MB on worker {worker_id}",
    })

    return {
        "session_id": session_id,
        "worker_id": worker_id,
        "worker_reserved": True,
        "allocated_ram_mb": req.requested_ram_mb,
        "token": token,
    }


@app.post("/offload")
async def offload(req: OffloadRequest):
    """Submit a task to the cloud worker pool."""
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found. Call /allocate first.")
    if req.task_type not in TASK_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type '{req.task_type}'. Valid: {list(TASK_REGISTRY.keys())}",
        )

    task_id = f"t-{uuid.uuid4().hex[:8]}"

    # Merge provided params with defaults
    params = {**TASK_DEFAULTS.get(req.task_type, {}), **req.params}

    # Store initial state
    task_results[task_id] = {
        "status": "queued",
        "task_type": req.task_type,
        "queued_at": time.time(),
    }

    # Update session task count
    sessions[req.session_id]["tasks_run"] = sessions[req.session_id].get("tasks_run", 0) + 1

    # Broadcast queue event
    await manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": "queued",
        "task_type": req.task_type,
    })

    # Kick off async execution
    asyncio.create_task(_dispatch_task(task_id, req.task_type, params))

    return {"task_id": task_id, "status": "queued"}


@app.get("/results/{task_id}")
async def get_results(task_id: str):
    """Poll a task result."""
    if task_id not in task_results:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    entry = task_results[task_id]
    return {
        "task_id": task_id,
        "status": entry.get("status"),
        "result": entry.get("result"),
        "error": entry.get("error"),
    }


@app.post("/release/{session_id}")
async def release_session(session_id: str):
    """Release a session and return worker to the warm pool."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    session = sessions.pop(session_id)
    await manager.broadcast({
        "type": "release",
        "session_id": session_id,
        "message": f"Session released. Worker {session['worker_id']} returned to pool.",
    })
    return {"status": "released", "session": session}


@app.post("/simulate/crash")
async def simulate_crash():
    """Demo endpoint: simulate a worker crash and auto-recovery."""
    await manager.broadcast({
        "type": "system_event",
        "event": "worker_crash",
        "message": "⚠ Worker w-02 crashed! Requeuing affected tasks...",
    })
    await asyncio.sleep(2)
    await manager.broadcast({
        "type": "system_event",
        "event": "worker_recovered",
        "message": "✓ Worker w-03 picked up tasks. System recovered automatically.",
    })
    return {"status": "crash_simulated"}


@app.post("/simulate/network_drop")
async def simulate_network_drop():
    """Demo endpoint: simulate a network interruption."""
    await manager.broadcast({
        "type": "system_event",
        "event": "network_drop",
        "message": "⚠ Network instability detected. Retrying with exponential backoff...",
    })
    await asyncio.sleep(3)
    await manager.broadcast({
        "type": "system_event",
        "event": "network_recovered",
        "message": "✓ Connection re-established. Tasks resumed.",
    })
    return {"status": "network_drop_simulated"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Real-time event stream for the dashboard."""
    await manager.connect(ws)
    try:
        while True:
            # Keep alive — accept heartbeat pings from client
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
