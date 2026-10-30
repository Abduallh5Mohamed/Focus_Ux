"""Stage profiling, VRAM residency planning and the supported-length rule.

Everything here only observes or decides from numbers a real run produced.
Nothing is invented: a reading that cannot be taken on this machine (no
nvidia-smi, no psutil) is reported as ``None`` with the reason, never as 0.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time

from .gpu import StageLog

SPEED_LIMITS_FORMAT = "focus-speed-limits/1"


# -- readers (each returns None when the reading is unavailable) ---------------
def read_rss_mib() -> float | None:
    """Resident memory of this process, MiB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2**20
    except ImportError:
        pass
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = Counters()
            c.cb = ctypes.sizeof(c)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
                return c.WorkingSetSize / 2**20
        except (OSError, AttributeError):
            pass
    return None


def read_gpu() -> dict | None:
    """Whole-GPU utilisation % and memory used MiB through nvidia-smi."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits", "-i", "0"],
            capture_output=True, text=True, timeout=5)
        if done.returncode != 0:
            return None
        util, used, total = (float(v) for v in done.stdout.strip().splitlines()[0].split(","))
        return {"util": util, "used_mib": used, "total_mib": total}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


class ResourceMonitor:
    """Samples RAM and GPU in a thread. Readers are injectable for tests."""

    def __init__(self, interval_s: float = 0.25, rss=read_rss_mib, gpu=read_gpu):
        self.interval_s, self._rss, self._gpu = interval_s, rss, gpu
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[tuple[float, float | None, dict | None]] = []

    def _loop(self):
        while not self._stop.is_set():
            self.samples.append((time.perf_counter(), self._rss(), self._gpu()))
            self._stop.wait(self.interval_s)

    def start(self):
        self._stop.clear()
        self.samples.append((time.perf_counter(), self._rss(), self._gpu()))
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        self.samples.append((time.perf_counter(), self._rss(), self._gpu()))

    def window(self, t0: float, t1: float) -> dict:
        inside = [s for s in self.samples if t0 <= s[0] <= t1] or self.samples[-1:]
        rss = [s[1] for s in inside if s[1] is not None]
        gpu = [s[2] for s in inside if s[2] is not None]
        return {
            "peak_ram_mib": round(max(rss), 1) if rss else None,
            "gpu_util_mean_pct": round(sum(g["util"] for g in gpu) / len(gpu), 1) if gpu else None,
            "gpu_mem_peak_mib": round(max(g["used_mib"] for g in gpu), 1) if gpu else None,
            "gpu_samples": len(gpu),
        }


def classify_idle(cpu_cores_busy: float | None, gpu_util_pct: float | None,
                  cores: int | None = None) -> str:
    """Where the machine waits during a stage. Needs both readings to say anything about the GPU."""
    cores = cores or os.cpu_count() or 1
    if cpu_cores_busy is None:
        return "unknown"
    cpu_busy = cpu_cores_busy >= 0.5
    if gpu_util_pct is None:
        return "cpu_busy_gpu_unmeasured" if cpu_busy else "cpu_mostly_idle_gpu_unmeasured"
    gpu_busy = gpu_util_pct >= 50
    if cpu_busy and not gpu_busy:
        return "gpu_idle_waiting_for_cpu"
    if gpu_busy and not cpu_busy:
        return "cpu_idle_waiting_for_gpu"
    return "both_busy" if cpu_busy else "both_idle"


class StageProfiler(StageLog):
    """StageLog plus CPU time, peak RAM and GPU utilisation per stage."""

    def __init__(self, device: str = "cpu", monitor: ResourceMonitor | None = None):
        super().__init__(device)
        self.monitor = monitor or ResourceMonitor()
        self._own_monitor = monitor is None

    def __enter__(self):
        if self._own_monitor:
            self.monitor.start()
        return self

    def __exit__(self, *exc):
        if self._own_monitor:
            self.monitor.stop()

    @contextlib.contextmanager
    def stage(self, name: str):
        wall0, cpu0 = time.perf_counter(), time.process_time()
        try:
            with super().stage(name):
                yield
        finally:
            wall1, cpu1 = time.perf_counter(), time.process_time()
            entry = self.stages[name]
            wall = max(wall1 - wall0, 1e-9)
            entry["cpu_seconds"] = round(cpu1 - cpu0, 3)
            entry["cpu_cores_busy"] = round((cpu1 - cpu0) / wall, 2)
            entry.update(self.monitor.window(wall0, wall1))
            entry["idle"] = classify_idle(entry["cpu_cores_busy"], entry["gpu_util_mean_pct"])

    def as_dict(self) -> dict:
        out = super().as_dict()
        rams = [s["peak_ram_mib"] for s in self.stages.values() if s.get("peak_ram_mib") is not None]
        out["peak_ram_mib"] = max(rams) if rams else None
        return out


# -- VRAM residency --------------------------------------------------------------
class ResidencyPolicy:
    """Which models stay loaded between stages. Default: none (unload all), the
    behaviour validated so far. ``plan_residency`` builds a policy from measured peaks."""

    def __init__(self, keep: tuple[str, ...] = ()):
        self.keep = frozenset(keep)

    def release(self, name: str, model) -> bool:
        """Unload ``model`` unless the policy keeps it. Returns True when unloaded."""
        if name in self.keep:
            return False
        model.unload()
        return True


def plan_residency(measured_peak_mib: dict[str, float], total_vram_mib: float,
                   headroom_mib: float = 1024.0, order: tuple[str, ...] = ("embedder", "diarizer")) -> dict:
    """Keep models resident only while the measured sum fits in VRAM with headroom.

    ``measured_peak_mib``: model name -> peak VRAM measured with that model loaded
    on the target GPU. A model with no measurement is never kept (unknown cost).
    Returns {"keep": [...], "unload": [...], "budget_mib", "used_mib", "reason"}.
    """
    budget = total_vram_mib - headroom_mib
    keep, used = [], 0.0
    for name in order:
        peak = measured_peak_mib.get(name)
        if peak is None:
            continue
        if used + peak <= budget:
            keep.append(name)
            used += peak
    skipped = [n for n in order if n not in keep]
    reason = ("measured peaks fit within the budget" if not skipped else
              "no measurement or does not fit: " + ", ".join(skipped))
    return {"keep": keep, "unload": skipped, "budget_mib": round(budget, 1),
            "used_mib": round(used, 1), "reason": reason}


# -- supported length ----------------------------------------------------------------
def supported_audio_seconds(runs: list[dict], rtf_target: float, vram_budget_mib: float | None = None,
                            ram_budget_mib: float | None = None) -> dict:
    """The longest clip length that was MEASURED to meet the targets.

    ``runs``: every attempted clip, failed ones included; ``real_time_factor`` must be end-to-end
    wall time / audio seconds, never a sum of stage times. [{"audio_seconds", "real_time_factor", "peak_vram_mib", "peak_ram_mib", "ok"}].
    A length counts only if its own run completed within every budget, and no
    shorter length is assumed from a longer one or the reverse. No extrapolation.
    """
    if not runs or any(r.get("audio_seconds") is None for r in runs):
        # a clip of unknown length cannot be placed in the range, so nothing can be called supported
        return {"supported_audio_s": None, "measured_lengths_s": [], "rtf_target": rtf_target,
                "vram_budget_mib": vram_budget_mib, "ram_budget_mib": ram_budget_mib,
                "not_installable_reason": "a profiled clip has no known length" if runs else "no clips were profiled"}
    good = []
    for r in sorted(runs, key=lambda r: r["audio_seconds"]):
        ok = bool(r.get("ok")) and r.get("real_time_factor") is not None and r["real_time_factor"] <= rtf_target
        if vram_budget_mib is not None:   # a missing reading cannot pass a VRAM budget
            ok = ok and r.get("peak_vram_mib") is not None and r["peak_vram_mib"] <= vram_budget_mib
        if ram_budget_mib is not None and r.get("peak_ram_mib") is not None:
            ok = ok and r["peak_ram_mib"] <= ram_budget_mib
        if ok:
            good.append(r["audio_seconds"])
        else:
            break  # the first failing length ends the supported range
    return {"supported_audio_s": max(good) if good else None,
            "measured_lengths_s": [r["audio_seconds"] for r in sorted(runs, key=lambda r: r["audio_seconds"])],
            "rtf_target": rtf_target, "vram_budget_mib": vram_budget_mib, "ram_budget_mib": ram_budget_mib}
