# AetherRAM

**AetherRAM** is an advanced cloud computing proof-of-concept that brings the "download more RAM" concept to life through transparent **app-level workload offloading**. 

It intelligently delegates CPU and memory-intensive computations to a warm pool of distributed cloud workers, seamlessly freeing up local system resources while maintaining the feel of local execution.

---

# Architecture Overview

```text
+---------------------------------------------------+
|                Client Interface                   |
|           Web UI / Monitor Dashboard              |
+---------------------------------------------------+
|                Application Layer                  |
|    Smart Decision Engine / Workload Offloading    |
+---------------------------------------------------+
|                 Cloud Pipeline                    |
|      FastAPI → Task Queue → Session Control       |
+---------------------------------------------------+
|               Execution Environment               |
|                                                   |
|   +----------------+    +----------------------+  |
|   | Local Compute  |    | Distributed Workers  |  |
|   | (Lightweight)  |    | (Dockerized Pool)    |  |
|   +----------------+    +----------------------+  |
|                                                   |
+---------------------------------------------------+
```

---

# System Flow

```text
User Application
   │
   ▼
Task Submission (@offloadable)
   │
   ▼
Decision Engine Evaluation
   │
   ├── Local Execution (If latency/cost optimized)
   └── Cloud Offload (If resource constrained)
          │
          ▼
     Cloud Backend API (FastAPI)
          │
          ▼
     Worker Queue (Redis)
          │
          ▼
   Distributed Worker Pool (RQ)
          │
          ▼
Result Aggregation & Return
```

---

# Core Components

### Intelligent Routing
- **Decision Engine**: Evaluates network latency, computational requirements, and local constraints to intelligently route tasks between local hardware and cloud workers.
- **Client SDK**: Provides an elegant `@offloadable` decorator to transform standard local functions into distributed workloads seamlessly.

### Execution Layer
- **Cloud Backend**: A robust FastAPI-driven REST and WebSocket interface managing JWT session tokens, task queues, and asynchronous routing.
- **Worker Pool**: A scalable, Dockerized cluster of RQ workers backed by Redis for high-throughput, horizontally scalable task processing.

### Observability
- **Monitor Dashboard**: A localized web interface providing real-time visibility into system health, network stability, offload metrics, and active workloads.
- **Simulation Controls**: Built-in mechanisms to simulate network drops and worker crashes for chaos testing.

---

# Getting Started

### 1. Install Dependencies
```powershell
git clone https://github.com/yourusername/aether-ram.git
cd aether-ram
pip install -r requirements.txt
```

### 2. Start the Cloud Backend
```powershell
cd server
uvicorn main:app --reload --port 8000
```
*(Alternatively, for a full distributed worker pool, use `docker-compose up --build` inside the `server/` directory).*

### 3. Start the Local Monitor & Dashboard
Open a new terminal session:
```powershell
cd aether-ram
python client/monitor.py
```

### 4. Access the Dashboard
Navigate to **http://localhost:8001** in your web browser to view the real-time telemetry and control panel.

---

# Usage Example

AetherRAM makes offloading easy via the `@offloadable` SDK decorator:

```python
from client.sdk import offloadable
import numpy as np

# Let the Decision Engine route this automatically
@offloadable(task_type="matrix_multiply")
def heavy_compute(n: int):
    A = np.random.rand(n, n)
    return (A @ A).sum()

# Execute as normal. The system will calculate if it's faster locally or in the cloud.
result = heavy_compute(n=2000)
print(f"Computed Result: {result}")
```

### Running Benchmarks
You can also run the built-in CLI benchmark to compare Local vs. Cloud performance:
```powershell
python client/benchmark.py                        # Run all 4 test workloads
python client/benchmark.py --task matrix_multiply --n 2000
python client/benchmark.py --task compress --size-mb 20
```

---

# Project Structure

```text
aether-ram/
│
├── client/
│   ├── dashboard/
│   │   ├── index.html
│   │   ├── app.js
│   │   └── style.css
│   ├── monitor.py
│   ├── decision.py
│   ├── sdk.py
│   └── benchmark.py
│
├── server/
│   ├── main.py
│   ├── tasks.py
│   ├── auth.py
│   ├── worker.py
│   └── docker-compose.yml
│
├── requirements.txt
├── start.ps1
└── README.md
```

---

# Compute Pipeline

```text
Local Application Request
      │
      ▼
 Resource Profiling
      │
      ▼
 State Serialization
      │
      ▼
 Network Transmission
      │
      ├── Session Validation (JWT)
      │        │
      │        ▼
      │   Cloud Worker Assignment
      │
      ▼
 Result Deserialization
```

---

# Key Capabilities

- **Transparent Workload Offloading:** Seamlessly run heavy operations in the cloud without refactoring core logic.
- **Smart Decision Routing:** Heuristic-based routing ensures optimal execution times and resource utilization.
- **Distributed Execution:** Dockerized worker pools provide warm, scalable compute environments.
- **Real-Time Telemetry:** Live WebSocket streams power the local health and metric dashboard.
- **Fault-Tolerant Architecture:** Resilient task handling designed to gracefully survive simulated network and worker failures.

---

# License

MIT License
