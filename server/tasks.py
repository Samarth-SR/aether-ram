"""
Cloud worker task implementations.
All 4 demo workloads: matrix multiply, image filter, CSV aggregate, zstd compression.
These run inside the worker pool (threads or RQ workers).
"""
import time
import os
import io
import random
import psutil


def matrix_multiply(n: int = 1000) -> dict:
    """
    Multiply two n×n random matrices using NumPy.
    Demonstrates CPU + memory heavy compute offloading.
    """
    import numpy as np

    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024
    cpu_before = psutil.cpu_percent(interval=None)

    start = time.time()

    A = np.random.rand(n, n).astype(np.float64)
    B = np.random.rand(n, n).astype(np.float64)
    C = A @ B
    result_sum = float(C.sum())

    elapsed = time.time() - start
    mem_after = process.memory_info().rss / 1024 / 1024
    cpu_after = psutil.cpu_percent(interval=None)

    return {
        "task_type": "matrix_multiply",
        "n": n,
        "result_checksum": round(result_sum, 4),
        "duration_ms": int(elapsed * 1000),
        "cloud_ram_mb": round(max(0, mem_after - mem_before), 2),
        "peak_ram_mb": round(mem_after, 2),
        "cpu_pct": round(cpu_after, 1),
        "status": "completed",
    }


def image_filter(width: int = 512, height: int = 512, filter_type: str = "blur") -> dict:
    """
    Generate a synthetic image and apply a filter using Pillow.
    Demonstrates visual result offloading.
    """
    from PIL import Image, ImageFilter
    import base64

    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024

    start = time.time()

    # Create a colorful gradient image
    img = Image.new("RGB", (width, height))
    pixels = [
        (
            (x * 255 // width),
            (y * 255 // height),
            ((x + y) * 127 // (width + height)),
        )
        for y in range(height)
        for x in range(width)
    ]
    img.putdata(pixels)

    filter_map = {
        "blur": ImageFilter.GaussianBlur(radius=8),
        "sharpen": ImageFilter.SHARPEN,
        "edge": ImageFilter.FIND_EDGES,
        "emboss": ImageFilter.EMBOSS,
    }
    flt = filter_map.get(filter_type, ImageFilter.GaussianBlur(radius=5))
    result_img = img.filter(flt)

    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    img_size_kb = round(len(buf.getvalue()) / 1024, 1)

    elapsed = time.time() - start
    mem_after = process.memory_info().rss / 1024 / 1024

    return {
        "task_type": "image_filter",
        "width": width,
        "height": height,
        "filter_type": filter_type,
        "image_b64": img_b64,          # full image for dashboard preview
        "output_size_kb": img_size_kb,
        "duration_ms": int(elapsed * 1000),
        "cloud_ram_mb": round(max(0, mem_after - mem_before), 2),
        "status": "completed",
    }


def csv_aggregate(rows: int = 100_000) -> dict:
    """
    Generate a large in-memory dataset, sort it, and compute aggregates.
    Demonstrates data science workload offloading.
    """
    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024

    start = time.time()

    categories = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    data = [
        {
            "id": i,
            "category": categories[i % len(categories)],
            "value": random.uniform(0, 10000),
            "score": random.uniform(0, 100),
        }
        for i in range(rows)
    ]

    # Group-by aggregate
    totals: dict = {}
    counts: dict = {}
    for row in data:
        cat = row["category"]
        totals[cat] = totals.get(cat, 0.0) + row["value"]
        counts[cat] = counts.get(cat, 0) + 1

    averages = {cat: round(totals[cat] / counts[cat], 2) for cat in totals}
    totals = {k: round(v, 2) for k, v in totals.items()}

    # Sort top 5
    top5 = sorted(data, key=lambda x: x["value"], reverse=True)[:5]

    elapsed = time.time() - start
    mem_after = process.memory_info().rss / 1024 / 1024

    return {
        "task_type": "csv_aggregate",
        "rows": rows,
        "totals": totals,
        "averages": averages,
        "top_values": [round(r["value"], 2) for r in top5],
        "duration_ms": int(elapsed * 1000),
        "cloud_ram_mb": round(max(0, mem_after - mem_before), 2),
        "status": "completed",
    }


def compress(size_mb: int = 10) -> dict:
    """
    Compress random data using zstd. Demonstrates memory/CPU offloading for
    compression-heavy workloads.
    """
    import zstandard as zstd

    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024

    start = time.time()

    raw_data = os.urandom(size_mb * 1024 * 1024)
    cctx = zstd.ZstdCompressor(level=3)
    compressed = cctx.compress(raw_data)

    ratio = len(raw_data) / len(compressed)
    output_size_kb = round(len(compressed) / 1024, 1)

    elapsed = time.time() - start
    mem_after = process.memory_info().rss / 1024 / 1024

    return {
        "task_type": "compress",
        "input_size_mb": size_mb,
        "output_size_kb": output_size_kb,
        "compression_ratio": round(ratio, 2),
        "space_saved_pct": round((1 - 1 / ratio) * 100, 1),
        "duration_ms": int(elapsed * 1000),
        "cloud_ram_mb": round(max(0, mem_after - mem_before), 2),
        "status": "completed",
    }


# Registry for task lookup
TASK_REGISTRY = {
    "matrix_multiply": matrix_multiply,
    "image_filter": image_filter,
    "csv_aggregate": csv_aggregate,
    "compress": compress,
}

# Default params for each task type (used in benchmark)
TASK_DEFAULTS = {
    "matrix_multiply": {"n": 1000},
    "image_filter": {"width": 512, "height": 512, "filter_type": "blur"},
    "csv_aggregate": {"rows": 50_000},
    "compress": {"size_mb": 5},
}
