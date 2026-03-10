"""
Client Monitor Agent
Monitors local system resources (RAM, CPU, Disk) via psutil
and serves them via a local HTTP API on port 8001.
Also serves the web dashboard and provides a /benchmark/local endpoint.
"""
import sys
import os
import time
import asyncio
import threading
import psutil

sys.path.insert(0, os.path.dirname(__file__))
from decision import should_offload, estimate_task_size_mb

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Cloud RAM - Local Monitor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve dashboard static files
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")


# ── Models ──────────────────────────────────────────────────────────────────────
class DecisionRequest(BaseModel):
    task_type: str
    params: dict = {}


class LocalBenchmarkRequest(BaseModel):
    task_type: str
    params: dict = {}


# ── Endpoints ───────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    return FileResponse(index_path)


@app.get("/stats")
async def get_stats():
    """Return real-time local system resource stats."""
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)
    disk = psutil.disk_usage("/")

    # Per-core CPU
    per_core = psutil.cpu_percent(percpu=True)

    # Top processes by memory
    processes = []
    for proc in sorted(psutil.process_iter(["pid", "name", "memory_percent"]),
                        key=lambda p: p.info.get("memory_percent") or 0,
                        reverse=True)[:5]:
        try:
            processes.append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "mem_pct": round(proc.info.get("memory_percent") or 0, 1),
            })
        except Exception:
            pass

    return {
        "timestamp": time.time(),
        "ram": {
            "total_gb": round(vm.total / 1e9, 2),
            "used_gb": round(vm.used / 1e9, 2),
            "available_gb": round(vm.available / 1e9, 2),
            "percent": vm.percent,
        },
        "cpu": {
            "percent": cpu,
            "per_core": per_core,
            "cores": psutil.cpu_count(),
        },
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb": round(disk.used / 1e9, 2),
            "percent": disk.percent,
        },
        "top_processes": processes,
    }


@app.post("/decision")
async def get_decision(req: DecisionRequest):
    """Run the Decision Engine and return a placement recommendation."""
    vm = psutil.virtual_memory()
    local_ram_pct = vm.percent

    decision = should_offload(local_ram_pct, req.task_type, req.params)
    task_size = estimate_task_size_mb(req.task_type, req.params)

    return {
        "should_offload": decision.should_offload,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "triggered_rule": decision.triggered_rule,
        "local_ram_pct": local_ram_pct,
        "estimated_task_size_mb": round(task_size, 2),
    }


@app.post("/benchmark/local")
async def run_local_benchmark(req: LocalBenchmarkRequest):
    """
    Run a task locally and return timing + resource usage.
    Used by the dashboard benchmark comparison panel.
    """
    # Import task functions from server directory
    server_dir = os.path.join(os.path.dirname(__file__), "..", "server")
    sys.path.insert(0, server_dir)
    from tasks import TASK_REGISTRY, TASK_DEFAULTS

    fn = TASK_REGISTRY.get(req.task_type)
    if not fn:
        return {"error": f"Unknown task type: {req.task_type}"}

    params = {**TASK_DEFAULTS.get(req.task_type, {}), **req.params}

    vm_before = psutil.virtual_memory()
    cpu_before = psutil.cpu_percent(interval=None)
    start = time.time()

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: fn(**params))

    elapsed = time.time() - start
    vm_after = psutil.virtual_memory()
    cpu_after = psutil.cpu_percent(interval=None)

    return {
        "mode": "local",
        "task_type": req.task_type,
        "params": params,
        "duration_ms": int(elapsed * 1000),
        "ram_before_pct": vm_before.percent,
        "ram_after_pct": vm_after.percent,
        "ram_delta_mb": round((vm_after.used - vm_before.used) / 1e6, 2),
        "cpu_pct": round(cpu_after, 1),
        "result_summary": {
            k: v for k, v in result.items()
            if k not in ("image_b64",)  # skip large binary fields
        },
    }


# Mount dashboard static files at a path that matches the HTML's relative references
if os.path.isdir(DASHBOARD_DIR):
    # Mount at /dash — serves style.css as /dash/style.css, etc.
    # index.html will reference ./style.css → works when served from /
    app.mount("/dash", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

# Also serve individual dashboard assets at root level so relative paths work
@app.get("/style.css")
async def serve_css():
    return FileResponse(os.path.join(DASHBOARD_DIR, "style.css"), media_type="text/css")

@app.get("/app.js")
async def serve_js():
    return FileResponse(os.path.join(DASHBOARD_DIR, "app.js"), media_type="application/javascript")


if __name__ == "__main__":
    print("=" * 55)
    print("  Cloud RAM — Local Monitor Agent")
    print("=" * 55)
    print(f"  Dashboard  → http://localhost:8001")
    print(f"  Stats API  → http://localhost:8001/stats")
    print(f"  Decision   → POST http://localhost:8001/decision")
    print(f"  Benchmark  → POST http://localhost:8001/benchmark/local")
    print("=" * 55)

    vm = psutil.virtual_memory()
    print(f"\n  System: {psutil.cpu_count()} cores | {vm.total / 1e9:.1f} GB RAM")
    print(f"  Current RAM usage: {vm.percent:.1f}%\n")

    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
