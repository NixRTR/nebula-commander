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

  # Deliberately minimal - the service side (client-module.nix) registers
  # org.beardedtek.NebulaCommander1's bus policy, polkit action and the
  # adminGroups rule, and this app is purely a consumer of that API over
  # client/linux/dbus_client.py. The one thing needed here is polkitd itself
  # (below). Changes need membership in services.ncclient.adminGroups
  # (default wheel/sudo); viewing works for any active local user.
  config = mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];

    # Every D-Bus call this app makes is authorized by polkit
    # (client/linux/dbus_server.py's CheckAuthorization), and NixOS's polkit
    # is opt-in. Without polkitd those calls all fail closed (refused), and
    # client-module.nix's security.polkit.extraConfig rule and its action
    # file aren't even installed. Desktop environments usually enable it
    # already; mkDefault so an explicit setting still wins.
    security.polkit.enable = mkDefault true;
  };
}
