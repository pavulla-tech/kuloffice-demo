# syntax=docker/dockerfile:1
# boquisso-fileserver, from its checkout: the file API in front of MinIO.
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
COPY main.go ./
COPY dnf ./dnf
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -o /out/boquisso .
FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && adduser -D -u 1000 boquisso
COPY --from=build /out/boquisso /usr/local/bin/boquisso
USER boquisso
ENTRYPOINT ["boquisso"]
