import { defineStore } from "pinia";
import { ref } from "vue";
import { authApi, type UserInfo } from "@/api/auth";
import router from "@/router";

/**
 * 解码 JWT payload(不验签,仅用于查看 exp 字段判断是否过期)。
 * 真正的验证由后端在每次受保护接口调用时完成。
 */
function decodeJwtExp(token: string): number | null {
    try {
        const parts = token.split(".");
        if (parts.length !== 3) return null;
        const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const decoded = JSON.parse(atob(payload));
        return typeof decoded.exp === "number" ? decoded.exp : null;
    } catch {
        return null;
    }
}

function isTokenExpired(token: string): boolean {
    const exp = decodeJwtExp(token);
    if (exp === null) return true;
    // 提前 60 秒判过期,避免请求临界点
    return Date.now() >= (exp - 60) * 1000;
}

export const useAuthStore = defineStore("auth", () => {
    const user = ref<UserInfo | null>(null);
    const token = ref<string>("");

    async function login(username: string, password: string) {
        const response = await authApi.login({ username, password });
        token.value = response.access_token;
        user.value = response.user;
        localStorage.setItem("token", response.access_token);
        localStorage.setItem("user", JSON.stringify(response.user));
        return response;
    }

    async function fetchCurrentUser() {
        try {
            const response = await authApi.getCurrentUser();
            user.value = response;
            return response;
        } catch {
            logout();
            throw new Error("Token已过期");
        }
    }

    async function logout() {
        // 先跳转再清状态:若先清 token,App.vue 的 v-if 会立刻卸载 MainLayout,
        // 导致当前受保护页面被 router-view 重新挂载并触发未认证的请求(如 GET /api/projects)
        await router.push("/login");
        user.value = null;
        token.value = "";
        localStorage.removeItem("token");
        localStorage.removeItem("user");
    }

    function initFromStorage() {
        const storedToken = localStorage.getItem("token");
        const storedUser = localStorage.getItem("user");
        if (storedToken && storedUser) {
            // 启动时检查 token 是否已过期,过期则直接清掉,避免首次请求就 401
            if (isTokenExpired(storedToken)) {
                localStorage.removeItem("token");
                localStorage.removeItem("user");
                return;
            }
            token.value = storedToken;
            user.value = JSON.parse(storedUser);
        }
    }

    /**
     * 在每次受保护请求前调用。若 token 在 5 分钟内即将过期,主动踢出登录,
     * 由用户重新登录 — 简化方案,不引入 refresh token(那需要后端同时改)。
     * 若想避免体验中断,后续可对接 /api/auth/refresh 接口。
     */
    function ensureFreshToken(): boolean {
        if (!token.value) return false;
        if (isTokenExpired(token.value)) {
            logout();
            return false;
        }
        return true;
    }

    return {
        user,
        token,
        login,
        logout,
        fetchCurrentUser,
        initFromStorage,
        ensureFreshToken,
    };
});
