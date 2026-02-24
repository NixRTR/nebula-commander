# Nebula Commander custom Keycloak image
# Bakes realm import + nebula theme and runs substitution + kc.sh via startup script.

FROM quay.io/keycloak/keycloak:26.5.3

# Realm import (placeholders substituted at container start via env); keycloak user must own so startup script can overwrite
COPY --chown=keycloak:keycloak docker/keycloak-import /opt/keycloak/data/import

# Custom login/account theme (nebula background + logo).
# For the nebula background, ensure nebula-bg.webp is in keycloak-theme/nebula/login/resources/img/
# (or copy from frontend/public/nebula-bg.webp) before building.
COPY docker/keycloak-theme /opt/keycloak/themes

# Startup script: substitute NEBULA_COMMANDER_* in realm JSON, then start Keycloak with --import-realm
# Use COPY --chmod to avoid RUN chmod (Keycloak image denies chmod/rename in /opt/keycloak and /tmp).
# Keep script with LF in repo (.gitattributes: docker/keycloak/*.sh text eol=lf) so no CRLF fix in image.
COPY --chmod=755 docker/keycloak/nebula-commander-start.sh /opt/keycloak/nebula-commander-start.sh

# Strip CRLF at runtime and run script (repo may be checked out with CRLF on Windows/WSL)
ENTRYPOINT ["/bin/sh", "-c", "sed 's/\\r$//' /opt/keycloak/nebula-commander-start.sh | /bin/sh"]
