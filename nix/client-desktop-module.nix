{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.services.ncclient-desktop;
in

{
  options.services.ncclient-desktop = {
    enable = mkEnableOption "Nebula Commander desktop app (GTK4/libadwaita)";

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ./client-desktop-package.nix { };
      defaultText = "pkgs.callPackage ./client-desktop-package.nix { }";
      description = "nebula-commander-desktop package.";
    };
  };

  # Deliberately minimal - unlike client-module.nix (the systemd service
  # this app talks to), there's no D-Bus/polkit wiring to do here: the
  # service side already registers org.beardedtek.NebulaCommander1's bus
  # policy and polkit action (see client-module.nix's services.dbus.packages
  # and security.polkit.extraConfig), and this app is purely a consumer of
  # that API over client/linux/dbus_client.py - no filesystem permissions,
  # group membership, or relogin step needed for it to work, on any host
  # that already has services.ncclient.enable = true.
  config = mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
  };
}
