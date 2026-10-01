{ pkgs
# Named repoSrc, not src: callPackage auto-injects any argument literally named
# "src" from pkgs (which as of nixpkgs 25.11 is a throwing alias for a renamed
# package), silently overriding a default given here and breaking the build.
, repoSrc ? ../.
# Which commit this was built from and that commit's time (Unix seconds), from the
# flake (self.rev / self.lastModified, see flake.nix). A Nix build has no release tag
# to stamp a version from, so the client's NixOS update check compares these against
# the signed update manifest instead (client/updates.py). null = unknown.
, sourceRev ? null
, sourceDate ? null
}:

pkgs.python313.pkgs.buildPythonApplication {
  pname = "nebula-commander-client";
  version = "0.1.8"; # matches client/pyproject.toml's setuptools_scm fallback_version
  pyproject = true;

  # pyproject.toml lives in client/ and maps package-dir "client" -> "." (the client/
  # directory itself is the "client" package), so build from client/, not the repo root.
  src = repoSrc + "/client";

  build-system = with pkgs.python313.pkgs; [
    setuptools
    wheel
    setuptools-scm
  ];

  dependencies = with pkgs.python313.pkgs; [
    requests
    keyring
    pyyaml
    cryptography # client/updates.py: verifies the signed update manifest
    # client/linux/dbus_server.py's system D-Bus service (see
    # client/pyproject.toml's own sys_platform=='linux' marker for the
    # same dependency on PyPI) - nixpkgs deps aren't auto-derived from
    # pyproject.toml here, so this needs listing by hand too. This is what
    # gives this package its D-Bus-server capability, since it wraps the
    # same client/ncclient.py entry point the .deb binary does.
    jeepney
  ];

  # No .git is present in the Nix store copy of the source, so setuptools_scm can't
  # detect a version from tags; pyproject.toml's fallback_version covers this, but
  # SETUPTOOLS_SCM_PRETEND_VERSION avoids relying on that fallback path entirely.
  SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.8";

  # No test suite is wired up for `client/` (nothing under pytest discovery here); skip
  # rather than have buildPythonApplication's default checkPhase fail on collection.
  doCheck = false;

  # See client/version.py - the same file CI's client/stamp_version.py writes for
  # release builds, minus VERSION (left as the dev fallback).
  postPatch = pkgs.lib.optionalString (sourceRev != null || sourceDate != null) ''
    cat > _build_version.py <<'PYEOF'
    GIT_COMMIT = ${if sourceRev != null then "\"${sourceRev}\"" else "None"}
    SOURCE_DATE = ${if sourceDate != null then toString sourceDate else "None"}
    PYEOF
  '';

  # D-Bus bus policy + polkit action declaration for client/linux/
  # dbus_server.py's org.beardedtek.NebulaCommander1 service, which this
  # package's ncclient binary hosts when run as the systemd service (see
  # nix/client-module.nix). Picked up automatically by NixOS's dbus module
  # via services.dbus.packages and by its polkit module (which unions
  # share/polkit-1/actions across environment.systemPackages) - no manual
  # reload step needed the way the .deb path's postinst requires, since
  # NixOS system activation restarts/reloads the affected services itself.
  postInstall = ''
    install -Dm644 "${repoSrc}/packaging/deb/service/payload/usr/share/polkit-1/actions/org.beardedtek.NebulaCommander1.policy" \
      "$out/share/polkit-1/actions/org.beardedtek.NebulaCommander1.policy"
    install -Dm644 "${repoSrc}/packaging/deb/service/payload/usr/share/dbus-1/system.d/org.beardedtek.NebulaCommander1.conf" \
      "$out/share/dbus-1/system.d/org.beardedtek.NebulaCommander1.conf"
  '';

  meta = {
    description = "Nebula Commander device client (ncclient)";
    homepage = "https://github.com/NixRTR/nebula-commander";
    license = pkgs.lib.licenses.gpl3Plus;
    mainProgram = "ncclient";
  };
}
