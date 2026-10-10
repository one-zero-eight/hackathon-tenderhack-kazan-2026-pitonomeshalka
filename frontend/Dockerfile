# Сборка из контекста frontend/:
#   docker build -t ktru-frontend frontend/
FROM node:24-alpine AS build

WORKDIR /app

# pnpm по lockfile v9; HUSKY=0 отключает prepare-хук (в контейнере нет .git)
RUN npm install -g pnpm@10
ENV HUSKY=0

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

FROM nginx:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
