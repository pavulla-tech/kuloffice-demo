# syntax=docker/dockerfile:1
# intaka's token panel (context: intaka's demo/token-panel), run by
# stack/token-panel.py (build context `stack`), which binds every interface so
# the published port reaches it, and keeps enrolled device keys on /panel.
FROM python:3.12-alpine
COPY . /src
COPY --from=stack token-panel.py /stack/token-panel.py
RUN adduser -D -u 1000 panel && mkdir /panel && chown panel /panel
USER panel
VOLUME /panel
CMD ["python3", "/stack/token-panel.py"]
