"""
Tkinter dialogs for Enroll and Settings.
"""
import tkinter as tk
from tkinter import ttk, messagebox

# Default bundled Nebula path (set by tray when available)
DEFAULT_NEBULA_PATH = ""


def get_bundled_nebula_path() -> str:
    """Return path to bundled nebula.exe if available, else empty string."""
    import os
    import sys
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "nebula", "nebula.exe")
    return path if os.path.isfile(path) else ""


def enroll_dialog(parent=None) -> tuple[str, str] | None:
    """
    Show Enroll dialog: server URL and code. Returns (server, code) on OK, None on Cancel.
    When parent is not None (tray): deiconify parent off-screen so Toplevel shows; use wait_window (single mainloop).
    """
    if parent is not None:
        parent.deiconify()
        parent.geometry("1x1+-10000+-10000")
    root = tk.Tk() if parent is None else tk.Toplevel(parent)
    root.title("Nebula Commander – Enroll")
    root.resizable(True, False)
    if parent:
        # Do not set transient(parent): on Windows an off-screen parent can be treated
        # as minimized and the transient dialog would minimize with it (flash then hide).
        root.grab_set()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.update_idletasks()
        root.after(100, lambda: root.attributes("-topmost", False))

    result: list[tuple[str, str] | None] = [None]

    frame = ttk.Frame(root, padding=10)
    frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    ttk.Label(frame, text="Server URL:").grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
    server_var = tk.StringVar(value="https://")
    server_entry = ttk.Entry(frame, textvariable=server_var, width=40)
    server_entry.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="Enrollment code:").grid(row=2, column=0, sticky=tk.W, pady=(0, 2))
    code_var = tk.StringVar()
    code_entry = ttk.Entry(frame, textvariable=code_var, width=20)
    code_entry.grid(row=3, column=0, sticky=tk.W, pady=(0, 12))

    def ok() -> None:
        server = (server_var.get() or "").strip()
        # Read from Entry directly; on Windows paste may not sync to StringVar
        code = (code_entry.get() or code_var.get() or "").strip().upper()
        if not server:
            messagebox.showwarning("Enroll", "Enter server URL.", parent=root)
            return
        if not code:
            messagebox.showwarning("Enroll", "Enter enrollment code.", parent=root)
            return
        result[0] = (server, code)
        root.destroy()

    def cancel() -> None:
        root.destroy()

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=4, column=0, sticky=tk.E, pady=(4, 0))
    ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(btn_frame, text="Enroll", command=ok).pack(side=tk.RIGHT)

    server_entry.focus_set()
    root.protocol("WM_DELETE_WINDOW", cancel)
    if parent is None:
        root.mainloop()
    else:
        try:
            root.wait_window()
        finally:
            parent.withdraw()
    return result[0]


def settings_dialog(
    parent: tk.Tk | None,
    server: str,
    output_dir: str,
    interval: int,
    nebula_path: str,
) -> tuple[str, str, int, str] | None:
    """
    Show Settings dialog. Returns (server, output_dir, interval, nebula_path) on OK, None on Cancel.
    When parent is not None (tray): deiconify parent off-screen so Toplevel shows; use wait_window (single mainloop).
    """
    if parent is not None:
        parent.deiconify()
        parent.geometry("1x1+-10000+-10000")
    root = tk.Tk() if parent is None else tk.Toplevel(parent)
    root.title("Nebula Commander – Settings")
    root.resizable(True, False)
    if parent:
        # Do not set transient(parent): on Windows an off-screen parent can be treated
        # as minimized and the transient dialog would minimize with it (flash then hide).
        root.grab_set()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.update_idletasks()
        root.after(100, lambda: root.attributes("-topmost", False))

    result: list[tuple[str, str, int, str] | None] = [None]

    frame = ttk.Frame(root, padding=10)
    frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    default_nebula = nebula_path or get_bundled_nebula_path()

    ttk.Label(frame, text="Server URL:").grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
    server_var = tk.StringVar(value=server or "https://")
    ttk.Entry(frame, textvariable=server_var, width=40).grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="Output directory (config/certs):").grid(row=2, column=0, sticky=tk.W, pady=(0, 2))
    output_var = tk.StringVar(value=output_dir)
    ttk.Entry(frame, textvariable=output_var, width=40).grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

    ttk.Label(frame, text="Poll interval (seconds):").grid(row=4, column=0, sticky=tk.W, pady=(0, 2))
    interval_var = tk.StringVar(value=str(interval))
    ttk.Entry(frame, textvariable=interval_var, width=10).grid(row=5, column=0, sticky=tk.W, pady=(0, 8))

    ttk.Label(frame, text="Nebula executable path (optional):").grid(row=6, column=0, sticky=tk.W, pady=(0, 2))
    nebula_var = tk.StringVar(value=default_nebula)
    ttk.Entry(frame, textvariable=nebula_var, width=40).grid(row=7, column=0, sticky=(tk.W, tk.E), pady=(0, 12))

    def ok() -> None:
        s = (server_var.get() or "").strip()
        o = (output_var.get() or "").strip()
        i_str = (interval_var.get() or "60").strip()
        try:
            i = int(i_str)
            if i < 10:
                i = 10
            elif i > 3600:
                i = 3600
        except ValueError:
            i = 60
        n = (nebula_var.get() or "").strip()
        if not s:
            messagebox.showwarning("Settings", "Enter server URL.", parent=root)
            return
        result[0] = (s, o or ".", i, n)
        root.destroy()

    def cancel() -> None:
        root.destroy()

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=8, column=0, sticky=tk.E, pady=(4, 0))
    ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(btn_frame, text="Save", command=ok).pack(side=tk.RIGHT)

    root.protocol("WM_DELETE_WINDOW", cancel)
    if parent is None:
        root.mainloop()
    else:
        try:
            root.wait_window()
        finally:
            parent.withdraw()
    return result[0]
