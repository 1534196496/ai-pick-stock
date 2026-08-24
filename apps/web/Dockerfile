FROM node:24.15.0-alpine AS build

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY apps/web/index.html apps/web/tsconfig.json apps/web/vite.config.ts ./
COPY apps/web/src ./src
RUN npm run build

FROM nginx:1.29-alpine

RUN rm /etc/nginx/conf.d/default.conf \
    && sed -i -e '/^user /d' -e 's#pid .*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx /var/run /usr/share/nginx/html

COPY --chown=nginx:nginx deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

USER nginx

EXPOSE 8080

ENTRYPOINT []

CMD ["nginx", "-g", "daemon off;"]
