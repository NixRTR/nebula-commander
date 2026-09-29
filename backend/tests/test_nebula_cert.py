"""
Tests for signing a host cert that advertises several subnet-router/exit-node routes.

nebula-cert takes the routes as one comma-separated -subnets argument, which the
argument allowlist used to reject ("Argument contains disallowed characters") - so
every exit node (0.0.0.0/0 + ::/0) and any subnet router with 2+ routes failed to
sign. nebula-cert also refuses IPv6 unsafe networks on an IPv4-only host, so ::/0
has to be left out of the cert for IPv4-addressed nodes.
"""
import shutil
import subprocess  # nosec B404 - test runs nebula-cert with fixed args, shell=False
import sys
from pathlib import Path

import pytest

from backend.models import Network, Node
from backend.services.cert_manager import _unsafe_subnets_for_cert
from backend.utils import nebula_cert
from backend.utils.nebula_cert import _to_safe_arg, ca_generate, cert_sign, keygen


def test_comma_separated_list_argument_is_allowed_unchanged():
    assert _to_safe_arg("192.168.1.0/24,0.0.0.0/0") == "192.168.1.0/24,0.0.0.0/0"
    assert _to_safe_arg("servers,laptops") == "servers,laptops"


@pytest.mark.parametrize("arg", ["a;b", "a|b", "$(id)", "a b", "a\nb"])
def test_shell_and_whitespace_characters_are_still_rejected(arg):
    with pytest.raises(ValueError):
        _to_safe_arg(arg)


def test_cert_sign_passes_all_routes_as_one_subnets_argument(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(nebula_cert, "nebula_cert_path", lambda: "nebula-cert")
    monkeypatch.setattr(
        nebula_cert.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0)
    )

    # Relative paths: the allowlist has no backslash, so an absolute tmp_path fails on Windows.
    monkeypatch.chdir(tmp_path)
    cert_sign(
        ca_crt=Path("ca.crt"),
        ca_key=Path("ca.key"),
        name="gateway",
        ip="10.100.0.1",
        out_crt=Path("host.crt"),
        subnet_cidr="10.100.0.0/24",
        unsafe_subnets=["192.168.1.0/24", "0.0.0.0/0"],
    )

    cmd = calls[0]
    assert cmd[cmd.index("-subnets") + 1] == "192.168.1.0/24,0.0.0.0/0"


def _gateway(ip: str, routes: list[str]) -> Node:
    return Node(
        id=1,
        network_id=1,
        hostname="gateway",
        ip_address=ip,
        unsafe_routes=[{"route": r, "source": "manual", "consumers": []} for r in routes],
    )


def test_ipv4_node_cert_leaves_out_ipv6_routes():
    network = Network(id=1, name="net", cert_version=2)
    node = _gateway("10.100.0.1", ["192.168.1.0/24", "0.0.0.0/0", "::/0"])
    assert _unsafe_subnets_for_cert(node, network) == ["192.168.1.0/24", "0.0.0.0/0"]


def test_ipv6_node_on_v2_network_keeps_ipv6_routes():
    network = Network(id=1, name="net", cert_version=2)
    node = _gateway("fd00::1", ["0.0.0.0/0", "::/0"])
    assert _unsafe_subnets_for_cert(node, network) == ["0.0.0.0/0", "::/0"]


def test_v1_network_never_puts_ipv6_routes_in_the_cert():
    network = Network(id=1, name="net", cert_version=1)
    node = _gateway("10.100.0.1", ["0.0.0.0/0", "::/0"])
    assert _unsafe_subnets_for_cert(node, network) == ["0.0.0.0/0"]


@pytest.mark.skipif(shutil.which("nebula-cert") is None, reason="nebula-cert not on PATH")
@pytest.mark.skipif(sys.platform == "win32", reason="the argument allowlist has no backslash, so Windows paths can't be passed")
def test_real_nebula_cert_signs_an_exit_node_with_a_subnet_route(tmp_path):
    """End to end against the real binary: exactly what an IPv4 exit node that also
    routes a LAN produces."""
    ca_generate("test-ca", tmp_path / "ca.crt", tmp_path / "ca.key")
    keygen(tmp_path / "host.pub", tmp_path / "host.key")
    node = _gateway("10.100.0.1", ["192.168.1.0/24", "0.0.0.0/0", "::/0"])

    cert_sign(
        ca_crt=tmp_path / "ca.crt",
        ca_key=tmp_path / "ca.key",
        name="gateway",
        ip="10.100.0.1",
        out_crt=tmp_path / "host.crt",
        in_pub=tmp_path / "host.pub",
        subnet_cidr="10.100.0.0/24",
        unsafe_subnets=_unsafe_subnets_for_cert(node, Network(id=1, name="net", cert_version=2)),
    )

    printed = subprocess.run(  # nosec B603 - fixed args, shell=False
        [shutil.which("nebula-cert"), "print", "-path", str(tmp_path / "host.crt")],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "192.168.1.0/24" in printed
    assert "0.0.0.0/0" in printed
