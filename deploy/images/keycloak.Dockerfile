# syntax=docker/dockerfile:1
# Keycloak with intaka's provider (BASE: intaka's own image, built first) and
# the KulPay login theme (context: intaka's demo/theme). The theme travels in
# the image so it always matches the provider's templates; a deploy copies it
# out to the folder Keycloak mounts (bin/kulpay, state/theme).
ARG BASE
FROM ${BASE}
COPY --chown=keycloak:root kulpay /opt/keycloak/themes/kulpay
