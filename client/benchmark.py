"""
Benchmark Runner — Local vs Cloud Performance Comparison
Runs each demo workload both locally and via the cloud backend,
then prints a side-by-side comparison table.

Usage:
    python benchmark.py
    python benchmark.py --task matrix_multiply --n 2000
"""
import argparse
import os
import sys
import time
import psutil
import httpx
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from decision import should_offload, estimate_task_size_mb
from tasks import TASK_REGISTRY, TASK_DEFAULTS

CLOUD_API = os.getenv("CLOUD_API_URL", "http://localhost:8000")


# ── Local runner ────────────────────────────────────────────────────────────────
def run_local(task_type: str, params: dict) -> dict:
    """Run a task in-process and measure resource usage."""
    fn = TASK_REGISTRY[task_type]

    vm_before = psutil.virtual_memory()
    cpu_before = psutil.cpu_percent(interval=None)
    start = time.time()

    try:
        result = fn(**params)
    except Exception as e:
        return {"error": str(e), "mode": "local"}

    elapsed = time.time() - start
    vm_after = psutil.virtual_memory()
    cpu_after = psutil.cpu_percent(interval=None)

    return {
        "mode": "local",
        "task_type": task_type,
        "duration_ms": int(elapsed * 1000),
        "ram_before_pct": round(vm_before.percent, 1),
        "ram_after_pct": round(vm_after.percent, 1),
        "ram_delta_mb": round((vm_after.used - vm_before.used) / 1e6, 2),
        "cpu_pct": round(cpu_after, 1),
    }


# ── Cloud runner ────────────────────────────────────────────────────────────────
def create_session(user_id: str = "benchmark-user") -> Optional[str]:
    try:
        resp = httpx.post(
            f"{CLOUD_API}/allocate",
            json={"user_id": user_id, "requested_ram_mb": 4096},
            timeout=10.0,
        )
        return resp.json().get("session_id")
    except Exception as e:
        print(f"  ✗ Could not connect to cloud backend: {e}")
        return None


def poll_result(task_id: str, timeout: float = 120.0) -> Optional[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{CLOUD_API}/results/{task_id}", timeout=5.0)
            data = resp.json()
            if data.get("status") == "completed":
                return data.get("result", {})
            elif data.get("status") in ("failed", "dead_letter"):
                return {"error": data.get("error", "Unknown error")}
        except Exception:
            pass
        time.sleep(0.5)
    return {"error": "Timeout"}


def run_cloud(task_type: str, params: dict, session_id: str) -> dict:
    """Submit task to cloud and wait for result."""
    start = time.time()
    try:
        resp = httpx.post(
            f"{CLOUD_API}/offload",
            json={"session_id": session_id, "task_type": task_type, "params": params},
            timeout=10.0,
        )
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
    except Exception as e:
        return {"error": str(e), "mode": "cloud"}

    result = poll_result(task_id)
    total_elapsed = time.time() - start

    if result and "error" not in result:
        return {
            "mode": "cloud",
            "task_type": task_type,
            "duration_ms": result.get("duration_ms", int(total_elapsed * 1000)),
            "total_rtt_ms": int(total_elapsed * 1000),
            "cloud_ram_mb": result.get("cloud_ram_mb", 0),
            "cpu_pct": result.get("cpu_pct", 0),
        }
    return {"error": result.get("error", "Unknown"), "mode": "cloud"}


# ── Report printer ──────────────────────────────────────────────────────────────
def print_comparison(task_type: str, local: dict, cloud: dict, decision_reason: str):
    print(f"\n{'═'*58}")
    print(f"  BENCHMARK: {task_type.upper().replace('_', ' ')}")
    print(f"{'═'*58}")
    print(f"  {'Metric':<25}  {'Local':>12}  {'Cloud':>12}")
    print(f"  {'-'*53}")

    local_ms = local.get("duration_ms", 0)
    cloud_ms = cloud.get("duration_ms") or cloud.get("total_rtt_ms", 0)
    speedup = local_ms / cloud_ms if cloud_ms > 0 else 1.0

    def fmt_ms(ms): return f"{ms:,} ms"
    def fmt_pct(p): return f"{p:.1f}%"

    rows = [
        ("Execution Time", fmt_ms(local_ms), fmt_ms(cloud_ms)),
        ("RAM Delta (MB)", f"{local.get('ram_delta_mb', 0):+.1f}", f"{cloud.get('cloud_ram_mb', 0):.1f}"),
        ("CPU Load", fmt_pct(local.get("cpu_pct", 0)), fmt_pct(cloud.get("cpu_pct", 0))),
        ("Round-trip Time", "—", fmt_ms(cloud.get("total_rtt_ms", cloud_ms))),
    ]

    for label, lval, cval in rows:
        print(f"  {label:<25}  {lval:>12}  {cval:>12}")

    print(f"  {'-'*53}")
    winner = "☁  Cloud" if cloud_ms < local_ms else "🖥  Local"
    print(f"  {'Winner':<25}  {winner:>26}")
    if speedup != 1.0:
        faster = "Cloud" if cloud_ms < local_ms else "Local"
        ratio = max(speedup, 1/speedup)
        print(f"  {'Speed advantage':<25}  {faster} is {ratio:.1f}× faster")
    print(f"\n  Decision Engine: {decision_reason[:55]}...")
    print(f"{'═'*58}\n")


# ── Main ────────────────────────────────────────────────────────────────────────
def benchmark_task(task_type: str, params: dict, session_id: str):
    local_ram_pct = psutil.virtual_memory().percent
    decision = should_offload(local_ram_pct, task_type, params)

    print(f"\n  Running LOCAL  → {task_type} {params}")
    local = run_local(task_type, params)

    print(f"  Running CLOUD  → {task_type} {params}")
    cloud = run_cloud(task_type, params, session_id)

    print_comparison(task_type, local, cloud, decision.reason)
    return local, cloud


def main():
    parser = argparse.ArgumentParser(description="Cloud RAM Benchmark: Local vs Cloud")
    parser.add_argument("--task", choices=list(TASK_REGISTRY.keys()), default=None)
    parser.add_argument("--n", type=int, help="Matrix size (for matrix_multiply)")
    parser.add_argument("--rows", type=int, help="Row count (for csv_aggregate)")
    parser.add_argument("--size-mb", type=int, dest="size_mb", help="Data size (for compress)")
    args = parser.parse_args()

    print("\n" + "╔" + "═"*55 + "╗")
    print("║      CLOUD RAM — BENCHMARK SUITE                      ║")
    print("╚" + "═"*55 + "╝")

    # Check cloud connectivity
    print(f"\n  Connecting to cloud backend at {CLOUD_API}...")
    try:
        resp = httpx.get(f"{CLOUD_API}/status", timeout=5.0)
        status = resp.json()
        print(f"  ✓ Connected — mode: {status.get('mode')}, workers: {status.get('worker_threads')}")
    except Exception as e:
        print(f"  ✗ Cannot reach cloud backend: {e}")
        print("    Start the server first:  python ../server/main.py\n")
        return

    session_id = create_session()
    if not session_id:
        return
    print(f"  ✓ Session: {session_id}\n")

    tasks_to_run = []
    if args.task:
        params = dict(TASK_DEFAULTS.get(args.task, {}))
        if args.n:           params["n"] = args.n
        if args.rows:        params["rows"] = args.rows
        if args.size_mb:     params["size_mb"] = args.size_mb
        tasks_to_run = [(args.task, params)]
    else:
        # Run all 4 with default params
        tasks_to_run = [(t, dict(p)) for t, p in TASK_DEFAULTS.items()]

    for task_type, params in tasks_to_run:
        benchmark_task(task_type, params, session_id)

    # Release session
    try:
        httpx.post(f"{CLOUD_API}/release/{session_id}", timeout=5.0)
        print(f"  Session {session_id} released.\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
