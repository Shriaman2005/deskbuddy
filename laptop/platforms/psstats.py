"""PC stats from psutil, shared by windows.py and macos.py: CPU, RAM, swap, battery, network rates, uptime, disk and
(where the OS has one) the load average. No GPU or temperatures. Imports anywhere; psutil is looked up on first use."""
import os
import re
import time

from .base import Sampler as _BaseSampler

LOOPBACK = re.compile(r"loopback|^lo\d*$", re.I)  # Windows "Loopback Pseudo-Interface 1", macOS lo0


def psutil_or_none():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def attempt(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001  (one sensor failing must not blank the others)
        return default


class Sampler:
    """disk_root: the volume whose fill level is shown. load: whether os.getloadavg() means anything here."""

    disk_root = os.sep
    load = False

    def __init__(self):
        self.ps = psutil_or_none()
        self._net = None
        if self.ps:
            attempt(lambda: self.ps.cpu_percent(None))      # the first reading of each is meaningless
            attempt(lambda: self.ps.cpu_percent(None, percpu=True))

    def net(self):
        counters = self.ps.net_io_counters(pernic=True)
        rx = sum(c.bytes_recv for n, c in counters.items() if not LOOPBACK.search(n))
        tx = sum(c.bytes_sent for n, c in counters.items() if not LOOPBACK.search(n))
        t = time.monotonic()
        prev, self._net = self._net, (t, rx, tx)
        if not prev or t == prev[0]:
            return 0, 0
        return max(0, round((rx - prev[1]) / (t - prev[0]))), max(0, round((tx - prev[2]) / (t - prev[0])))

    def battery(self):
        """(percent, charging, {status, minutes_left?}) or (None, None, {}) on a desktop."""
        b = self.ps.sensors_battery()
        if b is None:
            return None, None, {}
        plugged = bool(b.power_plugged)
        full = plugged and round(b.percent) >= 100
        info = {"status": "Full" if full else "Charging" if plugged else "Discharging"}
        if not plugged and isinstance(b.secsleft, (int, float)) and b.secsleft >= 0:
            info["minutes_left"] = round(b.secsleft / 60)
        return round(b.percent), plugged, info

    def sample(self):
        out = _BaseSampler().sample()
        ps = self.ps
        if not ps:
            return out
        vm = attempt(ps.virtual_memory)
        if vm:
            out.update(ram=round(vm.percent), ram_used_gb=round((vm.total - vm.available) / 2**30, 1),
                       ram_total_gb=round(vm.total / 2**30, 1))
        cores = attempt(lambda: ps.cpu_percent(None, percpu=True), [])
        cpu = attempt(lambda: ps.cpu_percent(None))
        out.update(cpu=None if cpu is None else round(cpu), cores=[round(c) for c in cores])
        bat, charging, info = attempt(self.battery, (None, None, {}))
        out.update(battery=bat, charging=charging, bat=info)
        rx_tx = attempt(self.net)
        if rx_tx:
            out.update(net_rx=rx_tx[0], net_tx=rx_tx[1])
        out["uptime"] = attempt(lambda: int(time.time() - ps.boot_time()))
        sw = attempt(ps.swap_memory)
        if sw:
            out["swap"] = round(sw.percent)
        disk = attempt(lambda: ps.disk_usage(self.disk_root))
        if disk:
            out.update(disk=round(disk.percent), disk_free_gb=round(disk.free / 1e9))
        if self.load:
            la = attempt(os.getloadavg)
            if la:
                out["load"] = [round(x, 2) for x in la]
        return out
