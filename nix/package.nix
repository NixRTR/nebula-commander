{ pkgs
, backendOnly ? false
, frontendOnly ? false
, src ? ../../.
}:

let
  backendSrc = src + "/backend";

  pythonEnv = pkgs.python313.withPackages (ps: with ps; [
    fastapi
    uvicorn
    websockets
    sqlalchemy
    aiosqlite
    pydantic
    pydantic-settings
    python-jose
    httpx
  ]);
in

if backendOnly then
  pkgs.runCommand "nebula-commander-backend" { } ''
    mkdir -p $out
    cp -r ${backendSrc}/* $out/
  ''
else if frontendOnly then
  (pkgs.buildNpmPackage {
    pname = "nebula-commander-frontend";
    version = "0.1.0";
    src = src + "/frontend";
    npmDepsHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    NODE_OPTIONS = "--openssl-legacy-provider";
    installPhase = "cp -r dist $out";
  })
else
  pkgs.runCommand "nebula-commander" { } ''
    mkdir -p $out/backend
    cp -r ${backendSrc}/* $out/backend/
    echo "Backend source at $out/backend; use Python env: ${pythonEnv}"
  ''
