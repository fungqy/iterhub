<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import Menu from 'primevue/menu'
import Avatar from 'primevue/avatar'
import Button from 'primevue/button'

const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggleTheme } = useTheme()

const isCollapse = ref(false)

// 品牌标记与 favicon 同源(单一事实来源,不另存副本)。
// 必须用 import.meta.env.BASE_URL 而非硬编码 "/favicon.svg" —— 生产部署在子路径
// (/iterhub/) 下,硬编码会 404。
const brandMark = `${import.meta.env.BASE_URL}favicon.svg`

// 用户菜单按钮的可读名(已取消角色标签,只保留用户名)。
const userLabel = computed(() => `用户菜单:${authStore.user?.username ?? ''}`)

// 顶栏整条已移除(用户要求)。原顶栏承载的「页面标题」改由各页 .ds-page-head 的 h1
// 自述 —— 实际业务页本来就有 h1,顶栏那份标题是重复信息。
// 主题切换按钮随之迁入侧边栏底部,与用户区并列,不因删顶栏而丢失功能。

// 导航项从路由派生 —— router/index.ts 是唯一源。
// 此前本组件硬编码了一份菜单,而路由 meta 里另有一份(且是 Element Plus 图标名),
// 两份不一致且加页面要改两处。现在只需在路由里改。
const menuItems = computed(() =>
  router
    .getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden)
    .sort((a, b) => Number(a.meta.order ?? 0) - Number(b.meta.order ?? 0))
    .map((r) => ({
      path: r.path,
      label: r.meta.title as string,
      icon: (r.meta.icon as string) || 'pi pi-circle',
    })),
)

const userMenu = ref()
// 供 aria-expanded 使用,必须与实际弹层显隐同步,不能是死值
const menuOpen = ref(false)
const userMenuItems = ref([
  {
    label: '退出登录',
    icon: 'pi pi-sign-out',
    command: () => handleLogout(),
  },
])

function toggleUserMenu(event: Event) {
  userMenu.value.toggle(event)
}

function handleLogout() {
  // logout() 内部已负责跳转 /login(先跳转后清状态),此处不要再 push 一次
  authStore.logout()
}

function toggleCollapse() {
  isCollapse.value = !isCollapse.value
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ collapsed: isCollapse }">
      <div class="app-brand">
        <!-- 品牌标记直接复用 public/favicon.svg —— 它就是产品标记本身。
             不另存一份 src/assets 副本,避免同一标记两处漂移(改 favicon 忘改侧栏)。
             展开态:标记纯粹装饰,可读名由右侧文字提供 → alt="";
             折叠态:文字被 v-if 移除,标记成为唯一内容 → 此时 alt 提供可读名,
             保证两种状态下该链接区域的名称都是「Sprint Better」。 -->
        <img
          class="app-brand-mark"
          :src="brandMark"
          :alt="isCollapse ? 'Sprint Better' : ''"
        />
        <span v-if="!isCollapse" class="app-brand-name">Sprint Better</span>
      </div>
      <nav class="app-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          :title="item.label"
        >
          <!-- 装饰性图标:对读屏隐藏,可读名由相邻的文本提供 -->
          <i :class="item.icon" aria-hidden="true"></i>
          <span v-if="!isCollapse">{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="app-sidebar-foot">
        <!-- 底部两件套:用户区(头像 + 名称)与主题切换。
             原先散落在顶栏右侧,顶栏已删,故归入侧边栏底部。
             折叠态下用户名隐藏,只留头像,由 title/aria-label 兜底。 -->
        <div class="app-user" :class="{ compact: isCollapse }">
          <button
            type="button"
            class="app-user-trigger"
            :title="authStore.user?.username ?? ''"
            :aria-label="userLabel"
            aria-haspopup="menu"
            :aria-expanded="menuOpen"
            @click="toggleUserMenu"
          >
            <Avatar
              :label="authStore.user?.username?.charAt(0)?.toUpperCase()"
              shape="circle"
              size="normal"
            />
            <!-- 用户名块:已取消角色标签,只留用户名。
                 折叠态整块不渲染(只留头像)。 -->
            <span v-if="!isCollapse" class="app-user-identity">
              <span class="app-user-name">{{ authStore.user?.username }}</span>
            </span>
          </button>
        </div>

        <div class="app-sidebar-actions" :class="{ compact: isCollapse }">
          <Button
            :icon="isDark ? 'pi pi-sun' : 'pi pi-moon'"
            text
            rounded
            :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            @click="toggleTheme"
          />
          <Button
            :icon="isCollapse ? 'pi pi-arrow-right' : 'pi pi-arrow-left'"
            text
            rounded
            :aria-label="isCollapse ? '展开侧边栏' : '收起侧边栏'"
            :title="isCollapse ? '展开侧边栏' : '收起侧边栏'"
            @click="toggleCollapse"
          />
        </div>
      </div>
    </aside>

    <div class="app-main">
      <main class="app-content">
        <router-view />
      </main>
    </div>

    <!-- 用户下拉菜单:popup 层挂到壳外(appendTo body),不属于侧边栏 DOM 流 -->
    <Menu
      ref="userMenu"
      :model="userMenuItems"
      :popup="true"
      append-to="body"
      @show="menuOpen = true"
      @hide="menuOpen = false"
    />
  </div>
</template>
