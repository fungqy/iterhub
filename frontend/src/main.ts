import { createApp } from "vue";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import ConfirmationService from "primevue/confirmationservice";
import Tooltip from "primevue/tooltip";
import { definePreset } from "@primeuix/themes";
import Aura from "@primeuix/themes/aura";
import "primeicons/primeicons.css";
import "./assets/styles/tailwind.css";
import "./assets/styles/index.scss";
import App from "./App.vue";
import router from "./router";
import { useAuthStore } from "@/stores/auth";
import { notify } from "@/utils/appToast";
import { initTheme } from "@/composables/useTheme";
import { primevueLocale } from "@/constants/primevueLocale";

// 基于 Aura 预设定制品牌绿主题(精确匹配 --accent: #aadb1e)
// 注意:--ih-brand(tokens.scss)须与下方 primary 500 系列同源,改一处必须同步另一处。
// primary-500 仅用于填充,文字/图标一律用 primary-900(--ih-brand-text),见 components.scss。
const IterhubPreset = definePreset(Aura, {
    semantic: {
        primary: {
            50: "{lime.50}",
            100: "{lime.100}",
            200: "{lime.200}",
            300: "{lime.300}",
            400: "#b9e556",
            500: "#aadb1e", // 品牌绿
            600: "#8cb819",
            700: "#739614",
            800: "#5a750f",
            900: "#415a0b",
            950: "#2c3d07",
        },
    },
});

const app = createApp(App);

const pinia = createPinia();
app.use(pinia);
app.use(router);
app.use(PrimeVue, {
    // 中文文案全局注入:此前未配置 locale 时,PrimeVue 会在下拉框无选项等处
    // 直接渲染内置英文(如 "No available options")。定义见 constants/primevueLocale.ts。
    locale: primevueLocale,
    theme: {
        preset: IterhubPreset,
        options: {
            // 暗色开关由 <html class="dark"> 控制,须与 composables/useTheme.ts
            // 及 tokens.scss 的 :root.dark 三处保持一致。
            // 不用默认的 'system':那会跟随系统偏好而无法被用户覆盖。
            darkModeSelector: ".dark",
            // 层序必须与 tailwind.css 的 `@layer reset, theme, primevue, ds, utilities;`
            // 逐字一致 —— 两处任一改动都必须同步另一处。
            // reset 是最低层:UA 默认值修正(base.scss)放这里,保证能被 PrimeVue 组件样式、
            // .ds-* 组件类与 Tailwind 工具类覆盖。
            cssLayer: { name: "primevue", order: "reset, theme, primevue, ds, utilities" },
        },
    },
});
app.use(ToastService);
app.use(ConfirmationService);
app.directive("tooltip", Tooltip);

// 全局错误兜底:组件渲染或 setup 期间抛错时,弹一个 Toast 提示并
// 打印到 console,避免页面直接白屏。生产环境可改为上报到 Sentry 等。
app.config.errorHandler = (err, _instance, info) => {
    console.error("[Vue error]", info, err);
    try {
        notify("error", "页面发生错误,已记录到控制台");
    } catch {
        // toast 未就绪时静默,不再次抛错
    }
};

app.config.warnHandler = (msg) => {
    // 不向用户暴露 Vue 的开发警告(噪音),仅控制台输出
    console.warn("[Vue warn]", msg);
};

// 初始化时从 localStorage 恢复登录状态
const authStore = useAuthStore();
authStore.initFromStorage();

// 初始化主题(须在 mount 前完成,避免首帧闪白)
initTheme();

app.mount("#app");
