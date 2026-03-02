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
      }
    )
    // {
      nixosModules.default = import ./nix/module.nix;
    };
}
