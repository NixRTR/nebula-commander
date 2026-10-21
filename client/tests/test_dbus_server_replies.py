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


def test_enroll_without_node_id_replies_empty(monkeypatch):
    monkeypatch.setattr(dbus_server.service_api, "enroll", lambda server, code: None)
    assert dbus_server._h_enroll("/tmp", _Msg(("s", "c"))) == ("s", ("",))
