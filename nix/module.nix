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
  # Package has backend/ at root; run uvicorn from root so "backend.main" resolves
  rootSrc = nebulaCommanderPkg;
in

{
  options.services.nebula-commander = {
    enable = mkEnableOption "Nebula Commander self-hosted control plane";

    package = mkOption {
      type = types.package;
      # `${../backend}` (not `${toString (../backend)}`) so Nix copies the path into
      # the store as a real derivation input; `toString` bakes in a raw host
      # filesystem path instead, which a sandboxed builder can't see, silently
      # producing an empty backend/ (confirmed via a real nixosSystem build).
      default = pkgs.runCommand "nebula-commander-src" { } ''
        mkdir -p $out/backend
        cp -r ${../backend}/* $out/backend/
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

    encryptionKeyFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = "Path to encryption key file (Fernet key for DB/cert encryption). If null, auto-generated at /var/lib/nebula-commander/encryption-key";
    };

    debug = mkOption {
      type = types.bool;
      default = false;
      description = "Enable debug mode";
    };

    publicUrl = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Public URL of this instance (e.g. https://nebula.example.com). Used to derive the OIDC redirect URI and for redirect validation.";
    };

    standaloneAdminBootstrap = mkOption {
      type = types.bool;
      default = false;
      description = "Allow the unauthenticated dev-token admin bootstrap endpoint when no OIDC provider is configured. Must be explicitly opted into.";
    };

    corsOrigins = mkOption {
      type = types.str;
      default = "*";
      description = "CORS origins: \"*\" or a comma-separated list.";
    };

    sessionHttpsOnly = mkOption {
      type = types.bool;
      default = false;
      description = "Set to true in production when served over HTTPS.";
    };

    allowedRedirectHosts = mkOption {
      type = types.str;
      default = "";
      description = "Comma-separated allowed hosts for OAuth/OIDC redirects. Empty derives from oidc.redirectUri/publicUrl.";
    };

    oidc = {
      issuerUrl = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "OIDC issuer URL (e.g. Keycloak realm URL). Leave null to use dev-token auth instead.";
      };
      publicIssuerUrl = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Public-facing OIDC issuer URL for browser redirects (logout, etc.), if different from issuerUrl.";
      };
      clientId = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "OIDC client ID.";
      };
      clientSecretFile = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = "Path to a file containing the OIDC client secret (e.g. managed by sops-nix).";
      };
      redirectUri = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "OIDC redirect URI. If unset and publicUrl is set, derived as publicUrl + /api/auth/callback.";
      };
      scopes = mkOption {
        type = types.str;
        default = "openid profile email";
        description = "OIDC scopes to request.";
      };
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

    systemd.services.nebula-commander-encryption-init = mkIf (cfg.encryptionKeyFile == null) {
      description = "Generate encryption key for Nebula Commander";
      wantedBy = [ "multi-user.target" ];
      before = [ "nebula-commander.service" ];
      after = [ "network.target" ] ++ optional (cfg.jwtSecretFile == null) "nebula-commander-jwt-init.service";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if [ ! -f /var/lib/nebula-commander/encryption-key ]; then
          ${pythonEnv}/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /var/lib/nebula-commander/encryption-key
          chmod 640 /var/lib/nebula-commander/encryption-key
          chown nebula-commander:nebula-commander /var/lib/nebula-commander/encryption-key
        fi
      '';
    };

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
      after = [ "network.target" ]
        ++ optional (cfg.jwtSecretFile == null) "nebula-commander-jwt-init.service"
        ++ optional (cfg.encryptionKeyFile == null) "nebula-commander-encryption-init.service";
      wantedBy = [ "multi-user.target" ];
      requires = optional (cfg.jwtSecretFile == null) "nebula-commander-jwt-init.service"
        ++ optional (cfg.encryptionKeyFile == null) "nebula-commander-encryption-init.service";

      # Extend PATH via the `path` option, not `environment.PATH` directly: NixOS's
      # systemd module already populates environment.PATH with a base default at the
      # same merge priority as a plain assignment here, so overwriting it outright
      # throws "conflicting definition values" (confirmed via a real nixosSystem eval).
      path = [ pkgs.nebula ];

      environment = {
        NEBULA_COMMANDER_DATABASE_URL = "sqlite+aiosqlite:///${cfg.databasePath}";
        NEBULA_COMMANDER_CERT_STORE_PATH = cfg.certStorePath;
        NEBULA_COMMANDER_PORT = toString cfg.backendPort;
        NEBULA_COMMANDER_JWT_SECRET_FILE = if cfg.jwtSecretFile != null then toString cfg.jwtSecretFile else "/var/lib/nebula-commander/jwt-secret";
        NEBULA_COMMANDER_ENCRYPTION_KEY_FILE = if cfg.encryptionKeyFile != null then toString cfg.encryptionKeyFile else "/var/lib/nebula-commander/encryption-key";
        NEBULA_COMMANDER_DEBUG = if cfg.debug then "true" else "false";
        NEBULA_COMMANDER_CORS_ORIGINS = cfg.corsOrigins;
        NEBULA_COMMANDER_SESSION_HTTPS_ONLY = if cfg.sessionHttpsOnly then "true" else "false";
        NEBULA_COMMANDER_STANDALONE_ADMIN_BOOTSTRAP = if cfg.standaloneAdminBootstrap then "true" else "false";
      }
      // optionalAttrs (cfg.publicUrl != null) { NEBULA_COMMANDER_PUBLIC_URL = cfg.publicUrl; }
      // optionalAttrs (cfg.allowedRedirectHosts != "") { NEBULA_COMMANDER_ALLOWED_REDIRECT_HOSTS = cfg.allowedRedirectHosts; }
      // optionalAttrs (cfg.oidc.issuerUrl != null) { NEBULA_COMMANDER_OIDC_ISSUER_URL = cfg.oidc.issuerUrl; }
      // optionalAttrs (cfg.oidc.publicIssuerUrl != null) { NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL = cfg.oidc.publicIssuerUrl; }
      // optionalAttrs (cfg.oidc.clientId != null) { NEBULA_COMMANDER_OIDC_CLIENT_ID = cfg.oidc.clientId; }
      // optionalAttrs (cfg.oidc.clientSecretFile != null) { NEBULA_COMMANDER_OIDC_CLIENT_SECRET_FILE = toString cfg.oidc.clientSecretFile; }
      // optionalAttrs (cfg.oidc.redirectUri != null) { NEBULA_COMMANDER_OIDC_REDIRECT_URI = cfg.oidc.redirectUri; }
      // optionalAttrs (cfg.oidc.issuerUrl != null) { NEBULA_COMMANDER_OIDC_SCOPES = cfg.oidc.scopes; };

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
