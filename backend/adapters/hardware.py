"""Read-only resource probes. Missing telemetry stays unknown, never zero."""
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path

GIB = 1024 ** 3


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def memory_values(path: Path) -> dict[str, int]:
    values = {}
    for line in (read_text(path) or "").splitlines():
        key, separator, value = line.partition(":")
        fields = value.split()
        if separator and fields and fields[0].isdigit():
            values[key] = int(fields[0]) * (1024 if fields[1:] == ["kB"] else 1)
    return values


def gpu_devices(sys_root: Path) -> list[dict]:
    devices = []
    for card in sorted((sys_root / "class/drm").glob("card[0-9]*")):
        if not card.name[4:].isdigit():
            continue
        device = card / "device"
        vendor = read_text(device / "vendor")
        model = read_text(device / "device")
        if not vendor or not model:
            continue
        driver_link = device / "driver"
        driver = driver_link.resolve().name if driver_link.is_symlink() else None
        raw_vram = read_text(device / "mem_info_vram_total")
        vram = int(raw_vram) if raw_vram and raw_vram.isdigit() else None
        devices.append({
            "vendor_id": vendor, "device_id": model, "driver": driver,
            "vram_bytes": vram,
            "vram_reason": None if vram is not None else "Dedicated VRAM is not exposed by this driver; shared memory is not dedicated VRAM.",
            "inference_support": "Not tested. Device presence does not establish runtime compatibility.",
        })
    return devices


def profile_hardware(data_dir: Path, *, proc_root=Path("/proc"), sys_root=Path("/sys")) -> dict:
    memory = memory_values(proc_root / "meminfo")
    cpu_lines = (read_text(proc_root / "cpuinfo") or "").splitlines()
    cpu = next((line.split(":", 1)[1].strip() for line in cpu_lines if line.startswith("model name") and ":" in line), None)
    try:
        disk = shutil.disk_usage(data_dir)
        disk_info = {"total_bytes": disk.total, "free_bytes": disk.free, "reason": None}
    except OSError:
        disk_info = {"total_bytes": None, "free_bytes": None, "reason": "Storage telemetry is unavailable."}
    # Container limits can be smaller than host RAM. Report both without inventing
    # a limit when cgroup v2 files are absent or the group is unlimited.
    cgroup = sys_root / "fs/cgroup"
    limit_text = read_text(cgroup / "memory.max")
    current_text = read_text(cgroup / "memory.current")
    limit = int(limit_text) if limit_text and limit_text.isdigit() else None
    current = int(current_text) if current_text and current_text.isdigit() else None
    available = memory.get("MemAvailable")
    if limit is not None and current is not None:
        group_free = max(0, limit - current)
        available = min(available, group_free) if available is not None else group_free
    devices = gpu_devices(sys_root)
    return {
        "schema_version": 1,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "os": {"system": platform.system(), "release": platform.release(), "architecture": platform.machine(),
               "session": os.environ.get("XDG_SESSION_TYPE") or None, "python": platform.python_version()},
        "cpu": {"model": cpu, "logical_cores": os.cpu_count()},
        "memory": {"total_bytes": memory.get("MemTotal"), "available_bytes": memory.get("MemAvailable"),
                   "swap_total_bytes": memory.get("SwapTotal"), "swap_free_bytes": memory.get("SwapFree"),
                   "cgroup_limit_bytes": limit, "cgroup_current_bytes": current,
                   "effective_available_bytes": available,
                   "reason": None if available is not None else "Available memory telemetry is unavailable."},
        "disk": disk_info,
        "gpu": {"devices": devices, "reason": None if devices else "No GPU telemetry is exposed. This does not prove there is no GPU."},
        "execution": {"mode": "cpu", "concurrency": 1, "cloud_enabled": False, "remote_enabled": False,
                      "model": None, "model_reason": "No model selected or benchmarked. No model size is recommended from hardware alone.",
                      "reserve_bytes": 2 * GIB},
        "limitations": ["Resource values are a point-in-time snapshot.",
                         "GPU inference, model fit and full application process-tree memory have not been measured."],
    }
