"""
Decision Engine — Smart Offload Logic
Determines whether a workload should run locally or be offloaded to cloud.
Presentable as: "AI-assisted workload placement logic."
"""
from dataclasses import dataclass
from typing import Literal

# Thresholds (tunable)
RAM_THRESHOLD_PCT = 80       # Offload if local RAM usage exceeds this
TASK_SIZE_THRESHOLD_MB = 200 # Offload if estimated task payload > this
TIME_THRESHOLD_RATIO = 1.2   # Offload if local time > cloud time × ratio


@dataclass
class Decision:
    should_offload: bool
    reason: str
    confidence: float           # 0.0–1.0
    triggered_rule: str


# Rough estimates for each task type at given scale
# (local vs cloud processing time in seconds)
TASK_TIME_ESTIMATES = {
    "matrix_multiply": {
        "local_per_1000n": 0.8,   # seconds per 1000 rows
        "cloud_per_1000n": 0.3,
    },
    "image_filter": {
        "local_per_mpx": 0.5,     # seconds per megapixel
        "cloud_per_mpx": 0.15,
    },
    "csv_aggregate": {
        "local_per_100k": 0.6,    # seconds per 100k rows
        "cloud_per_100k": 0.2,
    },
    "compress": {
        "local_per_mb": 0.12,     # seconds per MB
        "cloud_per_mb": 0.04,
    },
}


def estimate_task_time(task_type: str, params: dict) -> tuple[float, float]:
    """Return (estimated_local_sec, estimated_cloud_sec) for a task."""
    est = TASK_TIME_ESTIMATES.get(task_type, {})

    if task_type == "matrix_multiply":
        n = params.get("n", 1000)
        return (
            est.get("local_per_1000n", 1.0) * n / 1000,
            est.get("cloud_per_1000n", 0.3) * n / 1000,
        )
    elif task_type == "image_filter":
        w = params.get("width", 512)
        h = params.get("height", 512)
        mpx = (w * h) / 1_000_000
        return (
            est.get("local_per_mpx", 0.5) * mpx,
            est.get("cloud_per_mpx", 0.15) * mpx,
        )
    elif task_type == "csv_aggregate":
        rows = params.get("rows", 50_000)
        return (
            est.get("local_per_100k", 0.6) * rows / 100_000,
            est.get("cloud_per_100k", 0.2) * rows / 100_000,
        )
    elif task_type == "compress":
        size_mb = params.get("size_mb", 10)
        return (
            est.get("local_per_mb", 0.12) * size_mb,
            est.get("cloud_per_mb", 0.04) * size_mb,
        )
    return 1.0, 0.5  # default


def estimate_task_size_mb(task_type: str, params: dict) -> float:
    """Rough estimate of payload/working-set size in MB."""
    if task_type == "matrix_multiply":
        n = params.get("n", 1000)
        return (n * n * 8) / (1024 * 1024)  # float64 × 2 matrices
    elif task_type == "image_filter":
        w = params.get("width", 512)
        h = params.get("height", 512)
        return (w * h * 3) / (1024 * 1024)
    elif task_type == "csv_aggregate":
        rows = params.get("rows", 50_000)
        return (rows * 50) / (1024 * 1024)  # ~50 bytes per row
    elif task_type == "compress":
        return float(params.get("size_mb", 10))
    return 1.0


def should_offload(
    local_ram_pct: float,
    task_type: str,
    params: dict,
) -> Decision:
    """
    Core decision function.
    Evaluates 3 rules (in priority order):

      Rule 1: RAM pressure      — local_ram_pct > RAM_THRESHOLD_PCT
      Rule 2: Large payload     — task_size_mb   > TASK_SIZE_THRESHOLD_MB
      Rule 3: Speed advantage   — estimated_local_time > estimated_cloud_time × ratio

    Returns a Decision with full explanation.
    """
    task_size_mb = estimate_task_size_mb(task_type, params)
    local_time, cloud_time = estimate_task_time(task_type, params)

    # Rule 1 — RAM pressure
    if local_ram_pct > RAM_THRESHOLD_PCT:
        return Decision(
            should_offload=True,
            reason=f"RAM at {local_ram_pct:.0f}% (threshold: {RAM_THRESHOLD_PCT}%). "
                   f"Local execution risks OOM. Offloading to protect system stability.",
            confidence=min(1.0, (local_ram_pct - RAM_THRESHOLD_PCT) / 20 + 0.6),
            triggered_rule="RAM_PRESSURE",
        )

    # Rule 2 — Large payload
    if task_size_mb > TASK_SIZE_THRESHOLD_MB:
        return Decision(
            should_offload=True,
            reason=f"Estimated working set {task_size_mb:.0f} MB exceeds threshold "
                   f"({TASK_SIZE_THRESHOLD_MB} MB). Large data is better processed remotely.",
            confidence=0.85,
            triggered_rule="LARGE_PAYLOAD",
        )

    # Rule 3 — Speed advantage
    if local_time > cloud_time * TIME_THRESHOLD_RATIO:
        speedup = local_time / cloud_time
        return Decision(
            should_offload=True,
            reason=f"Cloud estimated {cloud_time:.2f}s vs local {local_time:.2f}s "
                   f"(~{speedup:.1f}× faster). Offloading for performance.",
            confidence=min(0.9, 0.5 + speedup / 10),
            triggered_rule="SPEED_ADVANTAGE",
        )

    # Run locally
    return Decision(
        should_offload=False,
        reason=f"Local conditions acceptable. RAM: {local_ram_pct:.0f}%, "
               f"payload: {task_size_mb:.1f} MB, est. time: {local_time:.2f}s. "
               f"Running locally to avoid network overhead.",
        confidence=0.75,
        triggered_rule="LOCAL_PREFERRED",
    )
