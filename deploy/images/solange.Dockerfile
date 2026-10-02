# syntax=docker/dockerfile:1
# Solange's new core (cmd/solange), from a solange checkout. Its subcommands
# are `serve`, `migrate` and the app/key/webhook management (see main.go).
FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -o /out/solange ./cmd/solange
FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && adduser -D -u 1000 solange && mkdir /geoip && chown solange /geoip
COPY --from=build /out/solange /usr/local/bin/solange
USER solange
ENTRYPOINT ["solange"]
CMD ["serve"]
