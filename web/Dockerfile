FROM node:24-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/tsconfig*.json web/vite.config.ts ./
COPY web/src ./src
COPY web/public ./public
# ProjectHome.tsx imports repo-root JSON configs (../../configs/site.json and
# ../../configs/industrial_site_v12.json), which resolve to /configs inside the
# image. The web build fails with TS2307 without this copy.
COPY configs /configs
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.29-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
RUN nginx -t
EXPOSE 80
