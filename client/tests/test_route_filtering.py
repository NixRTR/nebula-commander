"""
Tests for the client-side subnet-router/exit-node accept/reject mechanism -
the local device-consent gate on top of the server's per-route "consumers"
authorization (see backend/tests/test_config_generator.py for that half).
See docs/unsafe-routes.md and client/ncclient.py's extract_available_routes/
filter_accepted_routes/validate_new_subnet_route/_route_selection_fingerprint.
"""
import yaml

from client.ncclient import (
    _route_selection_fingerprint,
    extract_available_routes,
    filter_accepted_routes,
    validate_new_subnet_route,
)

RAW_CONFIG = b"""pki:
  ca: |-
    -----BEGIN NEBULA CERTIFICATE-----
    CjwKCkJlYXJkZWRUZWsowoSHzgYwwtKQ7AY6IErZjwe8tfrooBj5liTgJwOP7Qqy
    -----END NEBULA CERTIFICATE-----
  cert: |-
    -----BEGIN NEBULA CERTIFICATE-----
    CmwKBnBhc2NhbBIJgoCQU4D+//8PIgdTZXJ2ZXJzKMOpstUGMMOQt+QGOiBTrege
    -----END NEBULA CERTIFICATE-----
  key: |-
    -----BEGIN NEBULA X25519 PRIVATE KEY-----
    4ThE1GAsSU3VmRjHClYOxKVS/HxhO3SSb49vdmsLMi8=
    -----END NEBULA X25519 PRIVATE KEY-----
tun:
  dev: nebula1
  mtu: 1300
  routes: []
  unsafe_routes:
  - route: 192.168.1.0/24
    via: 10.100.0.17
  - route: 10.50.0.0/16
    via: 10.100.0.22
  - route: 0.0.0.0/0
    via: 10.100.0.30
  - route: ::/0
    via: 10.100.0.30
firewall:
  outbound:
  - port: any
    proto: any
    host: any
  inbound:
  - port: any
    proto: any
    host: any
"""


def test_extract_available_routes_classifies_subnet_vs_exit():
    routes = extract_available_routes(RAW_CONFIG)
    by_route = {r["route"]: r for r in routes}
    assert by_route["192.168.1.0/24"] == {"route": "192.168.1.0/24", "via": "10.100.0.17", "kind": "subnet"}
    assert by_route["0.0.0.0/0"]["kind"] == "exit"
    assert by_route["::/0"]["kind"] == "exit"


def test_filter_keeps_only_accepted_routes():
    filtered = filter_accepted_routes(
        RAW_CONFIG,
        accepted_subnet_routes=[{"route": "192.168.1.0/24", "via": "10.100.0.17"}],
        accepted_exit_node={"via": "10.100.0.30"},
    )
    parsed = yaml.safe_load(filtered)
    kept = {(r["route"], r["via"]) for r in parsed["tun"]["unsafe_routes"]}
    assert kept == {
        ("192.168.1.0/24", "10.100.0.17"),
        ("0.0.0.0/0", "10.100.0.30"),
        ("::/0", "10.100.0.30"),
    }
    # The non-accepted subnet route (10.50.0.0/16) must be gone.
    assert "10.50.0.0/16" not in {r["route"] for r in parsed["tun"]["unsafe_routes"]}


def test_filter_preserves_pki_block_content_through_reserialize():
    filtered = filter_accepted_routes(
        RAW_CONFIG, accepted_subnet_routes=[{"route": "192.168.1.0/24", "via": "10.100.0.17"}], accepted_exit_node=None
    )
    parsed = yaml.safe_load(filtered)
    assert "4ThE1GAsSU3VmRjHClYOxKVS" in parsed["pki"]["key"]
    assert "BEGIN NEBULA X25519 PRIVATE KEY" in parsed["pki"]["key"]


def test_filter_returns_original_bytes_unchanged_when_nothing_is_removed():
    """Accepting everything the server offers must be a byte-for-byte no-op,
    not a reserialize - avoids any reformatting risk on the PKI block when
    there's nothing to actually filter. (Not on Linux with an exit node: there
    the exit entries gain install: false - see the test below.)"""
    filtered = filter_accepted_routes(
        RAW_CONFIG,
        accepted_subnet_routes=[
            {"route": "192.168.1.0/24", "via": "10.100.0.17"},
            {"route": "10.50.0.0/16", "via": "10.100.0.22"},
        ],
        accepted_exit_node={"via": "10.100.0.30"},
        platform="win32",
    )
    assert filtered == RAW_CONFIG


def test_filter_marks_exit_routes_install_false_on_linux_only():
    """On Linux Nebula must not install the exit route itself (its own UDP would be
    routed into the tunnel); client/exit_routing.py installs a policy-routed one."""
    accepted = dict(accepted_subnet_routes=[], accepted_exit_node={"via": "10.100.0.30"})
    linux = yaml.safe_load(filter_accepted_routes(RAW_CONFIG, platform="linux", **accepted))
    exits = [r for r in linux["tun"]["unsafe_routes"] if r["route"] in ("0.0.0.0/0", "::/0")]
    assert len(exits) == 2 and all(r["install"] is False for r in exits)

    windows = yaml.safe_load(filter_accepted_routes(RAW_CONFIG, platform="win32", **accepted))
    assert all("install" not in r for r in windows["tun"]["unsafe_routes"])

    # Subnet routes are never touched.
    subnet = yaml.safe_load(filter_accepted_routes(
        RAW_CONFIG, platform="linux",
        accepted_subnet_routes=[{"route": "192.168.1.0/24", "via": "10.100.0.17"}], accepted_exit_node=None,
    ))
    assert all("install" not in r for r in subnet["tun"]["unsafe_routes"])


def test_fingerprint_changes_with_exit_allow_lan():
    exit_node = {"via": "10.100.0.30"}
    assert _route_selection_fingerprint([], exit_node, True) != _route_selection_fingerprint([], exit_node, False)
    assert _route_selection_fingerprint([], exit_node) == _route_selection_fingerprint([], exit_node, True)


def test_filter_rejecting_everything_yields_empty_unsafe_routes():
    filtered = filter_accepted_routes(RAW_CONFIG, accepted_subnet_routes=[], accepted_exit_node=None)
    parsed = yaml.safe_load(filtered)
    assert parsed["tun"]["unsafe_routes"] == []


def test_validate_new_subnet_route_detects_overlap():
    error = validate_new_subnet_route(
        "192.168.1.128/25", [{"route": "192.168.1.0/24", "via": "10.100.0.17"}]
    )
    assert error is not None
    assert "overlaps" in error


def test_validate_new_subnet_route_allows_non_overlapping():
    error = validate_new_subnet_route(
        "172.16.0.0/16", [{"route": "192.168.1.0/24", "via": "10.100.0.17"}]
    )
    assert error is None


def test_validate_new_subnet_route_rejects_invalid_cidr():
    error = validate_new_subnet_route("not-a-cidr", [])
    assert error is not None


def test_route_selection_fingerprint_stable_and_order_independent():
    fp1 = _route_selection_fingerprint([{"route": "192.168.1.0/24", "via": "10.100.0.17"}], {"via": "10.100.0.30"})
    fp2 = _route_selection_fingerprint([{"route": "192.168.1.0/24", "via": "10.100.0.17"}], {"via": "10.100.0.30"})
    assert fp1 == fp2

    fp_ab = _route_selection_fingerprint([{"route": "A", "via": "1"}, {"route": "B", "via": "2"}], None)
    fp_ba = _route_selection_fingerprint([{"route": "B", "via": "2"}, {"route": "A", "via": "1"}], None)
    assert fp_ab == fp_ba, "fingerprint must not depend on list order"


def test_route_selection_fingerprint_changes_with_selection():
    fp_empty = _route_selection_fingerprint([], None)
    fp_with_route = _route_selection_fingerprint([{"route": "192.168.1.0/24", "via": "10.100.0.17"}], None)
    assert fp_empty != fp_with_route
