# syntax=docker/dockerfile:1.9

# ---- Base -------------------------------------------------------------------
FROM node:22-alpine AS base
RUN apk add --no-cache libc6-compat
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# ---- Dependencies -----------------------------------------------------------
FROM base AS deps
COPY package.json package-lock.json* ./
# `npm ci` when a lockfile exists (reproducible); fall back on first bootstrap.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---- Development ------------------------------------------------------------
FROM base AS development
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- Builder ----------------------------------------------------------------
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined at build time, so they must be present here.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_APP_NAME="MemeScope AI"
ARG NEXT_PUBLIC_ENVIRONMENT=production
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME \
    NEXT_PUBLIC_ENVIRONMENT=$NEXT_PUBLIC_ENVIRONMENT

RUN npm run build

# ---- Production -------------------------------------------------------------
FROM base AS production
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
# `output: "standalone"` bundles only the files the server actually needs.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
