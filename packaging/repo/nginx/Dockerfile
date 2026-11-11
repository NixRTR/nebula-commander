# The signed apt + rpm repository and client update manifest served at
# https://pkgs.nebulacommander.com, as a static nginx image.
#
# Built by .github/workflows/publish-package-repo.yml with a context holding this file,
# default.conf, and the generated site/ (packaging/repo/build_repo.py). There are no RUN
# steps, so the arm64 image builds without emulation.
FROM nginx:stable-alpine

ENV NGINX_ENTRYPOINT_QUIET_LOGS=1
COPY default.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
