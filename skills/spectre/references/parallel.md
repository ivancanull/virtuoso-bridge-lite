# Parallel Simulation & Job Management

## Table of Contents
- Fire-and-forget with submit()
- Batch with run_parallel()
- Concurrency control
- Multi-server simulation
- Job management CLI (sim-jobs, sim-cancel)
- .env configuration

---

## Fire-and-forget with `submit()`

`submit()` returns a `Future` immediately. The simulation runs in a background thread.

```python
sim = SpectreSimulator.from_env()

# Submit simulations as needed — returns Future immediately
t1 = sim.submit(Path("tb_comparator.scs"), {"include_files": ["comp.va"]})
t2 = sim.submit(Path("tb_dac.scs"))

# Do other work while simulations run...

# Check without blocking
if t1.done():
    result = t1.result()

# Block on a specific one
result2 = t2.result()

# Submit more while others are still running
t3 = sim.submit(Path("tb_sar_logic.scs"))

# Wait for a batch
results = SpectreSimulator.wait_all([t1, t2, t3])
```

## Batch with `run_parallel()`

Submit all at once, wait for all to complete:

```python
results = sim.run_parallel([
    (Path("tb_comp.scs"), {"include_files": ["comp.va"]}),
    (Path("tb_dac.scs"), {}),
    (Path("tb_logic.scs"), {}),
], max_workers=5)
```

## Concurrency control

```python
sim.set_max_workers(4)  # default is 8, adjust for license/CPU limits
sim.shutdown()           # tear down pool, new one created on next submit
```

Each simulation gets its own remote directory (uuid-based) — no file conflicts.
SSH ControlMaster is shared automatically across threads.

## Multi-server simulation

Create a simulator per profile to distribute work across machines:

```python
# .env defines VB_REMOTE_HOST_worker1, VB_REMOTE_HOST_worker2, etc.
sim1 = SpectreSimulator(remote=True, profile="worker1")
sim2 = SpectreSimulator(remote=True, profile="worker2")

t1 = sim1.submit(Path("tb_comp.scs"))
t2 = sim2.submit(Path("tb_dac.scs"))

results = SpectreSimulator.wait_all([t1, t2])
```

## Job management (CLI)

Monitor and control simulations from the terminal:

```bash
# Show all jobs: user@host, status, time, CPU/MEM for running jobs
virtuoso-bridge sim-jobs

# Cancel a running simulation (kills remote Spectre process)
virtuoso-bridge sim-cancel <job-id>
```

`sim-jobs` output:
```
Simulation Jobs: 2 running, 1 queued, 3 done, 0 failed

● a3f2c1d0  zhangz@zhangz-wei         tb_comp.scs              running  16:45:29 45s  CPU:98.2% MEM:3.1%
● b7e9a412  designer1@wei-worker1     tb_dac.scs               running  16:45:30 12s  CPU:45.7% MEM:1.8%
○ c4d5e6f7  zhangz@zhangz-wei         tb_logic.scs             queued   16:45:35 0s
✓ d8e9f012  zhangz@zhangz-wei         tb_bias.scs              done     16:44:10-16:44:25 15s
```

Finished jobs auto-expire after 10 minutes.

## .env configuration

The `.env` file can live in the virtuoso-bridge-lite directory or in your project root
(recommended when virtuoso-bridge-lite is cloned as a subdirectory). Both locations
are searched automatically.

```dotenv
# Default connection
VB_REMOTE_HOST=my-server
VB_REMOTE_USER=username
VB_REMOTE_PORT=65081
VB_LOCAL_PORT=65082
VB_CADENCE_CSHRC=/path/to/.cshrc.cadence

# Additional profiles for multi-server
VB_REMOTE_HOST_worker1=eda-node1
VB_REMOTE_USER_worker1=sim_user
VB_REMOTE_PORT_worker1=65432
VB_LOCAL_PORT_worker1=65433
```
