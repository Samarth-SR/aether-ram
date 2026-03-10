"""
@offloadable SDK
Decorator that automatically uses the Decision Engine to choose
between local execution and cloud offloading.

Usage:
    from sdk import offloadable

    @offloadable(task_type="matrix_multiply")
    def heavy_compute(n: int):
        import numpy as np
        A = np.random.rand(n, n)
        return (A @ A).sum()

    result = heavy_compute(n=2000)
"""
import functools
import os
import sys
import time
import psutil
import httpx
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(__file__))
from decision import should_offload

CLOUD_API = os.getenv("CLOUD_API_URL", "http://localhost:8000")
DEFAULT_SESSION_ID = os.getenv("CLOUD_SESSION_ID", "")


def offloadable(
    task_type: str,
    params_map: Optional[dict] = None,
    force_cloud: bool = False,
    force_local: bool = False,
):
    """
    Decorator factory that wraps a function with decision-engine-based offloading.

    Args:
        task_type:   Task registry key (e.g. "matrix_multiply").
        params_map:  Map function kwargs → task params dict (optional).
        force_cloud: Always offload, ignore decision engine.
        force_local: Always run locally, ignore decision engine.
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Build params dict from kwargs
            params = dict(kwargs)
            if params_map:
                params = {k: kwargs.get(v, kwargs.get(k)) for k, v in params_map.items()}

            # 1 — Decision
            local_ram_pct = psutil.virtual_memory().percent
            decision = should_offload(local_ram_pct, task_type, params)

            run_remote = (force_cloud or decision.should_offload) and not force_local

            print(f"\n[SDK] Task: {task_type}")
            print(f"      Decision: {'☁  OFFLOAD' if run_remote else '🖥  LOCAL'}")
            print(f"      Reason: {decision.reason[:80]}...")
            print(f"      Confidence: {decision.confidence:.0%}")

            if not run_remote:
                # Run locally
                start = time.time()
                result = fn(*args, **kwargs)
                elapsed = time.time() - start
                print(f"      Local time: {elapsed*1000:.0f}ms")
                return result

            # 2 — Offload to cloud
            session_id = DEFAULT_SESSION_ID or _get_or_create_session()
            if not session_id:
                print("      ⚠  No session, falling back to local")
                return fn(*args, **kwargs)

            try:
                resp = httpx.post(
                    f"{CLOUD_API}/offload",
                    json={
                        "session_id": session_id,
                        "task_type": task_type,
                        "params": params,
                    },
                    timeout=5.0,
                )
                resp.raise_for_status()
                task_id = resp.json()["task_id"]
                print(f"      Task queued: {task_id}")

                # 3 — Poll for result
                return _poll_result(task_id)

            except Exception as exc:
                print(f"      ⚠  Cloud error ({exc}), falling back to local")
                return fn(*args, **kwargs)

        return wrapper
    return decorator


_session_id: Optional[str] = None


def _get_or_create_session(user_id: str = "sdk-user", ram_mb: int = 2048) -> Optional[str]:
    """Create a new cloud session if none exists."""
    global _session_id
    if _session_id:
        return _session_id
    try:
        resp = httpx.post(
            f"{CLOUD_API}/allocate",
            json={"user_id": user_id, "requested_ram_mb": ram_mb},
            timeout=5.0,
        )
        resp.raise_for_status()
        _session_id = resp.json()["session_id"]
        return _session_id
    except Exception:
        return None


def _poll_result(task_id: str, timeout: float = 120.0) -> Optional[dict]:
    """Poll /results/{task_id} until completed or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{CLOUD_API}/results/{task_id}", timeout=5.0)
            data = resp.json()
            status = data.get("status")
            if status == "completed":
                print(f"      ✓ Cloud completed in {data['result'].get('duration_ms', '?')}ms")
                return data.get("result")
            elif status in ("failed", "dead_letter"):
                print(f"      ✗ Task failed: {data.get('error')}")
                return None
        except Exception:
            pass
        time.sleep(0.5)

    print(f"      ✗ Timeout waiting for {task_id}")
    return None
