FROM node:18-alpine AS builder

WORKDIR /app

COPY package*.json ./

# 在 RUN npm ci 之前添加换源指令
RUN npm config set registry https://registry.npmmirror.com
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY . .

ARG VITE_API_HOST=/api
ENV VITE_API_HOST=$VITE_API_HOST

ARG VITE_BASE=/iterhub/
ENV VITE_BASE=$VITE_BASE

RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
