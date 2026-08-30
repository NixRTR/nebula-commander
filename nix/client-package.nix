{ pkgs
# Named repoSrc, not src: callPackage auto-injects any argument literally named
# "src" from pkgs (which as of nixpkgs 25.11 is a throwing alias for a renamed
# package), silently overriding a default given here and breaking the build.
, repoSrc ? ../.
}:

pkgs.python313.pkgs.buildPythonApplication {
  pname = "nebula-commander-client";
  version = "0.1.8"; # matches client/pyproject.toml's setuptools_scm fallback_version
  pyproject = true;

  # pyproject.toml lives in client/ and maps package-dir "client" -> "." (the client/
  # directory itself is the "client" package), so build from client/, not the repo root.
  src = repoSrc + "/client";

  build-system = with pkgs.python313.pkgs; [
    setuptools
    wheel
    setuptools-scm
  ];

  dependencies = with pkgs.python313.pkgs; [
    requests
    keyring
  ];

  # No .git is present in the Nix store copy of the source, so setuptools_scm can't
  # detect a version from tags; pyproject.toml's fallback_version covers this, but
  # SETUPTOOLS_SCM_PRETEND_VERSION avoids relying on that fallback path entirely.
  SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.8";

  # No test suite is wired up for `client/` (nothing under pytest discovery here); skip
  # rather than have buildPythonApplication's default checkPhase fail on collection.
  doCheck = false;

  meta = {
    description = "Nebula Commander device client (ncclient)";
    homepage = "https://github.com/NixRTR/nebula-commander";
    license = pkgs.lib.licenses.gpl3Plus;
    mainProgram = "ncclient";
  };
}
