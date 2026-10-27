"""
Nebula Commander Linux desktop app: a GTK4 + libadwaita (Adw) native GUI for
the ncclient systemd service (see client/ncclient.py's `install`/`run`
subcommands), which does the actual polling/config/cert/DNS/Nebula-process
work as root. This process itself runs unprivileged, as a normal user
session app - no elevation, no daemon of its own.

Why GTK4/libadwaita (this used to be a plain Tkinter app): Tkinter's default
widget set looks dated on every desktop and libadwaita is the thing that
actually gives a native, modern GNOME HIG look - the same reasoning that
drove the Windows app to WinUI3 rather than WinForms. The tradeoff is
packaging: GTK/PyGObject is well known to freeze poorly with PyInstaller
(the same reason a tray-icon/AppIndicator approach was avoided earlier in
this project's history), so this app is no longer distributed as a single
frozen binary. Instead the deb/rpm packages ship this as plain Python
source and declare python3-gi + gir1.2-gtk-4.0 + gir1.2-adw-1 as native
package dependencies - the standard, well-supported way GTK apps are
distributed via apt/dnf/zypper. This is *better*, not worse, for the
Flatpak build specifically: org.gnome.Platform already bundles GTK4 and
libadwaita, so no extra runtime needs bundling there at all. Running a
GTK4/libadwaita app on KDE/XFCE/etc. is completely normal (the same way
GNOME apps commonly run on non-GNOME desktops) - it renders with the
Adwaita look rather than matching the native toolkit, which is expected
and not a functionality concern.

API surface is deliberately restricted to what's available in libadwaita
1.2 (Debian 12's shipped version - verified: 1.2.2 - is the oldest target
across Debian 12+/Ubuntu 24.04+/Fedora/openSUSE, all of which ship newer).
Confirmed present at 1.2.2: Adw.ApplicationWindow, Adw.HeaderBar,
Adw.ViewStack/Adw.ViewSwitcherTitle, Adw.PreferencesPage/Group,
Adw.ActionRow, Adw.EntryRow, Adw.ComboRow, Adw.ToastOverlay/Adw.Toast,
Adw.MessageDialog. Deliberately NOT used because they need libadwaita
1.3/1.4/1.5 (confirmed absent at 1.2.2): Adw.ToolbarView, Adw.Banner,
Adw.SwitchRow, Adw.SpinRow, Adw.AlertDialog. Switch/spin-button "rows" are
built manually as Adw.ActionRow + a suffix widget instead - the standard
pre-1.4 pattern, still perfectly valid on newer libadwaita too.

No tray icon, no persistent on-screen indicator - see git history/project
notes for why (GNOME Shell has no built-in tray support; a literal
"permanent notification" doesn't work either). Transient notifications on
real state changes come from client/linux/notify.py; this window handles
everything needing real interaction - enroll, settings, the route
accept/reject picker.

One device can be enrolled in several networks (0.8.0+). The Networks page lists
them (one row each: name, server, overlay IP, state, exit node in use) with the
service controls; picking one opens its detail - status, subnet routes, exit node,
config - with Remove. "Add network" enrolls in another one. A host has one exit
node, so picking one in a network replaces another network's. Against a service from
before 0.8.0 (no ListNetworks) the app shows its single network as before.

Run from repo root: python -m client.linux.desktop
"""
from __future__ import annotations

import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402


def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # client/linux -> client -> repo root
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_path()

# All state (status/settings/routes/enroll/config) goes through the D-Bus
# service client/linux/dbus_server.py exposes from inside the privileged
# `ncclient run` process - no direct file access, no client.config/
# client.token_store/client.ncclient import here at all (see dbus_client.py's
# module docstring for the full rationale: this is what lets the Flatpak
# build drop --filesystem=/var/lib/ncclient:rw entirely, and what keeps the
# enrollment token out of this unprivileged process).
from client.linux import autostart, dbus_client, notify, service_control  # noqa: E402

APP_ID = "org.beardedtek.NebulaCommander"
POLL_MS = 3000
_NONE_EXIT_NODE = "None"


def _action_row_with_suffix(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget, activatable: bool = True) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title)
    row.add_suffix(widget)
    if activatable:
        row.set_activatable_widget(widget)
    group.add(row)
    return row


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Nebula Commander", default_width=680, default_height=620)

        self._prev_combo: tuple[str, str] | None = None
        # Network shown in the detail view: an id from list_networks(), or None for a
        # pre-0.8.0 service (its only network, through the calls without a network).
        self.current_network: "str | None" = None
        self._networks: list[dict] = []
        self._networks_fingerprint: object = None
        self._network_rows: list[Gtk.Widget] = []
        self._prev_network_states: dict = {}
        self._prev_route_keys: set[tuple] = set()
        self._routes_fingerprint: object = None
        self._route_rows: list[Adw.ActionRow] = []
        self._exit_node_vias: list[str | None] = [None]
        self._suspend_exit_signal = False
        self._update_ticks = 0

        self.toast_overlay = Adw.ToastOverlay()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.view_stack = Adw.ViewStack()
        switcher_title = Adw.ViewSwitcherTitle(stack=self.view_stack, title="Nebula Commander")
        header = Adw.HeaderBar()
        header.set_title_widget(switcher_title)
        outer.append(header)
        outer.append(self.view_stack)

        self.toast_overlay.set_child(outer)
        self.set_content(self.toast_overlay)

        # Networks tab: the list, and one network's detail in place of it.
        self.networks_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.networks_stack.add_named(self._build_networks_page(), "list")
        self.networks_stack.add_named(self._build_status_page(), "detail")
        enroll_page = self._build_enroll_page()
        settings_page = self._build_settings_page()

        self.view_stack.add_titled(self.networks_stack, "status", "Networks").set_icon_name("network-vpn-symbolic")
        self.view_stack.add_titled(enroll_page, "enroll", "Add network").set_icon_name("list-add-symbolic")
        self.view_stack.add_titled(settings_page, "settings", "Settings").set_icon_name("preferences-system-symbolic")

        GLib.timeout_add(POLL_MS, self._poll_tick)
        self._poll_tick()

    # ---- Networks page ----

    def _build_networks_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        svc_group = Adw.PreferencesGroup(title="Service")
        page.add(svc_group)
        self.service_row = Adw.ActionRow(title="Unknown")
        btn_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        start_btn = Gtk.Button(label="Start")
        start_btn.connect("clicked", lambda b: self._service_action(service_control.start))
        stop_btn = Gtk.Button(label="Stop")
        stop_btn.connect("clicked", lambda b: self._service_action(service_control.stop))
        restart_btn = Gtk.Button(label="Restart")
        restart_btn.connect("clicked", lambda b: self._service_action(service_control.restart))
        for b in (start_btn, stop_btn, restart_btn):
            btn_box.append(b)
        self.service_row.add_suffix(btn_box)
        svc_group.add(self.service_row)

        self.networks_group = Adw.PreferencesGroup(
            title="Networks",
            description="Each network this device is enrolled in. Open one for its routes and exit node.",
        )
        add_btn = Gtk.Button(label="Add network", valign=Gtk.Align.CENTER, css_classes=["flat"])
        add_btn.connect("clicked", lambda b: self.view_stack.set_visible_child_name("enroll"))
        self.networks_group.set_header_suffix(add_btn)
        page.add(self.networks_group)
        return page

    def _refresh_networks(self, svc_state: str) -> None:
        """Rebuild the network rows when anything shown on them changed."""
        networks = dbus_client.list_networks() if svc_state == service_control.ServiceState.RUNNING else None
        if networks is None:
            # Stopped, unreachable, or a pre-0.8.0 service: one row for "this device".
            status = dbus_client.get_status() if svc_state == service_control.ServiceState.RUNNING else {}
            networks = [{"id": None, "name": "This device", "server": "", "overlay_ip": "", "exit_node": None,
                         "status": status}] if status.get("state") not in (None, "unknown") else []
        self._networks = networks
        fingerprint = json.dumps(networks, sort_keys=True, default=str)
        if fingerprint == self._networks_fingerprint:
            return
        self._networks_fingerprint = fingerprint
        for row in self._network_rows:
            self.networks_group.remove(row)
        self._network_rows.clear()
        if not networks:
            row = Adw.ActionRow(title="Not enrolled in any network", subtitle="Use Add network with a code from Nebula Commander")
            self.networks_group.add(row)
            self._network_rows.append(row)
        for n in networks:
            state = ((n.get("status") or {}).get("state") or "unknown").capitalize()
            details = [x for x in (n.get("overlay_ip"), n.get("server")) if x]
            if n.get("exit_node"):
                details.append(f"exit node via {n['exit_node']}")
            row = Adw.ActionRow(title=n.get("name") or n.get("id") or "Network", subtitle=" - ".join(details),
                                activatable=True)
            row.add_suffix(Gtk.Label(label=state, css_classes=["dim-label"]))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, nid=n.get("id"): self._open_network(nid))
            self.networks_group.add(row)
            self._network_rows.append(row)
        if self.networks_stack.get_visible_child_name() == "detail" and self.current_network not in [n.get("id") for n in networks]:
            self._show_network_list()  # the open network was removed (here or elsewhere)

    def _open_network(self, network: "str | None") -> None:
        self.current_network = network
        self._routes_fingerprint = None
        self._exit_node_vias = [None]
        self._prev_route_keys = set()
        n = next((x for x in self._networks if x.get("id") == network), {})
        self.detail_title_row.set_title(n.get("name") or network or "This device")
        self.detail_title_row.set_subtitle(" - ".join(x for x in (n.get("server"), n.get("tun_dev")) if x))
        self.remove_network_btn.set_visible(network is not None)
        self.networks_stack.set_visible_child_name("detail")
        self._refresh_detail()

    def _show_network_list(self) -> None:
        self.networks_stack.set_visible_child_name("list")

    def _on_remove_network(self, _button: Gtk.Button) -> None:
        network = self.current_network
        if network is None:
            return
        name = self.detail_title_row.get_title()
        dialog = Adw.MessageDialog(
            heading=f"Leave {name}?", transient_for=self, modal=True,
            body="Nebula stops for this network and the device forgets its token. "
                 "Joining again needs a new enrollment code.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Leave network")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "remove":
                return
            try:
                dbus_client.remove_network(network)
            except dbus_client.DBusServiceError as e:
                self._show_error("Leave network", e.message)
                return
            self._toast(f"Left {name}.")
            self._networks_fingerprint = None
            self._show_network_list()
            self._refresh_networks(service_control.get_state())

        dialog.connect("response", on_response)
        dialog.present()

    # ---- Network detail page ----

    def _build_status_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        title_group = Adw.PreferencesGroup()
        page.add(title_group)
        self.detail_title_row = Adw.ActionRow(title="Network")
        back_btn = Gtk.Button(icon_name="go-previous-symbolic", valign=Gtk.Align.CENTER, tooltip_text="All networks",
                              css_classes=["flat"])
        back_btn.connect("clicked", lambda b: self._show_network_list())
        self.detail_title_row.add_prefix(back_btn)
        self.remove_network_btn = Gtk.Button(label="Leave network", valign=Gtk.Align.CENTER,
                                             css_classes=["destructive-action"])
        self.remove_network_btn.connect("clicked", self._on_remove_network)
        self.detail_title_row.add_suffix(self.remove_network_btn)
        title_group.add(self.detail_title_row)

        conn_group = Adw.PreferencesGroup(title="Connection")
        page.add(conn_group)
        self.status_row = Adw.ActionRow(title="Unknown")
        conn_group.add(self.status_row)

        self.routes_group = Adw.PreferencesGroup(title="Subnet routes offered to this node")
        page.add(self.routes_group)

        exit_group = Adw.PreferencesGroup(title="Exit node")
        page.add(exit_group)
        self.exit_combo = Adw.ComboRow(title="Selected exit node")
        self.exit_combo.set_model(Gtk.StringList.new([_NONE_EXIT_NODE]))
        self.exit_combo.connect("notify::selected", self._on_exit_node_changed)
        exit_group.add(self.exit_combo)
        self.exit_lan_switch = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        self.exit_lan_switch.connect("notify::active", self._on_exit_lan_toggled)
        exit_lan_row = Adw.ActionRow(
            title="Allow local network access",
            subtitle="Off: local-network traffic goes through the exit node too",
        )
        exit_lan_row.add_suffix(self.exit_lan_switch)
        exit_lan_row.set_activatable_widget(self.exit_lan_switch)
        exit_group.add(exit_lan_row)

        actions_group = Adw.PreferencesGroup()
        page.add(actions_group)
        actions_row = Adw.ActionRow(title="Advanced")
        view_config_btn = Gtk.Button(label="View Config", valign=Gtk.Align.CENTER)
        view_config_btn.connect("clicked", self._on_view_config)
        actions_row.add_suffix(view_config_btn)
        actions_group.add(actions_row)

        return page

    def _service_action(self, fn) -> None:
        ok, message = fn()
        if not ok:
            if service_control.is_access_denied(message):
                message = (
                    "Administrator required - only members of the sudo or wheel group "
                    "can start, stop or restart the Nebula Commander service."
                )
            self._show_error("Service", message or "Action failed.")
        self._refresh_status_labels()

    def _on_view_config(self, _button: Gtk.Button) -> None:
        try:
            content = dbus_client.get_config_yaml(self.current_network)
        except dbus_client.DBusServiceError as e:
            self._show_error("View Config", e.message)
            return
        win = Adw.Window(transient_for=self, modal=True, title="config.yaml", default_width=560, default_height=480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar())
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        text_view = Gtk.TextView(editable=False, monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
        text_view.get_buffer().set_text(content)
        scroller.set_child(text_view)
        box.append(scroller)
        win.set_content(box)
        win.present()

    def _refresh_status_labels(self) -> tuple[str, dict]:
        svc_state = service_control.get_state()
        labels = {
            service_control.ServiceState.RUNNING: "Running",
            service_control.ServiceState.STOPPED: "Stopped",
            service_control.ServiceState.TRANSITIONING: "Starting/stopping...",
            service_control.ServiceState.NOT_INSTALLED: "Not installed",
        }
        self.service_row.set_title(f"Service: {labels.get(svc_state, svc_state)}")
        if svc_state == service_control.ServiceState.NOT_INSTALLED:
            status = {"state": "error", "message": "Service not installed"}
        elif svc_state != service_control.ServiceState.RUNNING:
            status = {"state": "idle", "message": "Service stopped"}
        else:
            status = dbus_client.get_status(self.current_network)
        state = (status.get("state") or "idle").capitalize()
        self.status_row.set_title(state)
        self.status_row.set_subtitle(status.get("message") or "Nebula Commander")
        return svc_state, status

    def _maybe_notify(self, svc_state: str, status: dict) -> None:
        combo = (svc_state, status.get("state") or "idle")
        if self._prev_combo is not None and combo != self._prev_combo and svc_state != service_control.ServiceState.RUNNING:
            urgency = "critical" if svc_state == service_control.ServiceState.NOT_INSTALLED else "normal"
            notify.notify("Nebula Commander", status.get("message") or "Service stopped", urgency=urgency)
        self._prev_combo = combo
        # One notification per network whose state changed (errors, reconnects).
        for n in self._networks:
            st = n.get("status") or {}
            key, state = n.get("id"), st.get("state") or "idle"
            prev = self._prev_network_states.get(key)
            if prev is not None and prev != state:
                urgency = "critical" if state == "error" else "normal"
                notify.notify(n.get("name") or "Nebula Commander", st.get("message") or f"Status: {state}", urgency=urgency)
            self._prev_network_states[key] = state

    def _maybe_notify_new_routes(self, available: list[dict]) -> None:
        keys = {(r.get("route"), r.get("via"), r.get("kind")) for r in available}
        new_keys = keys - self._prev_route_keys
        if self._prev_route_keys and new_keys:
            for route, via, kind in new_keys:
                label = "exit node" if kind == "exit" else "subnet route"
                notify.notify(
                    "New route available",
                    f"A {label} ({route}) is now offered. Open Nebula Commander to accept it.",
                )
        self._prev_route_keys = keys

    def _refresh_routes_picker(self, available: list[dict], force: bool = False) -> None:
        settings = dbus_client.get_settings(self.current_network)
        accepted_subnet_routes = settings.get("accepted_subnet_routes") or []
        accepted_exit_node = settings.get("accepted_exit_node")
        exit_allow_lan = settings.get("exit_allow_lan", True) is not False
        host_exit_active = bool(settings.get("host_exit_active"))
        fingerprint = (
            json.dumps(available, sort_keys=True),
            json.dumps(accepted_subnet_routes, sort_keys=True),
            json.dumps(accepted_exit_node, sort_keys=True),
            exit_allow_lan,
            host_exit_active,
        )
        if not force and fingerprint == self._routes_fingerprint:
            return
        self._routes_fingerprint = fingerprint

        for row in self._route_rows:
            self.routes_group.remove(row)
        self._route_rows.clear()

        accepted_subnet_keys = {(r.get("route"), r.get("via")) for r in accepted_subnet_routes}
        subnet_routes = [r for r in available if r.get("kind") != "exit"]
        exit_nodes = [r for r in available if r.get("kind") == "exit"]

        if not subnet_routes:
            row = Adw.ActionRow(title="(none offered)")
            self.routes_group.add(row)
            self._route_rows.append(row)
        for r in subnet_routes:
            route, via = r.get("route"), r.get("via")
            checked = (route, via) in accepted_subnet_keys
            conflict = None if checked else dbus_client.validate_new_subnet_route(route, accepted_subnet_routes)
            switch = Gtk.Switch(active=checked, valign=Gtk.Align.CENTER, sensitive=not conflict)
            switch.connect("notify::active", self._on_subnet_toggle, route, via)
            row = Adw.ActionRow(title=route, subtitle=(conflict or f"via {via}"))
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            self.routes_group.add(row)
            self._route_rows.append(row)

        self._suspend_exit_signal = True
        # One entry per gateway: an exit node offers 0.0.0.0/0 and ::/0 with the same via.
        vias = [None] + list(dict.fromkeys(r.get("via") for r in exit_nodes))
        if vias != self._exit_node_vias or self.exit_combo.get_model() is None:
            # Only when the gateways change: replacing the model while its popover is
            # open (right after a pick) left the popover stuck on screen, holding input.
            self._exit_node_vias = vias
            labels = [_NONE_EXIT_NODE] + [f"via {via}" for via in vias[1:]]
            self.exit_combo.set_model(Gtk.StringList.new(labels))
        accepted_exit_via = (accepted_exit_node or {}).get("via")
        try:
            selected_index = self._exit_node_vias.index(accepted_exit_via)
        except ValueError:
            selected_index = 0
        self.exit_combo.set_selected(selected_index)
        self.exit_combo.set_subtitle(
            "Another network's exit node is in use - picking one here replaces it"
            if host_exit_active and not accepted_exit_via else ""
        )
        self.exit_lan_switch.set_active(exit_allow_lan)
        self._suspend_exit_signal = False

    def _safe_call(self, fn, *args) -> bool:
        try:
            fn(*args)
            return True
        except dbus_client.DBusServiceError as e:
            self._show_error("Routes", e.message)
            return False
        except Exception as e:
            self._show_error("Routes", str(e))
            return False

    def _on_subnet_toggle(self, switch: Gtk.Switch, _pspec, route: str, via: str) -> None:
        if switch.get_active():
            self._safe_call(dbus_client.accept_route, route, via, self.current_network)
        else:
            self._safe_call(dbus_client.reject_route, route, self.current_network)
        self._refresh_routes_picker(dbus_client.get_available_routes(self.current_network), force=True)

    def _on_exit_node_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        if self._suspend_exit_signal:
            return
        idx = combo.get_selected()
        via = self._exit_node_vias[idx] if 0 <= idx < len(self._exit_node_vias) else None
        if via is None:
            if dbus_client.get_settings(self.current_network).get("accepted_exit_node"):
                self._safe_call(dbus_client.reject_exit_node, self.current_network)
        else:
            self._safe_call(dbus_client.accept_exit_node, via, self.current_network)
        self._refresh_routes_picker(dbus_client.get_available_routes(self.current_network), force=True)

    def _on_exit_lan_toggled(self, switch: Gtk.Switch, _pspec) -> None:
        if self._suspend_exit_signal:
            return
        self._safe_call(dbus_client.set_settings, {"exit_allow_lan": switch.get_active()})
        self._refresh_routes_picker(dbus_client.get_available_routes(self.current_network), force=True)

    # ---- Enrollment page ----

    def _build_enroll_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        info_group = Adw.PreferencesGroup()
        page.add(info_group)
        self.enroll_info_row = Adw.ActionRow()
        info_group.add(self.enroll_info_row)

        group = Adw.PreferencesGroup(
            title="Add a network",
            description="Enter the server and the one-time code from that network's Nebula Commander "
                        "(Nodes > Get Enrollment Code). A device can be in several networks, on different servers.",
        )
        page.add(group)
        self.enroll_server_row = Adw.EntryRow(title="Server URL", text="https://")
        group.add(self.enroll_server_row)
        self.enroll_code_row = Adw.EntryRow(title="Enrollment code")
        group.add(self.enroll_code_row)

        btn_row = Adw.ActionRow()
        enroll_btn = Gtk.Button(label="Enroll", css_classes=["suggested-action"])
        enroll_btn.connect("clicked", self._on_enroll)
        btn_row.add_suffix(enroll_btn)
        group.add(btn_row)

        self._refresh_enroll_info()
        return page

    def _refresh_enroll_info(self) -> None:
        networks = dbus_client.list_networks()
        if networks is None:
            enrolled, server = dbus_client.is_enrolled()
            networks = [{"name": server}] if enrolled else []
        if networks:
            names = ", ".join(n.get("name") or n.get("server") or n.get("id") or "?" for n in networks)
            self.enroll_info_row.set_title(f"Enrolled in {len(networks)} network{'s' if len(networks) != 1 else ''}")
            self.enroll_info_row.set_subtitle(names)
        else:
            self.enroll_info_row.set_title("Not enrolled yet")
            self.enroll_info_row.set_subtitle("")

    def _on_enroll(self, _button: Gtk.Button) -> None:
        server = self.enroll_server_row.get_text().strip()
        code = self.enroll_code_row.get_text().strip().upper()
        if not server or not code:
            self._show_error("Enroll", "Enter both server URL and enrollment code.")
            return
        try:
            if dbus_client.list_networks() is None:  # service from before 0.8.0
                dbus_client.enroll(server, code)
                new_id, label = None, server
            else:
                e = dbus_client.enroll_network(server, code)
                new_id, label = e.get("id"), e.get("name") or server
        except dbus_client.DBusServiceError as e:
            self._show_error("Enroll", e.message)
            return
        self._toast(f"Enrolled in {label}.")
        self.enroll_code_row.set_text("")
        self._refresh_enroll_info()
        self._networks_fingerprint = None
        self._refresh_networks(service_control.get_state())
        self.view_stack.set_visible_child_name("status")
        self._open_network(new_id)

    # ---- Settings page ----

    def _build_settings_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        settings = dbus_client.get_settings()

        # No server here: each network keeps the server it was enrolled with.
        group = Adw.PreferencesGroup(title="Connection", description="These apply to every network.")
        page.add(group)

        interval_adj = Gtk.Adjustment(value=int(settings.get("interval") or 60), lower=10, upper=3600, step_increment=10)
        self.settings_interval_spin = Gtk.SpinButton(adjustment=interval_adj, valign=Gtk.Align.CENTER)
        _action_row_with_suffix(group, "Poll interval (seconds)", self.settings_interval_spin, activatable=False)

        # No Nebula path field: the service runs the system's packaged nebula
        # (its PATH), and nebula_path isn't settable over D-Bus any more.
        nebula_group = Adw.PreferencesGroup(title="Nebula")
        page.add(nebula_group)

        self.settings_accept_dns_switch = Gtk.Switch(active=bool(settings.get("accept_dns", False)), valign=Gtk.Align.CENTER)
        _action_row_with_suffix(nebula_group, "Accept split-horizon DNS", self.settings_accept_dns_switch)

        misc_group = Adw.PreferencesGroup(title="Startup")
        page.add(misc_group)
        self.settings_autostart_switch = Gtk.Switch(active=autostart.is_autostart_enabled(), valign=Gtk.Align.CENTER)
        self.settings_autostart_switch.connect("notify::active", self._on_toggle_autostart)
        _action_row_with_suffix(misc_group, "Run on startup", self.settings_autostart_switch)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_row = Adw.ActionRow()
        save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save_btn.connect("clicked", self._on_save_settings)
        save_row.add_suffix(save_btn)
        save_group.add(save_row)

        self._build_updates_group(page)
        return page

    # ---- Automatic updates (client/updates.py, via D-Bus) ----

    def _build_updates_group(self, page: Adw.PreferencesPage) -> None:
        self.updates_group = Adw.PreferencesGroup(
            title="Updates",
            description="Changes need an administrator (sudo or wheel group), like the other settings.",
        )
        page.add(self.updates_group)
        self.updates_version_row = Adw.ActionRow(title="Installed version")
        self.updates_group.add(self.updates_version_row)
        self.updates_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.updates_switch_row = _action_row_with_suffix(self.updates_group, "Automatic updates", self.updates_switch)
        self.updates_window_row = Adw.EntryRow(title="Install between (HH:MM-HH:MM, local time)")
        self.updates_group.add(self.updates_window_row)
        self.updates_status_row = Adw.ActionRow(title="Not checked yet")
        self.updates_status_row.set_subtitle_selectable(True)
        self.updates_group.add(self.updates_status_row)
        buttons = Adw.ActionRow()
        self.updates_check_btn = Gtk.Button(label="Check now", valign=Gtk.Align.CENTER)
        self.updates_check_btn.connect("clicked", self._on_check_updates)
        apply_btn = Gtk.Button(label="Apply", css_classes=["suggested-action"], valign=Gtk.Align.CENTER)
        apply_btn.connect("clicked", self._on_apply_updates)
        buttons.add_suffix(self.updates_check_btn)
        buttons.add_suffix(apply_btn)
        self.updates_group.add(buttons)
        self._refresh_updates(load_settings=True)

    def _refresh_updates(self, load_settings: bool = False, st: "dict | None" = None) -> None:
        if st is None:
            try:
                st = dbus_client.get_update_status()
            except dbus_client.DBusServiceError:
                st = None
        if not st or not st.get("supported"):
            # Service stopped or too old, or an install without automatic updates.
            self.updates_group.set_visible(False)
            return
        self.updates_group.set_visible(True)
        nixos = st.get("install_kind") == "nixos"
        installed = st.get("installed_version") or ""
        if installed.startswith("0.0.0+git."):
            version_text = f"Built from commit {installed[len('0.0.0+git.'):]} (your NixOS flake)"
        elif st.get("dev_build"):
            version_text = "Development build (never updated automatically)"
        else:
            version_text = f"v{st.get('installed_version')}"
        self.updates_version_row.set_subtitle(version_text)
        self.updates_switch_row.set_subtitle(
            "Check daily and tell you when a release is out - NixOS updates come from your flake"
            if nixos else "Install new releases from the Nebula Commander repository during the window"
        )
        self.updates_window_row.set_visible(not nixos)
        if load_settings:
            self.updates_switch.set_active(bool(st.get("enabled")))
            self.updates_window_row.set_text(f"{st.get('window_start')}-{st.get('window_end')}")

        lines = []
        result = st.get("last_result")
        if st.get("last_check"):
            title = {
                "update_available": f"v{st.get('available_version')} is available",
                "error": "Last check failed",
            }.get(result, "Up to date")
            self.updates_status_row.set_title(title)
            if result == "error":
                lines.append(st.get("last_error") or "")
            lines.extend(st.get("instructions") or [])
            lines.append(f"Checked {st['last_check']}")
        if st.get("last_install_attempt"):
            outcome = st.get("last_install_result") or ""
            if outcome == "error":
                outcome = st.get("last_install_error") or "failed"
            lines.append(f"Last install {st['last_install_attempt']}: {outcome}")
        self.updates_status_row.set_subtitle("\n".join(line for line in lines if line))
        self._maybe_notify_update(st)

    def _maybe_notify_update(self, st: dict) -> None:
        """Once per new version, per user (remembered across app restarts)."""
        available = st.get("available_version")
        if not available:
            return
        config_home = os.environ.get("XDG_CONFIG_HOME", "").strip() or os.path.join(os.path.expanduser("~"), ".config")
        marker = os.path.join(config_home, "nebula-commander", "notified-update")
        try:
            with open(marker, "r", encoding="utf-8") as f:
                if f.read().strip() == available:
                    return
        except OSError:
            pass
        if st.get("install_kind") == "nixos":
            body = "Update the nebula-commander flake input and rebuild to install it."
        elif st.get("mode") == "install":
            body = "It will be installed during the update window."
        else:
            body = "Open Nebula Commander for details."
        notify.notify(f"Nebula Commander {available} is available", body)
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(available)
        except OSError:
            pass

    def _on_apply_updates(self, _button: Gtk.Button) -> None:
        start, _sep, end = self.updates_window_row.get_text().strip().partition("-")
        try:
            st = dbus_client.set_auto_update(self.updates_switch.get_active(), start.strip() or None, end.strip() or None)
        except dbus_client.DBusServiceError as e:
            self._show_error("Updates", e.message)
            self._refresh_updates(load_settings=True)
            return
        self._refresh_updates(load_settings=True, st=st)
        self._toast("Automatic updates " + ("on." if st.get("enabled") else "off."))

    def _on_check_updates(self, _button: Gtk.Button) -> None:
        # Fetching + verifying the manifest can take a while: off the UI thread.
        self.updates_check_btn.set_sensitive(False)
        self.updates_status_row.set_title("Checking...")

        def work() -> None:
            try:
                st, err = dbus_client.check_for_updates_now(), None
            except dbus_client.DBusServiceError as e:
                st, err = None, e.message
            GLib.idle_add(done, st, err)

        def done(st, err) -> bool:
            self.updates_check_btn.set_sensitive(True)
            if err:
                self._show_error("Updates", err)
                self._refresh_updates()
            else:
                self._refresh_updates(st=st)
                if st.get("install_started"):
                    self._toast(f"Installing v{st.get('available_version')} now...")
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_toggle_autostart(self, switch: Gtk.Switch, _pspec) -> None:
        if switch.get_active():
            if getattr(sys, "frozen", False):
                target = sys.executable
            else:
                xdg_data = os.environ.get("XDG_DATA_HOME", "").strip() or os.path.join(
                    os.path.expanduser("~"), ".local", "share"
                )
                launch_dir = os.path.join(xdg_data, "nebula-commander")
                os.makedirs(launch_dir, exist_ok=True)
                script_path = os.path.join(launch_dir, "ncclient-desktop-launch.sh")
                repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                content = f'#!/bin/sh\ncd "{repo_root}"\nexec "{sys.executable}" -m client.linux.desktop\n'
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.chmod(script_path, 0o700)
                target = script_path
            ok = autostart.enable_autostart(target)
            if not ok:
                self._show_error("Run on startup", f"Could not create autostart entry for:\n{target}")
                switch.set_active(False)
        else:
            autostart.disable_autostart()

    def _on_save_settings(self, _button: Gtk.Button) -> None:
        interval = max(10, min(3600, self.settings_interval_spin.get_value_as_int()))
        try:
            dbus_client.set_settings(
                {
                    "interval": interval,
                    "accept_dns": self.settings_accept_dns_switch.get_active(),
                }
            )
        except dbus_client.DBusServiceError as e:
            self._show_error("Settings", e.message)
            return
        # Unlike route accept/reject (picked up on the service's next poll via
        # run_poll_loop's fingerprint check - no restart needed), server/
        # interval/accept_dns are only read once at process start
        # (see packaging/deb/service/payload's ncclient-run.sh wrapper for
        # accept_dns specifically). Best-effort restart so they take effect
        # now instead of leaving the change silently pending until the next
        # manual/reboot restart.
        if service_control.get_state() == service_control.ServiceState.RUNNING:
            ok, message = service_control.restart()
            if ok:
                self._toast("Settings saved. Restarting service to apply...")
            else:
                self._toast(f"Settings saved, but restart failed: {message}")
        else:
            self._toast("Settings saved.")

    # ---- Shared helpers ----

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.MessageDialog(heading=heading, body=body, transient_for=self, modal=True)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    # ---- Poll loop ----

    def _refresh_detail(self) -> None:
        self._refresh_status_labels()
        available = dbus_client.get_available_routes(self.current_network)
        self._maybe_notify_new_routes(available)
        self._refresh_routes_picker(available)

    def _poll_tick(self) -> bool:
        svc_state, status = self._refresh_status_labels()
        self._refresh_networks(svc_state)
        self._maybe_notify(svc_state, status)
        if self.networks_stack.get_visible_child_name() == "detail":
            self._refresh_detail()
        # Update status changes rarely; once a minute is plenty.
        self._update_ticks += 1
        if self._update_ticks * POLL_MS >= 60_000:
            self._update_ticks = 0
            self._refresh_updates()
        return GLib.SOURCE_CONTINUE


class NebulaCommanderApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: MainWindow | None = None

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main() -> None:
    if not sys.platform.startswith("linux"):
        print("Linux desktop app is Linux-only.", file=sys.stderr)
        sys.exit(1)
    app = NebulaCommanderApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
