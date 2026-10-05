# syntax=docker/dockerfile:1.7

# ---------- Build stage ----------
FROM node:22-alpine AS build

WORKDIR /app

# Build-time arg consumed by Vite. Declared early so it does not bust the
# dependency layer when only source files change.
ARG VITE_BACKEND_URL=/api
ENV VITE_BACKEND_URL=${VITE_BACKEND_URL}
ENV NODE_ENV=production
ENV CI=true

# Install deps first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --prefer-offline --include=dev

# Copy the Vite app. .dockerignore keeps node_modules, dist, secrets, and
# other local-only files out of the image build context.
COPY . .

# Build the static production bundle (tsc + vite build).
RUN npm run build


# ---------- Runtime stage ----------
FROM nginx:1.27-alpine AS runtime

# Overwrite default SPA-unfriendly nginx config.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets from the Vite build.
COPY --from=build /app/dist /usr/share/nginx/html


EXPOSE 80


CMD ["nginx", "-g", "daemon off;"]
