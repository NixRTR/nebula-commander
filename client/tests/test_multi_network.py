"""
One ncclient, several networks (0.8.0): settings/token layout and the one-time
conversion of a pre-0.8.0 install, per-network service API calls, the host's single
exit node, and the supervisor that runs one poll loop per network.
"""
import json
import os
import threading
import time

import pytest

from client import config, service_api, token_store


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Settings in tmp_path/config, tokens as files (no keyring), output in tmp_path/out."""
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NEBULA_DEVICE_TOKEN_FILE", str(tmp_path / "state" / "token"))
    monkeypatch.setattr(token_store, "_shared_dpapi_active", lambda: False)
    out = tmp_path / "out"
    out.mkdir()
    return out


def _settings():
    return config.load_settings()


# --- migration ------------------------------------------------------------------------

def test_pre_080_install_is_converted_in_place(host, tmp_path):
    config.save_settings({
        "server": "https://nc.example.com", "node_id": 12, "interval": 30, "accept_dns": True,
        "accepted_subnet_routes": [{"route": "192.168.50.0/24", "via": "10.100.0.5"}],
        "accepted_exit_node": {"via": "10.100.0.21"},
    })
    token_store.set_token("old-token")
    (host / "config.yaml").write_text("tun:\n  dev: nebula1\n")
    (host / "status.json").write_text("{}")

    assert config.migrate_to_enrollments(str(host)) is True
    s = _settings()
    assert "server" not in s and "accepted_exit_node" not in s
    assert s["interval"] == 30 and s["accept_dns"] is True
    (e,) = s["enrollments"]
    assert e["server"] == "https://nc.example.com" and e["node_id"] == 12
    assert e["accepted_subnet_routes"] == [{"route": "192.168.50.0/24", "via": "10.100.0.5"}]
    assert s["exit_node"] == {"enrollment": e["id"], "via": "10.100.0.21"}
    assert token_store.get_token(e["id"]) == "old-token"
    assert token_store.get_token() is None, "the id-less token is gone after the copy"
    net = host / "networks" / e["id"]
    assert (net / "config.yaml").read_text().startswith("tun:") and not (host / "config.yaml").exists()

    assert config.migrate_to_enrollments(str(host)) is False, "idempotent"
    assert len(_settings()["enrollments"]) == 1


def test_nothing_to_convert_on_a_fresh_install(host):
    assert config.migrate_to_enrollments(str(host)) is False
    assert _settings() == {}


# --- per-network API --------------------------------------------------------------------

def _enrolled(*names):
    items = [{"id": f"id{i}", "server": f"https://s{i}.example", "node_id": i, "name": n,
              "accepted_subnet_routes": []} for i, n in enumerate(names)]
    config.save_settings({"enrollments": items, "exit_allow_lan": True})
    for e in items:
        token_store.set_token(f"token-{e['id']}", e["id"])
    return items


def test_network_resolution(host):
    _enrolled("home")
    assert service_api.resolve_network(None)["name"] == "home", "the only network needs no name"
    _enrolled("home", "office")
    with pytest.raises(service_api.ServiceApiError, match="several networks"):
        service_api.resolve_network(None)
    assert service_api.resolve_network(None, first_if_many=True)["name"] == "home"
    assert service_api.resolve_network("OFFICE")["id"] == "id1", "names are case-insensitive"
    assert service_api.resolve_network("id1")["name"] == "office"
    with pytest.raises(service_api.ServiceApiError, match="No enrolled network"):
        service_api.resolve_network("lab")


def _offer(host, eid, routes):
    d = host / "networks" / eid
    d.mkdir(parents=True, exist_ok=True)
    (d / "available-routes.json").write_text(json.dumps(routes))


def test_a_host_has_one_exit_node(host):
    _enrolled("home", "office")
    _offer(host, "id0", [{"route": "0.0.0.0/0", "via": "10.0.0.1", "kind": "exit"}])
    _offer(host, "id1", [{"route": "0.0.0.0/0", "via": "10.1.0.1", "kind": "exit"}])
    service_api.accept_exit_node(str(host), "10.0.0.1", "home")
    service_api.accept_exit_node(str(host), "10.1.0.1", "office")
    assert _settings()["exit_node"] == {"enrollment": "id1", "via": "10.1.0.1"}, "the second replaces the first"
    assert service_api.get_settings("home")["accepted_exit_node"] is None
    assert service_api.get_settings("office")["accepted_exit_node"] == {"via": "10.1.0.1"}
    assert service_api.get_settings("home")["host_exit_active"] is True
    with pytest.raises(service_api.RouteError, match="isn't the one in use"):
        service_api.reject_exit_node(str(host), "home")
    service_api.reject_exit_node(str(host), "office")
    assert _settings()["exit_node"] is None


def test_routes_are_accepted_per_network(host):
    _enrolled("home", "office")
    _offer(host, "id1", [{"route": "192.168.9.0/24", "via": "10.1.0.9", "kind": "subnet"}])
    service_api.accept_route(str(host), "192.168.9.0/24", None, "office")
    assert service_api.get_settings("office")["accepted_subnet_routes"] == [{"route": "192.168.9.0/24", "via": "10.1.0.9"}]
    assert service_api.get_settings("home")["accepted_subnet_routes"] == []
    with pytest.raises(service_api.ServiceApiError, match="several networks"):
        service_api.accept_route(str(host), "192.168.9.0/24", None)


def test_remove_network_forgets_settings_token_and_exit_node(host):
    _enrolled("home", "office")
    config.save_settings({**_settings(), "exit_node": {"enrollment": "id1", "via": "10.1.0.1"}})
    assert service_api.remove_network(str(host), "office") == "id1"
    s = _settings()
    assert [e["id"] for e in s["enrollments"]] == ["id0"]
    assert s["exit_node"] is None
    assert token_store.get_token("id1") is None and token_store.get_token("id0") == "token-id0"


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.ok, self.text = data, status, status < 300, json.dumps(data)

    def json(self):
        return self._data


def test_enroll_adds_a_network_and_reenroll_replaces_the_token(host, monkeypatch):
    import requests
    replies = iter([
        {"device_token": "t-office", "node_id": 7, "hostname": "laptop", "network_name": "office"},
        {"device_token": "t-lab", "node_id": 3, "hostname": "laptop"},
        {"device_token": "t-office-2", "node_id": 7, "hostname": "laptop", "network_name": "office"},
    ])
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: _Resp(next(replies)))
    first = service_api.enroll_network("nc.example.com", "AAA")
    second = service_api.enroll_network("https://other.example", "BBB")
    assert first["id"] != second["id"]
    assert first["name"] == "office" and second["name"] == ""
    again = service_api.enroll_network("https://nc.example.com/", "CCC")
    assert again["id"] == first["id"], "same server and node: re-enroll, not a new network"
    assert token_store.get_token(first["id"]) == "t-office-2"
    assert len(_settings()["enrollments"]) == 2


def test_old_app_calls_use_the_first_network(host):
    _enrolled("home", "office")
    assert service_api.get_settings()["server"] == "https://s0.example"
    _offer(host, "id0", [{"route": "10.9.0.0/16", "via": "10.0.0.9", "kind": "subnet"}])
    assert service_api.get_available_routes(str(host))[0]["route"] == "10.9.0.0/16"


def test_list_networks(host):
    _enrolled("home", "office")
    d = host / "networks" / "id1"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("tun:\n  dev: nc-office\n")
    (d / "status.json").write_text(json.dumps({"state": "connected", "message": "ok", "updated_at": "x"}))
    config.save_settings({**_settings(), "exit_node": {"enrollment": "id1", "via": "10.1.0.1"}})
    nets = {n["id"]: n for n in service_api.list_networks(str(host))}
    assert nets["id1"]["tun_dev"] == "nc-office" and nets["id1"]["status"]["state"] == "connected"
    assert nets["id1"]["exit_node"] == "10.1.0.1" and nets["id0"]["exit_node"] is None
    assert "token" not in json.dumps(nets)


def test_list_networks_overlay_ip_is_live_with_recorded_fallback(host, monkeypatch):
    """The live interface address wins; the one recorded on connecting (which can be
    missing if the interface had no IP yet at that moment) is only a fallback."""
    _enrolled("home", "office")
    for eid, dev, recorded in (("id0", "nc-home", None), ("id1", "nc-office", "10.1.0.9")):
        d = host / "networks" / eid
        d.mkdir(parents=True)
        (d / "config.yaml").write_text(f"tun:\n  dev: {dev}\n")
        (d / "status.json").write_text(json.dumps({"state": "connected", "message": "ok", "overlay_ip": recorded}))
    monkeypatch.setattr(service_api, "_overlay_ip", lambda dev: "10.0.0.5" if dev == "nc-home" else None)
    nets = {n["id"]: n for n in service_api.list_networks(str(host))}
    assert nets["id0"]["overlay_ip"] == "10.0.0.5"
    assert nets["id1"]["overlay_ip"] == "10.1.0.9"


def test_poll_now_reaches_every_loop():
    a, b = [service_api.poll_now_generation()], [service_api.poll_now_generation()]
    service_api.request_poll_now()
    assert service_api.take_poll_now(a) and service_api.take_poll_now(b)
    assert not service_api.take_poll_now(a)


# --- supervisor -------------------------------------------------------------------------

def test_supervisor_runs_one_loop_per_network_and_follows_settings(host, monkeypatch):
    from client import ncclient
    from client.supervisor import Supervisor

    running = {}

    def fake_loop(server, output_dir, interval, nebula_bin, restart_service, stop_event, **kw):
        running[kw["enrollment_id"]] = (server, output_dir)
        kw["status_callback"]("connected", "Config updated")
        stop_event.wait()
        running.pop(kw["enrollment_id"], None)

    monkeypatch.setattr(ncclient, "run_poll_loop", fake_loop)
    _enrolled("home")
    (host / "networks" / "stale").mkdir(parents=True)
    host_statuses = []
    stop = threading.Event()
    sup = Supervisor(str(host), 60, "nebula", None, stop, status_callback=lambda s, m: host_statuses.append((s, m)),
                     reconcile_every=0.05, log=lambda m: None)
    t = threading.Thread(target=sup.run, daemon=True)
    t.start()

    def wait(cond, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    assert wait(lambda: set(running) == {"id0"})
    assert running["id0"] == ("https://s0.example", str(host / "networks" / "id0"))
    assert not (host / "networks" / "stale").exists(), "directories of networks removed earlier are deleted"
    _enrolled("home", "office")
    assert wait(lambda: set(running) == {"id0", "id1"})
    assert wait(lambda: ("connected", "2 networks connected") in host_statuses)
    service_api.remove_network(str(host), "home")
    assert wait(lambda: set(running) == {"id1"})
    assert wait(lambda: not (host / "networks" / "id0").exists())
    stop.set()
    t.join(5)
    assert running == {}


def test_supervisor_moves_a_second_network_off_a_used_port(host):
    import yaml

    from client.supervisor import Supervisor

    sup = Supervisor(str(host), 60, None, None, threading.Event(), log=lambda m: None)
    home, office = sup._port_filter("home", "home"), sup._port_filter("office", "office")
    cfg = b"listen:\n  host: 0.0.0.0\n  port: 4242\n"
    assert home(cfg) == cfg
    assert yaml.safe_load(office(cfg))["listen"]["port"] == 0
    lighthouse = cfg + b"lighthouse:\n  am_lighthouse: true\n"
    assert sup._port_filter("lh", "lh")(lighthouse) == lighthouse, "a lighthouse keeps its port (reported instead)"
    assert office(b"listen:\n  port: 4243\n") == b"listen:\n  port: 4243\n"
