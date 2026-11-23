FROM node:22-alpine AS build

WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV API_UPSTREAM=api:8000 PORT=80 NGINX_ENVSUBST_FILTER='API_UPSTREAM|PORT'
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/" || exit 1
