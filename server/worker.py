"""
RQ Worker entry point.
Run with: python worker.py
Uses Redis if available, else prints an error.
"""
import os
import sys

try:
    import redis
    from rq import Worker, Queue

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    conn = redis.from_url(REDIS_URL)
    conn.ping()

    queues = [Queue(connection=conn), Queue("failed", connection=conn)]
    print(f"✓ Worker connected to Redis at {REDIS_URL}")
    print("  Watching queues: default, failed")
    print("  Waiting for jobs...\n")

    worker = Worker(queues, connection=conn)
    worker.work(with_scheduler=True)

except redis.ConnectionError:
    print("✗ ERROR: Cannot connect to Redis.")
    print("  Start Redis with: docker-compose up redis")
    print("  Or install Redis for Windows from: https://github.com/tporadowski/redis/releases")
    sys.exit(1)
except Exception as e:
    print(f"✗ Worker startup failed: {e}")
    sys.exit(1)
