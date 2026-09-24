{ pkgs
, repoSrc ? ../.
}:

let
  # PyGObject/GTK4/libadwaita, real runtime dependencies here (unlike the
  # .deb/Flatpak packaging, which had to avoid PyGObject in anything
  # PyInstaller needs to freeze - client/ncclient.py's CLI/service binary.
  # This package never gets frozen at all, so that constraint doesn't
  # apply: it's plain Nix dependency-closure wrapping, the same as any
  # other GTK4 app.
  pythonEnv = pkgs.python313.withPackages (ps: with ps; [
    pygobject3
    jeepney
  ]);

  desktopFiles = repoSrc + "/packaging/flatpak";

  # Keep in sync with packaging/deb/build.py's _LINUX_SOURCE_FILES - all
  # three packaging paths (.deb, Flatpak, this) ship the same plain-Python
  # client/linux/*.py payload. client/__init__.py alone (not the rest of
  # client/*.py) is all that's needed from the top-level client package -
  # desktop.py no longer imports client.config/client.token_store/
  # client.ncclient at all, only client.linux.* modules talking to the
  # D-Bus service over jeepney.
  linuxSourceFiles = [
    "__init__.py"
    "desktop.py"
    "notify.py"
    "service_control.py"
    "autostart.py"
    "dbus_client.py"
  ];
in

pkgs.stdenv.mkDerivation {
  pname = "nebula-commander-desktop";
  version = "0.1.8"; # matches nix/client-package.nix's version

  src = repoSrc + "/client";

  nativeBuildInputs = with pkgs; [
    wrapGAppsHook4
    gobject-introspection
  ];

  buildInputs = with pkgs; [
    gtk4
    libadwaita
  ];

  dontBuild = true;
  dontConfigure = true;

  installPhase = ''
    runHook preInstall

    install -Dm644 __init__.py "$out/share/nebula-commander-desktop/client/__init__.py"
    ${pkgs.lib.concatMapStringsSep "\n" (f:
      ''install -Dm644 "linux/${f}" "$out/share/nebula-commander-desktop/client/linux/${f}"''
    ) linuxSourceFiles}

    mkdir -p "$out/bin"
    cat > "$out/bin/nebula-commander-desktop" <<WRAPPER
    #!/bin/sh
    exec ${pythonEnv}/bin/python3 "$out/share/nebula-commander-desktop/client/linux/desktop.py" "\$@"
    WRAPPER
    chmod +x "$out/bin/nebula-commander-desktop"

    install -Dm644 "${desktopFiles}/org.beardedtek.NebulaCommander.desktop" \
      "$out/share/applications/org.beardedtek.NebulaCommander.desktop"
    install -Dm644 "${desktopFiles}/org.beardedtek.NebulaCommander.svg" \
      "$out/share/icons/hicolor/scalable/apps/org.beardedtek.NebulaCommander.svg"
    install -Dm644 "${desktopFiles}/org.beardedtek.NebulaCommander.metainfo.xml" \
      "$out/share/metainfo/org.beardedtek.NebulaCommander.metainfo.xml"

    # The D-Bus bus policy and polkit action declaration ship with
    # nix/client-package.nix (the ncclient CLI/service package) instead of
    # here - that's the package that actually hosts the D-Bus service and
    # needs those files registered, matching the .deb split
    # (nebula-commander-service ships them, not nebula-commander-desktop).

    runHook postInstall
  '';

  meta = {
    description = "Nebula Commander desktop app (GTK4/libadwaita)";
    homepage = "https://github.com/NixRTR/nebula-commander";
    license = pkgs.lib.licenses.gpl3Plus;
    mainProgram = "nebula-commander-desktop";
  };
}
