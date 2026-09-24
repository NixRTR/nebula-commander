{
  description = "Nebula Commander - self-hosted Nebula control plane";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages = {
          default = pkgs.callPackage ./nix/package.nix { };
          backend = pkgs.callPackage ./nix/package.nix { backendOnly = true; };
          frontend = pkgs.callPackage ./nix/package.nix { frontendOnly = true; };
          ncclient = pkgs.callPackage ./nix/client-package.nix { };
          ncclient-desktop = pkgs.callPackage ./nix/client-desktop-package.nix { };
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python313
            nodejs_22
            nebula
          ];
          shellHook = ''
            echo "Nebula Commander dev shell. Backend: cd backend && pip install -r requirements.txt && python -m uvicorn main:app --reload"
            echo "Frontend: cd frontend && npm install && npm run dev"
          '';
        };

        # `nix flake check` builds these. A bare flake-schema check wouldn't have caught
        # the systemd.services.<name>.environment.PATH conflict found in module.nix and
        # client-module.nix - that only surfaces when both modules are actually evaluated
        # as part of a real NixOS system, which is what this does.
        checks.nixos-module-eval =
          (nixpkgs.lib.nixosSystem {
            inherit system;
            modules = [
              ./nix/module.nix
              ./nix/client-module.nix
              ./nix/client-desktop-module.nix
              ({ ... }: {
                boot.isContainer = true;
                system.stateVersion = "25.11";
                services.nebula-commander = {
                  enable = true;
                  jwtSecretFile = "/run/secrets/jwt";
                  encryptionKeyFile = "/run/secrets/enc";
                  publicUrl = "https://nebula.example.com";
                  oidc = {
                    issuerUrl = "https://keycloak.example.com/realms/nc";
                    clientId = "nebula-commander";
                    clientSecretFile = "/run/secrets/oidc-client-secret";
                  };
                };
                services.ncclient = {
                  enable = true;
                  server = "https://nebula.example.com";
                  enrollCodeFile = "/run/secrets/enroll-code";
                  acceptDns = true;
                };
                # Also evaluates/builds client-desktop-module.nix as part of
                # this check - specifically to catch a services.dbus.packages/
                # polkit-action-file wiring mistake at eval/build time, the
                # same reason module.nix + client-module.nix are evaluated
                # together above rather than each in isolation.
                services.ncclient-desktop.enable = true;
              })
            ];
          }).config.system.build.toplevel;
      }
    )
    // {
      nixosModules.default = import ./nix/module.nix;
      nixosModules.client = import ./nix/client-module.nix;
      nixosModules.client-desktop = import ./nix/client-desktop-module.nix;
    };
}
