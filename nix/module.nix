{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.services.nebula-commander;
  # When used as a flake input, use the package from the flake; otherwise build from path
  nebulaCommanderPkg = cfg.package;
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
  # Package has backend/ at root; run uvicorn from root so "backend.main" resolves
  rootSrc = nebulaCommanderPkg;
in

{
  options.services.nebula-commander = {
    enable = mkEnableOption "Nebula Commander self-hosted control plane";

    package = mkOption {
      type = types.package;
      default = pkgs.runCommand "nebula-commander-src" { } ''
        mkdir -p $out/backend
        cp -r ${toString (../../backend)}/* $out/backend/
      '';
      defaultText = "backend source from repo";
      description = "Nebula Commander package (backend source)";
    };

    port = mkOption {
      type = types.port;
      default = 8080;
      description = "Port for the HTTP API (when using nginx)";
    };

    backendPort = mkOption {
      type = types.port;
      default = 8081;
      description = "Port for the FastAPI backend (internal)";
    };

    databasePath = mkOption {
      type = types.str;
      default = "/var/lib/nebula-commander/db.sqlite";
      description = "SQLite database file path";
    };

    certStorePath = mkOption {
      type = types.str;
      default = "/var/lib/nebula-commander/certs";
      description = "Directory for CA and host certificates";
    };

    jwtSecretFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = "Path to JWT secret file (e.g. managed by sops-nix)";
    };

    debug = mkOption {
      type = types.bool;
      default = false;
      description = "Enable debug mode";
    };
  };

  config = mkIf cfg.enable {
    users.users.nebula-commander = {
      isSystemUser = true;
      group = "nebula-commander";
      description = "Nebula Commander service user";
    };
    users.groups.nebula-commander = { };

    systemd.tmpfiles.rules = [
      "d /var/lib/nebula-commander 0750 nebula-commander nebula-commander -"
      "d ${cfg.certStorePath} 0750 nebula-commander nebula-commander -"
      "d /run/nebula-commander 0750 nebula-commander nebula-commander -"
    ];

    systemd.services.nebula-commander-jwt-init = mkIf (cfg.jwtSecretFile == null) {
      description = "Generate JWT secret for Nebula Commander";
      wantedBy = [ "multi-user.target" ];
      before = [ "nebula-commander.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if [ ! -f /var/lib/nebula-commander/jwt-secret ]; then
          ${pkgs.openssl}/bin/openssl rand -hex 32 > /var/lib/nebula-commander/jwt-secret
          chmod 640 /var/lib/nebula-commander/jwt-secret
          chown nebula-commander:nebula-commander /var/lib/nebula-commander/jwt-secret
        fi
      '';
    };

    systemd.services.nebula-commander = {
      description = "Nebula Commander API (FastAPI)";
      after = [ "network.target" ] ++ optional (cfg.jwtSecretFile == null) "nebula-commander-jwt-init.service";
      wantedBy = [ "multi-user.target" ];
      requires = optional (cfg.jwtSecretFile == null) "nebula-commander-jwt-init.service";

      environment = {
        NEBULA_COMMANDER_DATABASE_URL = "sqlite+aiosqlite:///${cfg.databasePath}";
        NEBULA_COMMANDER_CERT_STORE_PATH = cfg.certStorePath;
        NEBULA_COMMANDER_PORT = toString cfg.backendPort;
        JWT_SECRET_FILE = if cfg.jwtSecretFile != null then toString cfg.jwtSecretFile else "/var/lib/nebula-commander/jwt-secret";
        DEBUG = if cfg.debug then "true" else "false";
        PATH = "/run/current-system/sw/bin:${pkgs.nebula}/bin";
      };

      serviceConfig = {
        Type = "simple";
        User = "nebula-commander";
        Group = "nebula-commander";
        WorkingDirectory = rootSrc;
        ExecStart = "${pythonEnv}/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port ${toString cfg.backendPort}";
        Restart = "always";
        RestartSec = "10s";
        PrivateTmp = true;
        ProtectHome = true;
        ReadWritePaths = [ "/var/lib/nebula-commander" "/run/nebula-commander" (dirOf cfg.databasePath) cfg.certStorePath ];
        NoNewPrivileges = true;
      };
    };
  };
}
