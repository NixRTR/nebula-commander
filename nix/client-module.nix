{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.services.ncclient;

  runArgs = [
    "--output-dir"
    cfg.outputDir
    "--interval"
    (toString cfg.interval)
  ] ++ optional cfg.acceptDns "--accept-dns";
in

{
  options.services.ncclient = {
    enable = mkEnableOption "Nebula Commander device client (ncclient)";

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ./client-package.nix { };
      defaultText = "pkgs.callPackage ./client-package.nix { }";
      description = "ncclient package.";
    };

    nebulaPackage = mkOption {
      type = types.package;
      default = pkgs.nebula;
      defaultText = "pkgs.nebula";
      description = "Package providing the nebula/nebula-cert binaries ncclient orchestrates.";
    };

    server = mkOption {
      type = types.str;
      description = "Nebula Commander server URL (e.g. https://nebula.example.com).";
    };

    enrollCodeFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = ''
        Path to a file containing a one-time enrollment code (e.g. managed by
        sops-nix). When set and no device token exists yet at
        "''${stateDir}/token", ncclient enroll is run once before the main
        service starts. Leave null if you provision the token file out of band.
      '';
    };

    interval = mkOption {
      type = types.int;
      default = 60;
      description = "Poll interval in seconds.";
    };

    outputDir = mkOption {
      type = types.str;
      default = "/var/lib/ncclient/nebula";
      description = "Directory ncclient writes Nebula's config/certs/binary to.";
    };

    acceptDns = mkOption {
      type = types.bool;
      default = false;
      description = "Accept and apply DNS settings pushed by Nebula Commander.";
    };

    stateDir = mkOption {
      type = types.str;
      default = "/var/lib/ncclient";
      description = ''
        Directory holding the device token and settings.json (node_id) together
        on the same persistent path. Both must live in the same place, or
        node_id is silently lost on every restart even though the token
        survives - the exact bug this module avoids by setting
        NEBULA_COMMANDER_CONFIG_DIR and NEBULA_DEVICE_TOKEN_FILE from the same
        stateDir below.
      '';
    };
  };

  config = mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0700 root root -"
      "d ${cfg.outputDir} 0700 root root -"
    ];

    # Registers cfg.package's shipped D-Bus bus policy (system.d/*.conf) and
    # polkit action declaration (polkit-1/actions/*.policy) for
    # client/linux/dbus_server.py's org.beardedtek.NebulaCommander1
    # service, which `ncclient run` (below) hosts. NixOS's dbus/polkit
    # modules pick these up from the package output directly - no manual
    # `systemctl reload polkit`/`reload dbus` step needed the way the .deb
    # path's postinst requires (see nix/client-package.nix's postInstall),
    # since system activation restarts/reloads the affected services
    # itself whenever this changes.
    services.dbus.packages = [ cfg.package ];

    # Authorizes org.freedesktop.systemd1's own manage-units action, scoped
    # to exactly the ncclient unit - this is what lets
    # client/linux/service_control.py's Start/Stop/Restart (called by the
    # desktop app, see nix/client-desktop-module.nix) work for any active
    # local session with no password prompt. Inline JS via extraConfig
    # (rather than a shipped .rules file the way the .deb path does it) -
    # simpler for a single rule than adding another packaged file/reload
    # dependency. Mirrors packaging/deb/service/payload/usr/share/
    # polkit-1/rules.d/org.nixrtr.nebulacommander.rules exactly - keep the
    # two in sync if this condition ever changes.
    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
          if (action.id == "org.freedesktop.systemd1.manage-units" &&
              action.lookup("unit") == "ncclient.service" &&
              ["start", "stop", "restart"].indexOf(action.lookup("verb")) != -1 &&
              subject.active && subject.local) {
              return polkit.Result.YES;
          }
      });
    '';

    systemd.services.ncclient-enroll = mkIf (cfg.enrollCodeFile != null) {
      description = "Enroll ncclient with Nebula Commander";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      before = [ "ncclient.service" ];
      path = [ cfg.nebulaPackage ];
      environment = {
        NEBULA_DEVICE_TOKEN_FILE = "${cfg.stateDir}/token";
        NEBULA_COMMANDER_CONFIG_DIR = cfg.stateDir;
      };
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if [ ! -f "${cfg.stateDir}/token" ]; then
          ${cfg.package}/bin/ncclient --server ${cfg.server} enroll --code "$(cat ${cfg.enrollCodeFile})"
        fi
      '';
    };

    systemd.services.ncclient = {
      description = "Nebula Commander device client (ncclient)";
      after = [ "network-online.target" ] ++ optional (cfg.enrollCodeFile != null) "ncclient-enroll.service";
      wants = [ "network-online.target" ];
      requires = optional (cfg.enrollCodeFile != null) "ncclient-enroll.service";
      wantedBy = [ "multi-user.target" ];

      # Extend PATH via `path`, not `environment.PATH`: NixOS's systemd module already
      # populates environment.PATH with a base default at the same merge priority as a
      # plain assignment, so overwriting it outright throws "conflicting definition
      # values" (confirmed via a real nixosSystem eval).
      path = [ cfg.nebulaPackage ];

      # ncclient run only honors --server via NEBULA_COMMANDER_SERVER; every other
      # flag (--output-dir, --interval, --accept-dns, --nebula, --restart-service) must
      # be passed on the command line - there is no env-var equivalent for them.
      environment = {
        NEBULA_COMMANDER_SERVER = cfg.server;
        NEBULA_DEVICE_TOKEN_FILE = "${cfg.stateDir}/token";
        NEBULA_COMMANDER_CONFIG_DIR = cfg.stateDir;
      };

      serviceConfig = {
        Type = "simple";
        # Runs as root: Nebula needs to create a TUN device, matching the existing
        # privileged precedent on the other two platforms (Windows Service =
        # LocalSystem, Docker image = root in container) rather than attempting
        # CAP_NET_ADMIN-only hardening untested here.
        ExecStart = "${cfg.package}/bin/ncclient --server ${cfg.server} run ${concatStringsSep " " runArgs}";
        Restart = "on-failure";
        RestartSec = "30s";
      };
    };
  };
}
