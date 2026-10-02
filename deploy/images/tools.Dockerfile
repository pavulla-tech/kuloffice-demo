# syntax=docker/dockerfile:1
# Provisioning: intaka's realm scripts (context: intaka's demo/setup), the
# stack's bootstrap and reviewer seed (context `stack`), and the deploy's own
# (context `tools`). Run by `make init` and `make operator`.
FROM python:3.12-alpine
RUN apk add --no-cache curl
COPY . /setup
COPY --from=stack bootstrap.sh seed_reviewer.py /stack/
COPY --from=tools . /tools
RUN rm -rf /setup/__pycache__ && adduser -D -u 1000 tools
USER tools
ENTRYPOINT ["sh"]
CMD ["/tools/init.sh"]
