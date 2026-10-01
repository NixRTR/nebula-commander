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

    adminGroups = mkOption {
      type = types.nullOr (types.listOf types.str);
      default = [ "wheel" "sudo" ];
      example = [ "wheel" ];
      description = ''
        Active local users in any of these groups may change this device's
        Nebula network without a password: the desktop app's settings,
        enrollment and route/exit-node changes (polkit action
        org.beardedtek.NebulaCommander1.manage), and start/stop/restart of
        ncclient.service. Everyone else needs an administrator's password.
        Reading status is open to any active local user regardless.

        null = any active local user (the old behaviour - only sensible on a
        single-user machine).
      '';
    };
  };

  config = mkIf cfg.enable {
    # cfg.package on PATH for its share/polkit-1/actions (NixOS's polkit module,
    # when security.polkit.enable is on - client-desktop-module.nix turns it on -
    # only links actions from systemPackages; services.dbus.packages below
    # covers the bus policy only). Without polkitd every D-Bus call is refused
    # (fails closed), which is fine headless. Plus a wrapper so `sudo ncclient routes ...`
    # / `sudo ncclient enroll ...` act on the service's own state instead of
    # root's per-user defaults. hiPrio: both provide bin/ncclient, and
    # system-path's buildEnv otherwise picks one by list order.
    environment.systemPackages = [
      cfg.package
      (lib.hiPrio (pkgs.writeShellScriptBin "ncclient" ''
        export NEBULA_COMMANDER_CONFIG_DIR=${cfg.stateDir}
        export NEBULA_DEVICE_TOKEN_FILE=${cfg.stateDir}/token
        export NEBULA_COMMANDER_OUTPUT_DIR=${cfg.outputDir}
        exec ${cfg.package}/bin/ncclient "$@"
      ''))
    ];

    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0700 root root -"
      "d ${cfg.outputDir} 0700 root root -"
    ];

    # Registers cfg.package's shipped D-Bus bus policy (system.d/*.conf) for
    # client/linux/dbus_server.py's org.beardedtek.NebulaCommander1 service,
    # which `ncclient run` (below) hosts. (Its polkit action declaration comes
    # from environment.systemPackages above, not from here.) No manual
    # `systemctl reload dbus` step needed the way the .deb path's postinst
    # requires, since system activation reloads the affected services itself.
    services.dbus.packages = [ cfg.package ];

    # Who may change the device's network: org.beardedtek.NebulaCommander1's
    # manage action (dbus_server.py - settings/enroll/routes) and systemd's
    # manage-units for start/stop/restart of exactly ncclient.service
    # (client/linux/service_control.py). Active local members of adminGroups
    # get YES, everyone else AUTH_ADMIN. Mirrors packaging/deb/service/payload/
    # usr/share/polkit-1/rules.d/org.nixrtr.nebulacommander.rules (which
    # hardcodes sudo/wheel) - keep the two in sync.
    security.polkit.extraConfig = let
      groups = builtins.toJSON cfg.adminGroups; # JSON array or null - valid JS either way
    in ''
      polkit.addRule(function(action, subject) {
          var isNcclientUnit =
              action.id == "org.freedesktop.systemd1.manage-units" &&
              action.lookup("unit") == "ncclient.service" &&
              ["start", "stop", "restart"].indexOf(action.lookup("verb")) != -1;
          if (action.id != "org.beardedtek.NebulaCommander1.manage" && !isNcclientUnit) {
              return polkit.Result.NOT_HANDLED;
          }
          var groups = ${groups};
          if (subject.active && subject.local &&
              (groups === null || groups.some(function(g) { return subject.isInGroup(g); }))) {
              return polkit.Result.YES;
          }
          return polkit.Result.AUTH_ADMIN;
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
      # nftables/iproute2: linux_routing.apply_routes sets up forwarding/NAT for
      # routes this node advertises as a subnet router / exit node.
      path = [ cfg.nebulaPackage pkgs.nftables pkgs.iproute2 ];

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
