"""
Gateway automation on hosts running Docker (client/linux_routing.py): Docker's iptables
FORWARD policy drops whatever ncclient's own nftables table accepts, so ncclient mirrors
its forward rules into DOCKER-USER - and says so when it can't switch IP forwarding on
(read-only /proc/sys in a container).
"""
import subprocess

from client import linux_routing as lr


def test_docker_user_rules_for_exit_and_subnet():
    rules = lr.docker_user_rules(
        [{"route": "0.0.0.0/0"}, {"route": "::/0"}, {"route": "192.168.1.0/24"}, {"route": "fd00::/64"}],
        "nebula1",
        "eth0",
    )
    tag = ["-m", "comment", "--comment", "ncclient", "-j", "ACCEPT"]
    assert rules == [
        ["-i", "nebula1", "-o", "eth0", *tag],
        ["-i", "eth0", "-o", "nebula1", "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", *tag],
        ["-i", "nebula1", "-d", "192.168.1.0/24", *tag],
        ["-s", "192.168.1.0/24", "-o", "nebula1", *tag],
    ]


def test_docker_user_rules_skip_exit_without_uplink():
    assert lr.docker_user_rules([{"route": "0.0.0.0/0"}], "nebula1", None) == []


class _FakeIptables:
    def __init__(self, existing: str = ""):
        self.calls = []
        self.existing = existing

    def __call__(self, argv, **kw):
        self.calls.append(argv[1:])
        if "-L" in argv:
            return subprocess.CompletedProcess(argv, 0, "Chain DOCKER-USER", "")
        if "-S" in argv:
            return subprocess.CompletedProcess(argv, 0, self.existing, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_rules_are_replaced_not_duplicated(monkeypatch):
    existing = (
        "-N DOCKER-USER\n"
        "-A DOCKER-USER -i nebula1 -o eth0 -m comment --comment ncclient -j ACCEPT\n"
        "-A DOCKER-USER -s 10.0.0.0/8 -j DROP\n"  # someone else's rule: untouched
        "-A DOCKER-USER -j RETURN\n"
    )
    fake = _FakeIptables(existing)
    monkeypatch.setattr(lr.shutil, "which", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(lr.subprocess, "run", fake)
    monkeypatch.setattr(lr, "_default_route_iface", lambda: "eth0")
    lr._apply_docker_user_rules([{"route": "0.0.0.0/0"}], "nebula1", None)
    deletes = [c for c in fake.calls if c[1] == "-D"]
    assert deletes == [["-w", "-D", "DOCKER-USER", "-i", "nebula1", "-o", "eth0", "-m", "comment",
                        "--comment", "ncclient", "-j", "ACCEPT"]]
    inserts = [c for c in fake.calls if c[1] == "-I"]
    assert len(inserts) == 2


def test_no_docker_chain_is_a_noop(monkeypatch):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "iptables: No chain/target/match by that name.")

    monkeypatch.setattr(lr.shutil, "which", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(lr.subprocess, "run", run)
    lr._apply_docker_user_rules([{"route": "0.0.0.0/0"}], "nebula1", None)
    assert all("-L" in c for c in calls), "only the chain probes ran"


def test_forwarding_warning_when_proc_sys_is_read_only(monkeypatch):
    logged = []
    real_open = open

    def fake_open(path, mode="r", **kw):
        if str(path).startswith("/proc/sys/"):
            if "w" in mode:
                raise OSError(30, "Read-only file system")
            from io import StringIO
            return StringIO("0\n")
        return real_open(path, mode, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    lr._set_ip_forward([{"route": "0.0.0.0/0"}], logged.append)
    assert len(logged) == 1 and "net.ipv4.ip_forward" in logged[0] and "host" in logged[0]


def test_pipe_get_settings_returns_exit_allow_lan():
    """The Windows app reads the LAN toggle back through the pipe's get_settings allowlist."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "windows" / "pipe_server.py").read_text(encoding="utf-8")
    get_settings = source[source.index("def get_settings"):source.index("def is_enrolled")]
    assert '"exit_allow_lan"' in get_settings
