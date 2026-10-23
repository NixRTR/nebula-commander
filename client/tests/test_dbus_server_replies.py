"""
D-Bus server replies (client/linux/dbus_server.py) must match their signatures: Enroll
returned the backend's int node id for an "s" reply, jeepney refused to build it, no
reply was sent, and the desktop app showed "Enroll failed:" after a 35 s timeout although
the device had enrolled (found on a Debian 13 VM).
"""
import pytest

jeepney = pytest.importorskip("jeepney")

from client.linux import dbus_server  # noqa: E402


class _Msg:
    def __init__(self, body):
        self.body = body


def test_enroll_reply_is_a_string_that_jeepney_can_send(monkeypatch):
    monkeypatch.setattr(dbus_server.service_api, "enroll", lambda server, code: 32)
    signature, body = dbus_server._h_enroll("/tmp", _Msg(("https://nc.example", "CODE")))
    assert (signature, body) == ("s", ("32",))
    call = jeepney.new_method_call(
        jeepney.DBusAddress(dbus_server.OBJECT_PATH, bus_name=dbus_server.BUS_NAME, interface=dbus_server.INTERFACE),
        "Enroll", "ss", ("https://nc.example", "CODE"),
    )
    jeepney.new_method_return(call, signature, body)  # raised TypeError before the fix


def test_route_and_setting_changes_wake_the_poll_loop():
    """Picking an exit node in the desktop app took up to a full poll interval (60 s) to
    apply; these calls now wake run_poll_loop's sleep."""
    from client import service_api

    assert {"AcceptExitNode", "RejectExitNode", "AcceptRoute", "RejectRoute", "SetSettings"} <= dbus_server._APPLY_NOW
    assert "GetStatus" not in dbus_server._APPLY_NOW
    service_api.take_poll_now()  # clear
    service_api.request_poll_now()
    assert service_api.take_poll_now() is True
    assert service_api.take_poll_now() is False, "one wake-up per request"


def test_enroll_without_node_id_replies_empty(monkeypatch):
    monkeypatch.setattr(dbus_server.service_api, "enroll", lambda server, code: None)
    assert dbus_server._h_enroll("/tmp", _Msg(("s", "c"))) == ("s", ("",))


def test_per_network_methods_build_valid_replies(monkeypatch):
    """0.8.0 per-network methods: every reply must match its signature (see the Enroll bug
    above), and the pre-0.8.0 methods keep working with several networks enrolled."""
    api = dbus_server.service_api
    monkeypatch.setattr(api, "list_networks", lambda out: [{"id": "a1", "name": "home", "node_id": 3}])
    monkeypatch.setattr(api, "enroll_network", lambda server, code: {"id": "a1", "node_id": 3, "name": "", "hostname": ""})
    monkeypatch.setattr(api, "get_status", lambda out, net=None, first_if_many=True: {"state": "connected", "message": "m"})
    monkeypatch.setattr(api, "get_available_routes", lambda out, net=None, first_if_many=True: [])
    monkeypatch.setattr(api, "get_settings", lambda net=None: {"server": "https://a"})
    monkeypatch.setattr(api, "get_config_yaml", lambda out, net=None, first_if_many=True: "tun: {}\n")
    calls = []
    for name in ("remove_network", "set_settings", "accept_route", "reject_route", "accept_exit_node", "reject_exit_node"):
        monkeypatch.setattr(api, name, lambda *a, _n=name, **k: calls.append((_n, a, k)) or ("10.0.0.0/8", "10.1.0.1"))
    address = jeepney.DBusAddress(dbus_server.OBJECT_PATH, bus_name=dbus_server.BUS_NAME, interface=dbus_server.INTERFACE)
    bodies = {
        "ListNetworks": (), "EnrollNetwork": ("https://a", "C"), "RemoveNetwork": ("a1",),
        "GetStatusForNetwork": ("a1",), "GetAvailableRoutesForNetwork": ("a1",), "GetSettingsForNetwork": ("a1",),
        "SetSettingsForNetwork": ("a1", "{}"), "AcceptRouteForNetwork": ("a1", "10.0.0.0/8", ""),
        "RejectRouteForNetwork": ("a1", "10.0.0.0/8"), "AcceptExitNodeForNetwork": ("a1", "10.1.0.1"),
        "RejectExitNodeForNetwork": ("a1",), "GetConfigYamlForNetwork": ("a1",),
    }
    for member, body in bodies.items():
        handler, _action = dbus_server._METHODS[member]
        signature, reply = handler("/tmp", _Msg(body))
        call = jeepney.new_method_call(address, member, "s" * len(body), body)
        jeepney.new_method_return(call, signature, reply)
    dbus_server._h_accept_route("/tmp", _Msg(("10.0.0.0/8", "")))
    assert ("accept_route", ("/tmp", "10.0.0.0/8", None), {"first_if_many": True}) in calls, \
        "the pre-0.8.0 AcceptRoute uses the first network"
