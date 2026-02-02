{
  description = "Nebula Commander - self-hosted Nebula control plane";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in
    {
      packages.${system} = {
        default = pkgs.callPackage ./nix/package.nix { };
        backend = pkgs.callPackage ./nix/package.nix { backendOnly = true; };
        frontend = pkgs.callPackage ./nix/package.nix { frontendOnly = true; };
      };

      nixosModules.default = import ./nix/module.nix;

      devShells.${system}.default = pkgs.mkShell {
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
    };
}
