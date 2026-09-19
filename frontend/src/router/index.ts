import { createRouter, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import { authApi } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";

// ── 导航的唯一源 ──────────────────────────────────────────────
// 侧边栏由本文件的 routes 派生(见 components/layout/MainLayout.vue),
// 不再在组件里另维护一份菜单列表。新增页面只需在这里加一条路由。
//
// meta 约定:
//   title  —— 侧边栏文案 / 顶栏页头 / 页面 <h1> 共用
//   icon   —— PrimeIcons 类名。此前这里是 Element Plus 图标名(Odometer/FolderOpened…),
//             与组件内实际使用的 pi pi-* 不一致且无人读取,已统一为 PrimeIcons。
//   order  —— 侧边栏排序,必须是数字且唯一
//   hidden —— 不进入侧边栏(登录页、404 页)
const routes: RouteRecordRaw[] = [
    {
        path: "/login",
        name: "Login",
        component: () => import("@/views/auth/Login.vue"),
        meta: { title: "登录", hidden: true },
    },
    {
        path: "/",
        redirect: "/dashboard",
    },
    {
        path: "/dashboard",
        name: "Dashboard",
        component: () => import("@/views/dashboard/Dashboard.vue"),
        meta: { title: "工作台", icon: "pi pi-th-large", order: 1 },
    },
    {
        path: "/projects",
        name: "Projects",
        component: () => import("@/views/projects/ProjectList.vue"),
        meta: { title: "项目信息", icon: "pi pi-folder-open", order: 2 },
    },
    {
        path: "/jobs",
        name: "Jobs",
        component: () => import("@/views/jobs/Jobs.vue"),
        meta: { title: "任务调度", icon: "pi pi-clock", order: 3 },
    },
    {
        path: "/sonar",
        name: "Sonar",
        component: () => import("@/views/sonar/Sonar.vue"),
        meta: { title: "代码扫描", icon: "pi pi-desktop", order: 4 },
    },
    {
        path: "/reports",
        name: "Reports",
        component: () => import("@/views/reports/Reports.vue"),
        meta: { title: "质量报表", icon: "pi pi-chart-bar", order: 5 },
    },
    {
        path: "/screen",
        name: "Screen",
        component: () => import("@/views/screen/Screen.vue"),
        meta: { title: "文档导入", icon: "pi pi-file-import", order: 6 },
    },
    {
        // 兜底:必须放在最后。此前未匹配的路径会渲染出「有侧栏、无内容」的空白壳。
        path: "/:pathMatch(.*)*",
        name: "NotFound",
        component: () => import("@/views/NotFound.vue"),
        meta: { title: "页面不存在", hidden: true },
    },
];

const base = import.meta.env.BASE_URL;

const router = createRouter({
    history: createWebHistory(base),
    routes,
});

router.beforeEach(async (to) => {
    if (to.path === "/login") return true;

    const token = localStorage.getItem("token");
    if (!token) return "/login";

    const authStore = useAuthStore();

    // 已校验过就直接放行。
    // 此前每次导航都调一次 /auth/me,切页时白白多一次网络往返,观感变慢。
    // 本地 JWT 过期由 authStore.ensureFreshToken()(每次请求前)负责,
    // 服务端拒绝但本地未过期的情况由 api 的 401 拦截器兜底跳登录 —— 两条路径缺一不可,
    // 否则会出现「登录态假象 + 全接口 401 + 无任何反馈」。
    if (authStore.user) return true;

    try {
        authStore.user = await authApi.getCurrentUser();
        return true;
    } catch {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        return "/login";
    }
});

export default router;
