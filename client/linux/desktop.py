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

Run from repo root: python -m client.linux.desktop
"""
from __future__ import annotations

import json
import os
import sys

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
        self._prev_route_keys: set[tuple] = set()
        self._routes_fingerprint: object = None
        self._route_rows: list[Adw.ActionRow] = []
        self._exit_node_vias: list[str | None] = [None]
        self._suspend_exit_signal = False

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

        status_page = self._build_status_page()
        enroll_page = self._build_enroll_page()
        settings_page = self._build_settings_page()

        self.view_stack.add_titled(status_page, "status", "Status").set_icon_name("network-vpn-symbolic")
        self.view_stack.add_titled(enroll_page, "enroll", "Enrollment").set_icon_name("dialog-password-symbolic")
        self.view_stack.add_titled(settings_page, "settings", "Settings").set_icon_name("preferences-system-symbolic")

        GLib.timeout_add(POLL_MS, self._poll_tick)
        self._poll_tick()

    # ---- Status page ----

    def _build_status_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        conn_group = Adw.PreferencesGroup(title="Connection")
        page.add(conn_group)
        self.status_row = Adw.ActionRow(title="Unknown")
        conn_group.add(self.status_row)

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

        self.routes_group = Adw.PreferencesGroup(title="Subnet routes offered to this node")
        page.add(self.routes_group)

        exit_group = Adw.PreferencesGroup(title="Exit node")
        page.add(exit_group)
        self.exit_combo = Adw.ComboRow(title="Selected exit node")
        self.exit_combo.set_model(Gtk.StringList.new([_NONE_EXIT_NODE]))
        self.exit_combo.connect("notify::selected", self._on_exit_node_changed)
        exit_group.add(self.exit_combo)

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
            self._show_error("Service", message or "Action failed.")
        self._refresh_status_labels()

    def _on_view_config(self, _button: Gtk.Button) -> None:
        try:
            content = dbus_client.get_config_yaml()
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
            status = dbus_client.get_status()
        state = (status.get("state") or "idle").capitalize()
        self.status_row.set_title(state)
        self.status_row.set_subtitle(status.get("message") or "Nebula Commander")
        return svc_state, status

    def _maybe_notify(self, svc_state: str, status: dict) -> None:
        combo = (svc_state, status.get("state") or "idle")
        if self._prev_combo is not None and combo != self._prev_combo:
            state = status.get("state") or "idle"
            urgency = "critical" if state == "error" or svc_state == service_control.ServiceState.NOT_INSTALLED else "normal"
            notify.notify("Nebula Commander", status.get("message") or f"Status: {state}", urgency=urgency)
        self._prev_combo = combo

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
        settings = dbus_client.get_settings()
        accepted_subnet_routes = settings.get("accepted_subnet_routes") or []
        accepted_exit_node = settings.get("accepted_exit_node")
        fingerprint = (
            json.dumps(available, sort_keys=True),
            json.dumps(accepted_subnet_routes, sort_keys=True),
            json.dumps(accepted_exit_node, sort_keys=True),
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
        self._exit_node_vias = [None] + [r.get("via") for r in exit_nodes]
        labels = [_NONE_EXIT_NODE] + [f"via {r.get('via')}" for r in exit_nodes]
        self.exit_combo.set_model(Gtk.StringList.new(labels))
        accepted_exit_via = (accepted_exit_node or {}).get("via")
        try:
            selected_index = self._exit_node_vias.index(accepted_exit_via)
        except ValueError:
            selected_index = 0
        self.exit_combo.set_selected(selected_index)
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
            self._safe_call(dbus_client.accept_route, route, via)
        else:
            self._safe_call(dbus_client.reject_route, route)
        self._refresh_routes_picker(dbus_client.get_available_routes(), force=True)

    def _on_exit_node_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        if self._suspend_exit_signal:
            return
        idx = combo.get_selected()
        via = self._exit_node_vias[idx] if 0 <= idx < len(self._exit_node_vias) else None
        if via is None:
            if dbus_client.get_settings().get("accepted_exit_node"):
                self._safe_call(dbus_client.reject_exit_node)
        else:
            self._safe_call(dbus_client.accept_exit_node, via)
        self._refresh_routes_picker(dbus_client.get_available_routes(), force=True)

    # ---- Enrollment page ----

    def _build_enroll_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        info_group = Adw.PreferencesGroup()
        page.add(info_group)
        self.enroll_info_row = Adw.ActionRow()
        info_group.add(self.enroll_info_row)

        group = Adw.PreferencesGroup(title="Enroll this device")
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
        enrolled, server = dbus_client.is_enrolled()
        if enrolled:
            self.enroll_info_row.set_title("Already enrolled")
            self.enroll_info_row.set_subtitle(f"Server: {server or '?'}")
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
            dbus_client.enroll(server, code)
        except dbus_client.DBusServiceError as e:
            self._show_error("Enroll", e.message)
            return
        self._toast("Enrolled successfully.")
        self._refresh_enroll_info()
        self.view_stack.set_visible_child_name("status")

    # ---- Settings page ----

    def _build_settings_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        settings = dbus_client.get_settings()

        group = Adw.PreferencesGroup(title="Connection")
        page.add(group)
        self.settings_server_row = Adw.EntryRow(title="Server URL", text=settings.get("server") or "https://")
        group.add(self.settings_server_row)

        interval_adj = Gtk.Adjustment(value=int(settings.get("interval") or 60), lower=10, upper=3600, step_increment=10)
        self.settings_interval_spin = Gtk.SpinButton(adjustment=interval_adj, valign=Gtk.Align.CENTER)
        _action_row_with_suffix(group, "Poll interval (seconds)", self.settings_interval_spin, activatable=False)

        nebula_group = Adw.PreferencesGroup(title="Nebula")
        page.add(nebula_group)
        self.settings_nebula_row = Adw.EntryRow(title="Nebula executable path (optional - blank uses PATH)", text=settings.get("nebula_path") or "")
        browse_btn = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_nebula)
        self.settings_nebula_row.add_suffix(browse_btn)
        nebula_group.add(self.settings_nebula_row)

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

        return page

    def _on_browse_nebula(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(
            title="Select nebula executable",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )

        def on_response(dlg: Gtk.FileChooserNative, response: int) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile is not None:
                    self.settings_nebula_row.set_text(gfile.get_path() or "")
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

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
                os.chmod(script_path, 0o755)
                target = script_path
            ok = autostart.enable_autostart(target)
            if not ok:
                self._show_error("Run on startup", f"Could not create autostart entry for:\n{target}")
                switch.set_active(False)
        else:
            autostart.disable_autostart()

    def _on_save_settings(self, _button: Gtk.Button) -> None:
        server = self.settings_server_row.get_text().strip()
        if not server:
            self._show_error("Settings", "Enter server URL.")
            return
        interval = max(10, min(3600, self.settings_interval_spin.get_value_as_int()))
        try:
            dbus_client.set_settings(
                {
                    "server": server,
                    "interval": interval,
                    "nebula_path": self.settings_nebula_row.get_text().strip(),
                    "accept_dns": self.settings_accept_dns_switch.get_active(),
                }
            )
        except dbus_client.DBusServiceError as e:
            self._show_error("Settings", e.message)
            return
        # Unlike route accept/reject (picked up on the service's next poll via
        # run_poll_loop's fingerprint check - no restart needed), server/
        # interval/nebula_path/accept_dns are only read once at process start
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

    def _poll_tick(self) -> bool:
        svc_state, status = self._refresh_status_labels()
        self._maybe_notify(svc_state, status)
        available = dbus_client.get_available_routes()
        self._maybe_notify_new_routes(available)
        self._refresh_routes_picker(available)
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
