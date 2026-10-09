# syntax=docker/dockerfile:1
# kuloffice, from a kuloffice checkout, with kuloffice-worker beside it (the
# instruction worker; the kuloffice-worker compose service runs it). The license public key is linked in:
# pass it with --build-arg LICENSE_PUBLIC_KEY (the Makefile reads it from the
# checkout's keys/public.pem.base64), or the binary refuses every license.
# Compiled on the builder's own platform for the target one: no emulation.
FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
COPY cmd ./cmd
COPY internal ./internal
COPY pkg ./pkg
COPY proto ./proto
ARG LICENSE_PUBLIC_KEY
ARG LICENSE_ISSUER=pavulla.com
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    test -n "$LICENSE_PUBLIC_KEY" || { echo "LICENSE_PUBLIC_KEY is empty" >&2; exit 1; }; \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -tags 'metrics tracing cache' -ldflags "\
      -X github.com/pavulla-tech/kuloffice/internal/commands.binaryName=kuloffice \
      -X github.com/pavulla-tech/kuloffice/internal/license.publicKey=$LICENSE_PUBLIC_KEY \
      -X github.com/pavulla-tech/kuloffice/internal/license.issuer=$LICENSE_ISSUER" \
      -o /out/kuloffice ./cmd/kuloffice && \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/kuloffice-worker ./cmd/kuloffice-worker
FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && adduser -D -u 1000 kuloffice
COPY --from=build /out/ /usr/local/bin/
USER kuloffice
WORKDIR /home/kuloffice
ENTRYPOINT ["kuloffice"]
CMD ["serve"]
