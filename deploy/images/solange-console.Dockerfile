# syntax=docker/dockerfile:1
# Solange's console (context: solange's console/). Settings at run time
# (SOLANGE_*).
FROM node:22-alpine3.20 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build
FROM node:22-alpine3.20
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app ./
USER node
CMD ["node_modules/.bin/next", "start", "--port", "3200"]
