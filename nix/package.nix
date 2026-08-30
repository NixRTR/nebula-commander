{ pkgs
, backendOnly ? false
, frontendOnly ? false
# Named repoSrc, not src: callPackage auto-injects any argument literally named
# "src" from pkgs (which as of nixpkgs 25.11 is a throwing alias for a renamed
# package), silently overriding a default given here and breaking every build.
, repoSrc ? ../.
}:

let
  backendSrc = repoSrc + "/backend";

  pythonEnv = pkgs.python313.withPackages (ps: with ps; [
    fastapi
    uvicorn
    websockets
    sqlalchemy
    aiosqlite
    pydantic
    pydantic-settings
    email-validator
    pyyaml
    python-jose
    httpx
    authlib
    itsdangerous
    cryptography
    aiosmtplib
    jinja2
  ]);
in

if backendOnly then
  # backend/ lands at $out/backend, matching the default (unqualified) output below,
  # so this is a valid drop-in for services.nebula-commander.package - module.nix's
  # WorkingDirectory + "uvicorn backend.main:app" needs backend/ as a subdirectory,
  # not $out itself.
  pkgs.runCommand "nebula-commander-backend" { } ''
    mkdir -p $out/backend
    cp -r ${backendSrc}/* $out/backend/
  ''
else if frontendOnly then
  (pkgs.buildNpmPackage {
    pname = "nebula-commander-frontend";
    version = "0.1.0";
    src = repoSrc + "/frontend";
    # Computed via `nix run nixpkgs#prefetch-npm-deps -- frontend/package-lock.json`.
    # Must be recomputed the same way whenever frontend/package-lock.json changes.
    npmDepsHash = "sha256-TjjpA2Yk+cfiHaYISIb5u47Ppd5hslOr035IaUWXm4M=";
    installPhase = "cp -r dist $out";
  })
else
  pkgs.runCommand "nebula-commander" { } ''
    mkdir -p $out/backend
    cp -r ${backendSrc}/* $out/backend/
    echo "Backend source at $out/backend; use Python env: ${pythonEnv}"
  ''
