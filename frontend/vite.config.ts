import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
// @ts-ignore - Node.js built-in modules
import { resolve, dirname } from "path";
// @ts-ignore - Node.js built-in modules
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), "");
    const apiHost = env.VITE_API_HOST || "http://localhost:8000";

    const base = env.VITE_BASE || "/";

    return {
        base,
        plugins: [
            vue(),
            tailwindcss(),
            AutoImport({
                imports: ["vue", "vue-router", "pinia"],
                dts: "src/auto-imports.d.ts",
            }),
            Components({
                dts: "src/components.d.ts",
            }),
        ],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        css: {
            preprocessorOptions: {
                scss: {
                    // 显式切换到 modern-compiler API,
                    // 消除 sass 1.69+ 默认 legacy API 的 deprecation 警告,
                    // 并与 Sass 2.0 保持兼容。
                    api: "modern-compiler",
                },
            },
        },
        build: {
            // 把 echarts / primevue 拆成独立 chunk,避免首屏加载 1.2MB 单文件
            rollupOptions: {
                output: {
                    manualChunks: {
                        vue: ["vue", "vue-router", "pinia"],
                        prime: ["primevue", "@primeuix/themes", "primeicons"],
                        echarts: ["echarts"],
                        // axios 是高频依赖,单独拆出
                        // 能让首屏 chunk 进一步减小,缓存命中率也更高
                        axios: ["axios"],
                    },
                },
            },
        },
        server: {
            port: parseInt(env.PORT || "3000"),
            proxy: {
                "/api": {
                    target: apiHost,
                    changeOrigin: true,
                },
            },
        },
    };
});
