# syntax=docker/dockerfile:1
# Keycloak with intaka's provider (BASE: intaka's own image, built first) and
# the mobile app's login theme (context: intaka's demo/theme), as kulpay-mobile.
# The web theme, kulpay, is the provider's own (in its JAR); a folder theme of
# the same name would override it, which is why this one has its own name. The
# mobile client selects it (deploy/tools/client_themes.py). It travels in the
# image so it always matches the provider's templates; a deploy copies it out
# to the folder Keycloak mounts (bin/kulpay, state/theme).
ARG BASE
FROM ${BASE}
COPY --chown=keycloak:root kulpay /opt/keycloak/themes/kulpay-mobile
