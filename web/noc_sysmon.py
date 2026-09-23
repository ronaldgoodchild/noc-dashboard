"""
REGTeches NOC System Monitor
Local PC Hardware & Process Monitor
Cross-platform: Windows & Linux
Developed by Ronald Goodchild
(c) 2026 REGTeches / Bay Area Tech

Requirements:  pip install psutil
Run:           python noc_sysmon.py
"""

import sys
import os
import platform
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk

try:
    import psutil
except ImportError:
    import subprocess
    print("Installing psutil, please wait...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

# ── App info ─────────────────────────────────────────────────────────────────
VER     = "2.0.0"
AUTHOR  = "Ronald Goodchild"
COPY    = "(c) 2026 REGTeches / Bay Area Tech"
REFRESH = 2000      # UI refresh in ms
TOP_N   = 30        # max processes shown

# ── Colour palette (matches NOC dashboard) ───────────────────────────────────
BG      = "#0a0f1a"
CARD    = "#0f172a"
CARD2   = "#0d1629"
BORDER  = "#1e293b"
HDR     = "#060a14"
TEXT    = "#e2e8f0"
DIM     = "#94a3b8"
ACCENT  = "#3b82f6"
GREEN   = "#22c55e"
RED     = "#ef4444"
YELLOW  = "#eab308"
ORANGE  = "#f97316"

F_UI    = ("Segoe UI",  9)
F_BOLD  = ("Segoe UI",  9, "bold")
F_HEAD  = ("Segoe UI", 10, "bold")
F_TITLE = ("Segoe UI", 11, "bold")
F_MONO  = ("Consolas",  9)
F_SMALL = ("Consolas",  8)
F_SB    = ("Consolas",  8, "bold")


# ── Helpers ──────────────────────────────────────────────────────────────────
def fmt_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def pct_clr(p):
    if p < 60:
        return GREEN
    if p < 80:
        return YELLOW
    return RED


def get_cpu_name():
    try:
        if platform.system() == "Windows":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        with open("/proc/cpuinfo") as f:
            for ln in f:
                if "model name" in ln:
                    return ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"


def make_scroll_frame(parent, bg=BG):
    """Return inner scrollable frame. Attach widgets to the returned frame."""
    outer = tk.Frame(parent, bg=bg)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0)
    vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    inner  = tk.Frame(canvas, bg=bg)
    inner.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    def _scroll(event):
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        else:
            canvas.yview_scroll(1, "units")

    canvas.bind("<MouseWheel>", _scroll)
    canvas.bind("<Button-4>",   _scroll)
    canvas.bind("<Button-5>",   _scroll)

    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    return inner


# ── Bar-graph canvas widget ───────────────────────────────────────────────────
class Bar(tk.Canvas):
    def __init__(self, parent, w=220, h=16, bg=CARD, **kw):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, **kw)
        self._w = w
        self._h = h

    def draw(self, pct: float, clr=None):
        self.delete("all")
        self.create_rectangle(0, 0, self._w, self._h, fill=BORDER, outline="")
        pct = max(0.0, min(float(pct), 100.0))
        if pct > 0:
            bw = max(2, int(self._w * pct / 100))
            self.create_rectangle(0, 0, bw, self._h,
                                  fill=(clr or pct_clr(pct)), outline="")
        self.create_text(
            self._w // 2, self._h // 2,
            text=f"{pct:.1f}%", fill=TEXT, font=F_SB,
        )


# ── Background data collector ────────────────────────────────────────────────
class Collector(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._lock  = threading.Lock()
        self._data  = {}
        self._alive = True
        # warm-up so first reading is non-zero
        psutil.cpu_percent(interval=0.5)
        psutil.cpu_percent(percpu=True, interval=None)

    def snap(self):
        with self._lock:
            return dict(self._data)

    def stop(self):
        self._alive = False

    def run(self):
        while self._alive:
            try:
                d = self._collect()
                with self._lock:
                    self._data = d
            except Exception:
                pass
            time.sleep(1.5)

    def _collect(self):
        d = {}

        # CPU
        d["cpu"]       = psutil.cpu_percent(interval=None)
        d["cpu_cores"] = psutil.cpu_percent(percpu=True)
        f = psutil.cpu_freq()
        d["cpu_info"] = {
            "name": get_cpu_name(),
            "phys": psutil.cpu_count(logical=False) or 0,
            "logi": psutil.cpu_count(logical=True)  or 0,
            "fcur": round(f.current) if f else 0,
            "fmax": round(f.max)     if f else 0,
        }
        temps = []
        try:
            for chip, ee in (psutil.sensors_temperatures() or {}).items():
                for e in ee:
                    if (e.current or 0) > 0:
                        temps.append({
                            "lbl": f"{chip} / {e.label or 'core'}",
                            "cur": e.current,
                            "hi":  e.high or 95.0,
                        })
        except (AttributeError, NotImplementedError):
            pass
        d["cpu_temps"] = temps

        # Memory
        m  = psutil.virtual_memory()
        sw = psutil.swap_memory()
        d["mem"] = {
            "pct":    m.percent,
            "tot":    m.total,
            "used":   m.used,
            "avail":  m.available,
            "cached": getattr(m, "cached",  0),
            "buf":    getattr(m, "buffers", 0),
        }
        d["swap"] = {
            "pct":  sw.percent,
            "tot":  sw.total,
            "used": sw.used,
            "free": sw.free,
        }

        # Disks
        disks = []
        for part in psutil.disk_partitions(all=False):
            if platform.system() == "Windows" and (
                "cdrom" in (part.opts or "") or part.fstype == ""
            ):
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "dev":   part.device,
                    "mount": part.mountpoint,
                    "fs":    part.fstype,
                    "tot":   u.total,
                    "used":  u.used,
                    "free":  u.free,
                    "pct":   u.percent,
                })
            except (PermissionError, OSError):
                pass
        d["disks"] = disks

        try:
            io = psutil.disk_io_counters()
            d["disk_io"] = {
                "rb": io.read_bytes,  "wb": io.write_bytes,
                "rn": io.read_count,  "wn": io.write_count,
            } if io else {}
        except Exception:
            d["disk_io"] = {}

        # Processes
        pl = []
        try:
            for p in psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_percent",
                 "status", "memory_info", "username"]
            ):
                try:
                    mi = p.info.get("memory_info")
                    pl.append({
                        "pid":  p.info["pid"],
                        "name": (p.info["name"] or "?")[:34],
                        "cpu":  p.info.get("cpu_percent")    or 0.0,
                        "mem":  p.info.get("memory_percent") or 0.0,
                        "stat": p.info.get("status") or "",
                        "rss":  mi.rss if mi else 0,
                        "user": (p.info.get("username") or "")[:22],
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        pl.sort(key=lambda x: x["cpu"], reverse=True)
        d["procs"]   = pl[:TOP_N]
        d["n_procs"] = len(psutil.pids())

        # Network
        ifaces = []
        try:
            for name, addrs in psutil.net_if_addrs().items():
                al = []
                for a in addrs:
                    fn = getattr(a.family, "name", str(a.family))
                    if "INET6" in fn:
                        al.append({"t": "IPv6", "addr": a.address})
                    elif "INET" in fn:
                        al.append({
                            "t":    "IPv4",
                            "addr": a.address,
                            "mask": a.netmask or "",
                        })
                    elif any(x in fn for x in
                             ("PACKET", "LINK", "17", "18", "AF_LINK")):
                        al.append({"t": "MAC", "addr": a.address})
                if al:
                    ifaces.append({"name": name, "addrs": al})
        except Exception:
            pass
        d["net_ifaces"] = ifaces

        try:
            nio = psutil.net_io_counters()
            d["net_io"] = {
                "sent": nio.bytes_sent, "recv": nio.bytes_recv,
                "pks":  nio.packets_sent, "pkr": nio.packets_recv,
                "ein":  nio.errin,       "eout": nio.errout,
            }
        except Exception:
            d["net_io"] = {}

        # System
        boot = datetime.fromtimestamp(psutil.boot_time())
        up   = datetime.now() - boot
        hh, r = divmod(up.seconds, 3600)
        mm, _ = divmod(r, 60)
        try:
            users = len(psutil.users())
        except Exception:
            users = 0
        d["sys"] = {
            "host":   platform.node(),
            "os":     f"{platform.system()} {platform.release()}",
            "ver":    platform.version()[:72],
            "arch":   platform.machine(),
            "py":     platform.python_version(),
            "uptime": f"{up.days}d {hh}h {mm}m",
            "boot":   boot.strftime("%Y-%m-%d %H:%M:%S"),
            "users":  users,
        }

        try:
            d["load"] = psutil.getloadavg()
        except (AttributeError, OSError):
            d["load"] = None

        try:
            bat = psutil.sensors_battery()
            d["bat"] = {
                "pct":  bat.percent,
                "plug": bat.power_plugged,
                "secs": bat.secsleft,
            } if bat else None
        except (AttributeError, NotImplementedError):
            d["bat"] = None

        return d


# ── Compact widget (the "box") ────────────────────────────────────────────────
class Widget(tk.Tk):
    """
    Small always-on-top window — appears in the taskbar.
    Shows live CPU / MEM / DISK bars.
    Click the blue button (or double-click) to open full details.
    """

    def __init__(self, on_details):
        super().__init__()
        self._on_details = on_details
        self.title("REGTeches SysMon")
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        # Place bottom-right, above the taskbar
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{sw - 320}+{sh - 265}")

        self._build()
        self.bind("<Double-Button-1>", lambda e: self._on_details())

    def _build(self):
        # Top accent stripe
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        # Header
        hdr = tk.Frame(self, bg=HDR)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  REGTeches SysMon",
                 bg=HDR, fg=ACCENT, font=F_BOLD, pady=6).pack(side="left")
        tk.Label(hdr, text=f"v{VER}  ",
                 bg=HDR, fg=DIM, font=F_SMALL).pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Bars
        body = tk.Frame(self, bg=CARD, padx=12, pady=10)
        body.pack(fill="x")
        self._cpu_bar  = self._bar_row(body, "CPU ")
        self._mem_bar  = self._bar_row(body, "MEM ")
        self._disk_bar = self._bar_row(body, "DISK")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Status line
        self._status = tk.Label(
            self, text="Collecting data...",
            bg=CARD, fg=DIM, font=F_SMALL, pady=4,
        )
        self._status.pack(fill="x", padx=12)

        # Open-details button
        btn_f = tk.Frame(self, bg=CARD, pady=8)
        btn_f.pack(fill="x", padx=12)
        btn = tk.Label(
            btn_f,
            text="  Open Full System Details  >>",
            bg=ACCENT, fg=TEXT, font=F_BOLD,
            cursor="hand2", pady=7,
        )
        btn.pack(fill="x")
        btn.bind("<Button-1>",        lambda e: self._on_details())
        btn.bind("<Double-Button-1>", lambda e: self._on_details())

    def _bar_row(self, parent, label):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=CARD, fg=DIM,
                 font=F_SMALL, width=5, anchor="w").pack(side="left")
        bar = Bar(row, w=205, h=16, bg=CARD)
        bar.pack(side="left", padx=(4, 0))
        return bar

    def update_stats(self, cpu, mem, disk, host):
        self._cpu_bar.draw(cpu)
        self._mem_bar.draw(mem)
        self._disk_bar.draw(disk)
        ts = datetime.now().strftime("%H:%M:%S")
        self._status.config(text=f"  {host}  |  {ts}")


# ── Full detail window ────────────────────────────────────────────────────────
class DetailWin(tk.Toplevel):
    """Six-tab system info window: CPU / Memory / Disks / Processes / Network / System."""

    def __init__(self, master):
        super().__init__(master)
        self.title("REGTeches System Monitor  --  Full Details")
        self.configure(bg=BG)
        self.geometry("990x720")
        self.minsize(720, 520)
        self._sort_cpu = True

        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 990) // 2
        y = (self.winfo_screenheight() - 720) // 2
        self.geometry(f"990x720+{x}+{y}")

        self._apply_styles()
        self._build()

    # ── ttk dark styles ───────────────────────────────────────────────────────
    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook",
                    background=BG, borderwidth=0, tabmargins=[0, 0, 0, 0])
        s.configure("TNotebook.Tab",
                    background=CARD, foreground=DIM,
                    padding=[14, 7], font=F_UI, borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", BORDER), ("active", CARD2)],
              foreground=[("selected", TEXT),   ("active", TEXT)])
        s.configure("Treeview",
                    background=CARD, foreground=TEXT,
                    fieldbackground=CARD, rowheight=26,
                    font=F_MONO, borderwidth=0, relief="flat")
        s.configure("Treeview.Heading",
                    background=BORDER, foreground=TEXT,
                    font=F_BOLD, relief="flat", borderwidth=0)
        s.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])
        s.configure("Vertical.TScrollbar",
                    background=BORDER, troughcolor=BG,
                    arrowcolor=DIM, borderwidth=0)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build(self):
        # Header bar
        hdr = tk.Frame(self, bg=HDR)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  REGTeches NOC  --  System Monitor",
                 bg=HDR, fg=ACCENT, font=F_TITLE, padx=14, pady=8).pack(side="left")
        self._hdr_info = tk.Label(hdr, text="", bg=HDR, fg=DIM, font=F_UI, padx=14)
        self._hdr_info.pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._t_cpu  = self._add_tab("  CPU")
        self._t_mem  = self._add_tab("  Memory")
        self._t_disk = self._add_tab("  Disks")
        self._t_proc = self._add_tab("  Processes")
        self._t_net  = self._add_tab("  Network")
        self._t_sys  = self._add_tab("  System")

        self._build_proc_tab()

        # Footer
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        self._footer = tk.Label(
            self, text="", bg=HDR, fg=DIM, font=F_SMALL, pady=4,
        )
        self._footer.pack(side="bottom", fill="x")
        self.bind("<Escape>", lambda e: self.destroy())

    def _add_tab(self, title):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text=title)
        return make_scroll_frame(tab)

    # ── Section helpers ───────────────────────────────────────────────────────
    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(f, text=title, bg=BG, fg=ACCENT, font=F_HEAD).pack(side="left")
        tk.Frame(f, bg=BORDER, height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=7,
        )

    def _kv(self, parent, key, val, vc=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=16, pady=1)
        tk.Label(row, text=key, bg=CARD, fg=DIM, font=F_UI,
                 width=24, anchor="w").pack(side="left", padx=(10, 0), pady=4)
        tk.Label(row, text=str(val), bg=CARD, fg=vc or TEXT,
                 font=F_MONO).pack(side="left", padx=4)

    def _bar_row(self, parent, label, pct, detail="", bar_w=340):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=16, pady=2)
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=F_UI,
                 width=22, anchor="w").pack(side="left", padx=(10, 4), pady=6)
        b = Bar(row, w=bar_w, h=18, bg=CARD)
        b.draw(pct)
        b.pack(side="left")
        if detail:
            tk.Label(row, text=detail, bg=CARD, fg=DIM,
                     font=F_SMALL).pack(side="left", padx=6)

    def _clear(self, tab):
        for w in tab.winfo_children():
            w.destroy()

    # ── CPU tab ───────────────────────────────────────────────────────────────
    def update_cpu(self, d):
        self._clear(self._t_cpu)
        pct  = d.get("cpu", 0)
        info = d.get("cpu_info", {})

        self._section(self._t_cpu, "Overview")
        self._bar_row(self._t_cpu, "Overall CPU Usage", pct)
        self._kv(self._t_cpu, "Processor",       info.get("name", "?"))
        self._kv(self._t_cpu, "Physical Cores",  info.get("phys", "?"))
        self._kv(self._t_cpu, "Logical Cores",   info.get("logi", "?"))
        if info.get("fcur"):
            self._kv(self._t_cpu, "Current Freq", f"{info['fcur']:,} MHz")
        if info.get("fmax"):
            self._kv(self._t_cpu, "Max Freq",     f"{info['fmax']:,} MHz")

        cores = d.get("cpu_cores", [])
        if cores:
            self._section(self._t_cpu, f"Per-Core  ({len(cores)} cores)")
            grid = tk.Frame(self._t_cpu, bg=BG)
            grid.pack(fill="x", padx=16, pady=4)
            for i, cp in enumerate(cores):
                col = i % 2
                cell = tk.Frame(grid, bg=CARD)
                cell.grid(row=i // 2, column=col,
                          padx=4, pady=2, sticky="ew")
                grid.columnconfigure(col, weight=1)
                tk.Label(cell, text=f"Core {i:2d}", bg=CARD, fg=DIM,
                         font=F_SMALL, width=7, anchor="w").pack(
                             side="left", padx=(8, 4), pady=4)
                b = Bar(cell, w=160, h=14, bg=CARD)
                b.draw(cp)
                b.pack(side="left")

        temps = d.get("cpu_temps", [])
        if temps:
            self._section(self._t_cpu, "Temperatures")
            for t in temps:
                clr = GREEN if t["cur"] < 60 else (YELLOW if t["cur"] < 80 else RED)
                self._kv(self._t_cpu, t["lbl"],
                         f"{t['cur']:.1f}C  (max {t['hi']:.0f}C)", clr)

    # ── Memory tab ────────────────────────────────────────────────────────────
    def update_mem(self, d):
        self._clear(self._t_mem)
        mem  = d.get("mem",  {})
        swap = d.get("swap", {})

        self._section(self._t_mem, "RAM")
        if mem:
            tot = mem["tot"]  / 2**30
            use = mem["used"] / 2**30
            avi = mem["avail"] / 2**30
            self._bar_row(self._t_mem, "RAM Used", mem["pct"],
                          f"{use:.2f} GB / {tot:.2f} GB")
            self._kv(self._t_mem, "Total",     f"{tot:.2f} GB")
            self._kv(self._t_mem, "Used",      f"{use:.2f} GB",
                     RED if mem["pct"] > 85 else TEXT)
            self._kv(self._t_mem, "Available", f"{avi:.2f} GB", GREEN)
            if mem.get("cached"):
                self._kv(self._t_mem, "Cached",
                         f"{mem['cached']/2**30:.2f} GB")
            if mem.get("buf"):
                self._kv(self._t_mem, "Buffers",
                         f"{mem['buf']/2**30:.2f} GB")

        self._section(self._t_mem, "Swap / Page File")
        if swap and swap.get("tot", 0) > 0:
            tot = swap["tot"]  / 2**30
            use = swap["used"] / 2**30
            fre = swap["free"] / 2**30
            self._bar_row(self._t_mem, "Swap Used", swap["pct"],
                          f"{use:.2f} GB / {tot:.2f} GB")
            self._kv(self._t_mem, "Total", f"{tot:.2f} GB")
            self._kv(self._t_mem, "Used",  f"{use:.2f} GB")
            self._kv(self._t_mem, "Free",  f"{fre:.2f} GB", GREEN)
        else:
            self._kv(self._t_mem, "Swap", "Not configured / 0 bytes")

    # ── Disks tab ─────────────────────────────────────────────────────────────
    def update_disks(self, d):
        self._clear(self._t_disk)
        for disk in d.get("disks", []):
            self._section(
                self._t_disk,
                f"  {disk['dev']}   >>   {disk['mount']}",
            )
            self._bar_row(
                self._t_disk, "Used Space", disk["pct"],
                f"{disk['used']/2**30:.1f} GB  /  {disk['tot']/2**30:.1f} GB",
            )
            self._kv(self._t_disk, "File System", disk.get("fs", "?"))
            self._kv(self._t_disk, "Total",
                     f"{disk['tot']/2**30:.2f} GB")
            self._kv(self._t_disk, "Used",
                     f"{disk['used']/2**30:.2f} GB",
                     RED if disk["pct"] > 85 else TEXT)
            self._kv(self._t_disk, "Free",
                     f"{disk['free']/2**30:.2f} GB", GREEN)

        dio = d.get("disk_io", {})
        if dio:
            self._section(self._t_disk, "Disk I/O  (since boot)")
            self._kv(self._t_disk, "Total Read",    fmt_bytes(dio.get("rb", 0)))
            self._kv(self._t_disk, "Total Written", fmt_bytes(dio.get("wb", 0)))
            self._kv(self._t_disk, "Read Ops",      f"{dio.get('rn',0):,}")
            self._kv(self._t_disk, "Write Ops",     f"{dio.get('wn',0):,}")

    # ── Processes tab ─────────────────────────────────────────────────────────
    def _build_proc_tab(self):
        hdr = tk.Frame(self._t_proc, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(hdr, text="Top Processes", bg=BG, fg=ACCENT,
                 font=F_HEAD).pack(side="left")
        self._proc_count = tk.Label(hdr, text="", bg=BG, fg=DIM, font=F_SMALL)
        self._proc_count.pack(side="right")

        sort_f = tk.Frame(self._t_proc, bg=BG)
        sort_f.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(sort_f, text="Sort by:", bg=BG, fg=DIM, font=F_SMALL).pack(side="left")
        self._sb_cpu = tk.Label(sort_f, text=" CPU% ", bg=ACCENT, fg=TEXT,
                                font=F_SB, cursor="hand2", padx=4, pady=2)
        self._sb_cpu.pack(side="left", padx=4)
        self._sb_cpu.bind("<Button-1>", lambda e: self._sort_procs("cpu"))
        self._sb_mem = tk.Label(sort_f, text=" MEM% ", bg=BORDER, fg=DIM,
                                font=F_SB, cursor="hand2", padx=4, pady=2)
        self._sb_mem.pack(side="left")
        self._sb_mem.bind("<Button-1>", lambda e: self._sort_procs("mem"))

        tf = tk.Frame(self._t_proc, bg=BG)
        tf.pack(fill="both", expand=True, padx=16, pady=4)
        cols = ("pid", "name", "cpu", "mem", "rss", "status", "user")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings", height=22)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        for cid, head, w, anc in [
            ("pid",    "PID",     60,  "e"),
            ("name",   "Process", 210, "w"),
            ("cpu",    "CPU %",    70, "e"),
            ("mem",    "MEM %",    70, "e"),
            ("rss",    "Memory",   90, "e"),
            ("status", "Status",   80, "w"),
            ("user",   "User",    130, "w"),
        ]:
            self._tree.heading(cid, text=head,
                               command=lambda c=cid: self._tree_sort(c))
            self._tree.column(cid, width=w, anchor=anc, stretch=False)

        self._tree.tag_configure("even",    background=CARD)
        self._tree.tag_configure("odd",     background=CARD2)
        self._tree.tag_configure("hi_cpu",  foreground=RED)
        self._tree.tag_configure("med_cpu", foreground=YELLOW)
        self._tree.tag_configure("hi_mem",  foreground=ORANGE)

        menu = tk.Menu(self._tree, tearoff=0, bg=CARD, fg=TEXT,
                       activebackground=ACCENT)
        menu.add_command(label="Copy PID",  command=self._copy_pid)
        menu.add_command(label="Copy Name", command=self._copy_name)
        if platform.system() == "Windows":
            menu.add_separator()
            menu.add_command(label="Open Task Manager",
                             command=lambda: os.startfile("taskmgr"))
        self._tree.bind("<Button-3>",
                        lambda e: (self._tree.selection_set(
                            self._tree.identify_row(e.y)),
                            menu.post(e.x_root, e.y_root)))

        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._proc_data = []

    def _sort_procs(self, by):
        self._sort_cpu = (by == "cpu")
        self._sb_cpu.config(bg=ACCENT if self._sort_cpu  else BORDER,
                            fg=TEXT   if self._sort_cpu  else DIM)
        self._sb_mem.config(bg=ACCENT if not self._sort_cpu else BORDER,
                            fg=TEXT   if not self._sort_cpu else DIM)
        self._refresh_tree()

    def _tree_sort(self, col):
        self._sort_procs("cpu" if col == "cpu" else "mem")

    def _refresh_tree(self):
        procs = sorted(self._proc_data,
                       key=lambda x: x["cpu" if self._sort_cpu else "mem"],
                       reverse=True)
        self._tree.delete(*self._tree.get_children())
        for i, p in enumerate(procs):
            tags = ["even" if i % 2 == 0 else "odd"]
            if p["cpu"] > 50:   tags.append("hi_cpu")
            elif p["cpu"] > 20: tags.append("med_cpu")
            if p["mem"] > 20:   tags.append("hi_mem")
            self._tree.insert("", "end", iid=str(p["pid"]), tags=tags,
                               values=(
                                   p["pid"],
                                   p["name"],
                                   f"{p['cpu']:.1f}%",
                                   f"{p['mem']:.1f}%",
                                   fmt_bytes(p["rss"]).strip(),
                                   p["stat"],
                                   p["user"],
                               ))

    def _copy_pid(self):
        sel = self._tree.selection()
        if sel:
            self.clipboard_clear()
            self.clipboard_append(self._tree.item(sel[0], "values")[0])

    def _copy_name(self):
        sel = self._tree.selection()
        if sel:
            self.clipboard_clear()
            self.clipboard_append(self._tree.item(sel[0], "values")[1])

    def update_procs(self, d):
        self._proc_data = d.get("procs", [])
        n = d.get("n_procs", 0)
        self._proc_count.config(
            text=f"Showing {len(self._proc_data)} of {n} total")
        self._refresh_tree()

    # ── Network tab ───────────────────────────────────────────────────────────
    def update_net(self, d):
        self._clear(self._t_net)
        self._section(self._t_net, "Network Interfaces")
        for iface in d.get("net_ifaces", []):
            for a in iface["addrs"]:
                t = a["t"]
                if t == "IPv4":
                    self._kv(self._t_net, f"{iface['name']}  IPv4", a["addr"])
                    if a.get("mask"):
                        self._kv(self._t_net, f"{iface['name']}  Netmask",
                                 a["mask"])
                elif t == "IPv6":
                    self._kv(self._t_net, f"{iface['name']}  IPv6",
                             a["addr"].split("%")[0])
                elif t == "MAC":
                    self._kv(self._t_net, f"{iface['name']}  MAC", a["addr"])

        nio = d.get("net_io", {})
        if nio:
            self._section(self._t_net, "I/O Statistics  (since boot)")
            self._kv(self._t_net, "Bytes Sent",     fmt_bytes(nio.get("sent", 0)))
            self._kv(self._t_net, "Bytes Received", fmt_bytes(nio.get("recv", 0)))
            self._kv(self._t_net, "Packets Sent",   f"{nio.get('pks',0):,}")
            self._kv(self._t_net, "Packets Recv",   f"{nio.get('pkr',0):,}")
            self._kv(self._t_net, "Errors In",
                     str(nio.get("ein", 0)),
                     RED if nio.get("ein", 0) > 0 else TEXT)
            self._kv(self._t_net, "Errors Out",
                     str(nio.get("eout", 0)),
                     RED if nio.get("eout", 0) > 0 else TEXT)

    # ── System tab ────────────────────────────────────────────────────────────
    def update_sys(self, d):
        self._clear(self._t_sys)
        info = d.get("sys",  {})
        load = d.get("load", None)
        bat  = d.get("bat",  None)

        self._section(self._t_sys, "Machine")
        self._kv(self._t_sys, "Hostname",        info.get("host", "?"))
        self._kv(self._t_sys, "Operating System",info.get("os",   "?"))
        self._kv(self._t_sys, "OS Version",      info.get("ver",  "?"))
        self._kv(self._t_sys, "Architecture",    info.get("arch", "?"))
        self._kv(self._t_sys, "Python",          info.get("py",   "?"))

        self._section(self._t_sys, "Uptime")
        self._kv(self._t_sys, "System Uptime",
                 info.get("uptime", "?"), GREEN)
        self._kv(self._t_sys, "Last Boot",       info.get("boot", "?"))
        self._kv(self._t_sys, "Users Logged In", str(info.get("users", 0)))

        if load is not None:
            self._section(self._t_sys, "Load Average  (Linux)")
            self._kv(self._t_sys, " 1 min",  f"{load[0]:.2f}")
            self._kv(self._t_sys, " 5 min",  f"{load[1]:.2f}")
            self._kv(self._t_sys, "15 min",  f"{load[2]:.2f}")

        if bat:
            self._section(self._t_sys, "Battery")
            clr    = GREEN if bat["pct"] > 40 else (YELLOW if bat["pct"] > 20 else RED)
            status = "Charging" if bat["plug"] else "On Battery"
            self._bar_row(self._t_sys, "Battery Level", bat["pct"],
                          detail=status, bar_w=280)
            self._kv(self._t_sys, "Status", status, clr)
            if bat["secs"] and bat["secs"] > 0 and not bat["plug"]:
                hh, r = divmod(int(bat["secs"]), 3600)
                mm, _ = divmod(r, 60)
                self._kv(self._t_sys, "Time Remaining", f"{hh}h {mm}m", clr)

        self._section(self._t_sys, "About")
        self._kv(self._t_sys, "App",       "REGTeches NOC System Monitor")
        self._kv(self._t_sys, "Version",   VER)
        self._kv(self._t_sys, "Author",    AUTHOR)
        self._kv(self._t_sys, "Copyright", COPY)

    # ── Master refresh ────────────────────────────────────────────────────────
    def refresh(self, data: dict):
        if not data:
            return
        sys_info = data.get("sys", {})
        self._hdr_info.config(
            text=f"  {sys_info.get('host','?')}  |  {sys_info.get('os','')}  "
        )
        tab = self.nb.index(self.nb.select())
        self.update_procs(data)
        if tab == 0:
            self.update_cpu(data)
        elif tab == 1:
            self.update_mem(data)
        elif tab == 2:
            self.update_disks(data)
        elif tab == 4:
            self.update_net(data)
        elif tab == 5:
            self.update_sys(data)
        self.nb.bind("<<NotebookTabChanged>>",
                     lambda e: self._on_tab_change(data))
        ts = datetime.now().strftime("%H:%M:%S")
        self._footer.config(
            text=f"  {COPY}  |  {AUTHOR}  |  v{VER}  |  Updated {ts}  "
        )

    def _on_tab_change(self, data):
        tab = self.nb.index(self.nb.select())
        if tab == 0:   self.update_cpu(data)
        elif tab == 1: self.update_mem(data)
        elif tab == 2: self.update_disks(data)
        elif tab == 4: self.update_net(data)
        elif tab == 5: self.update_sys(data)


# ── Main app controller ───────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.collector  = Collector()
        self.collector.start()
        self.detail_win = None
        self.widget     = Widget(self._open_detail)
        self._schedule()

    def _open_detail(self):
        try:
            if self.detail_win and self.detail_win.winfo_exists():
                self.detail_win.lift()
                self.detail_win.focus_force()
                return
        except tk.TclError:
            pass
        self.detail_win = DetailWin(self.widget)
        data = self.collector.snap()
        if data:
            self.detail_win.refresh(data)

    def _schedule(self):
        self._tick()
        self.widget.after(REFRESH, self._schedule)

    def _tick(self):
        data = self.collector.snap()
        if not data:
            return
        cpu   = data.get("cpu", 0)
        mem   = data.get("mem", {}).get("pct", 0)
        disks = data.get("disks", [])
        disk  = (sum(d["pct"] for d in disks) / len(disks)) if disks else 0
        host  = data.get("sys", {}).get("host", "localhost")
        try:
            self.widget.update_stats(cpu, mem, disk, host)
        except tk.TclError:
            pass
        try:
            if self.detail_win and self.detail_win.winfo_exists():
                self.detail_win.refresh(data)
        except tk.TclError:
            self.detail_win = None

    def run(self):
        try:
            self.widget.mainloop()
        finally:
            self.collector.stop()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().run()


if __name__ == "__main__":
    main()
