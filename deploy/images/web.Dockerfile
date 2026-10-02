# syntax=docker/dockerfile:1
# The KulPay web app, from a kulpay-web checkout. Its settings are read at run
# time (KULPAY_*), so one image serves any host.
FROM node:22-alpine3.20 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
# The build type-checks the tests too, whose matchers vitest.setup.ts declares.
COPY next.config.ts tsconfig.json postcss.config.mjs vitest.config.mts vitest.setup.ts ./
COPY messages ./messages
COPY public ./public
COPY src ./src
RUN npm run build
FROM node:22-alpine3.20
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app ./
USER node
CMD ["node_modules/.bin/next", "start"]
