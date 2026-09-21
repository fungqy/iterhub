# ⚠ 本文件依赖 BuildKit(`--mount=type=cache`)。Docker 23+ 默认启用;若显式关闭
#   (DOCKER_BUILDKIT=0)会报 `Unknown flag: mount`,请改为 `DOCKER_BUILDKIT=1` 构建。
FROM node:22-alpine AS builder

WORKDIR /app

# 仓库用的是 pnpm:只有 pnpm-lock.yaml,**没有** package-lock.json,所以此前的
# `npm ci` 必然失败(EUSAGE)。这里显式钉住 pnpm 版本,避免"装到哪个 pnpm"随构建漂移。
# ⚠ 不要在 package.json 里加 `packageManager` 字段:pnpm 12 会把它当成需要解析的
#   依赖并要求更新 pnpm-lock.yaml,直接让下面的 --frozen-lockfile 报
#   ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE(已实测)。
RUN npm config set registry https://registry.npmmirror.com \
    && npm i -g pnpm@12.4.1

# pnpm-workspace.yaml 必须一起拷:它带 allowBuilds(esbuild / vue-demi / @parcel/watcher),
# pnpm 10+ 默认禁止依赖执行 postinstall,缺了它 esbuild 二进制不会落地 ⇒ vite build 失败。
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# --frozen-lockfile:严格按 pnpm-lock.yaml 安装,不重新解析 ⇒ 构建可复现
RUN --mount=type=cache,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm install --frozen-lockfile

COPY . .

# ⚠ 必须用 ENV 而不是只声明 ARG:vite.config.ts 的 loadEnv() 是从 process.env 取值,
#   只给 ARG 的话 base 会静默退化成 "/" ⇒ 所有静态资源 404。
ARG VITE_BASE=/iterhub/
ENV VITE_BASE=$VITE_BASE

# 注意:这里**没有** VITE_API_HOST。它只被 vite.config.ts 的 dev server proxy 使用,
# src/ 下无任何代码读它 ⇒ 传进构建对产物毫无影响(前端 api 基址恒为 VITE_BASE + 'api',
# 由 nginx 的 /iterhub/api 反代到后端)。别再把它加回来。
RUN pnpm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
