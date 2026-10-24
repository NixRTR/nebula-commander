"""The SIGTERM handler ignores further SIGTERMs before setting stop_event.

A frozen build often gets SIGTERM twice (systemd signals the cgroup, the PyInstaller
bootloader forwards its own); a second Event.set() from a nested handler deadlocked on
the Event's lock and the service hung until systemd's 90 s stop timeout."""
import signal
import threading

from client import ncclient


def test_handler_ignores_further_sigterm_then_sets_event():
    ev = threading.Event()
    old = signal.getsignal(signal.SIGTERM)
    try:
        h = ncclient._stop_on_signal(ev)
        signal.signal(signal.SIGTERM, h)
        h(signal.SIGTERM, None)
        assert ev.is_set()
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGTERM, old)
