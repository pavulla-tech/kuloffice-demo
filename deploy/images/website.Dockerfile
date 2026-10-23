# syntax=docker/dockerfile:1
# The KulPay website (Hugo, static), from a kulpay-website checkout, served by
# nginx. BASE_URL is the public address (make images passes
# WEBSITE_PUBLIC_URL); the default "/" gives root-relative links for any host.
# The build stage runs on the laptop's own platform: its output is plain files.
FROM --platform=$BUILDPLATFORM alpine:3.20 AS build
ARG HUGO_VERSION=0.162.1
ARG BUILDARCH
RUN apk add --no-cache curl && cd /tmp && \
    base="https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}" && \
    file="hugo_${HUGO_VERSION}_linux-${BUILDARCH}.tar.gz" && \
    curl -fsSLO "$base/$file" && curl -fsSL "$base/hugo_${HUGO_VERSION}_checksums.txt" | grep " $file\$" | sha256sum -c - && \
    tar -xzf "$file" -C /usr/local/bin hugo && rm "$file"
WORKDIR /site
COPY . .
ARG BASE_URL=/
RUN hugo --minify --baseURL "$BASE_URL" -d /out

FROM nginx:1.27-alpine
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    absolute_redirect off;
    gzip on;
    gzip_types text/css application/javascript image/svg+xml application/json;
    error_page 404 /404.html;
    location / { try_files $uri $uri/ =404; add_header Cache-Control "no-cache"; }
    # Hugo fingerprints these; a new build gets new names.
    location ~* \.(css|js)$ { add_header Cache-Control "public, max-age=31536000, immutable"; }
    location ~* \.(png|jpe?g|svg|webp|ico)$ { add_header Cache-Control "public, max-age=86400"; }
}
EOF
COPY --from=build /out /usr/share/nginx/html
