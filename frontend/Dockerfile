# ===== Stage 1: Builder =====
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency definition files first for better layer caching
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# ===== Stage 2: Runtime (nginx) =====
FROM nginx:alpine

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom nginx configuration for SPA routing + API proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Security: drop root privileges
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
