import axios from 'axios'
import type { AxiosInstance, AxiosError, AxiosRequestConfig } from 'axios'
import { notify } from '@/utils/appToast'
import { useAuthStore } from '@/stores/auth'

const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.BASE_URL + 'api',
  timeout: 30000,
})

// 请求拦截器：添加 JWT Token,并在发送前检查 token 是否已过期
api.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      // ensureFreshToken 内部会在过期时调用 logout() 并跳转登录
      authStore.ensureFreshToken()
      // 重新读取,logout 后 token 已被清空
      const token = authStore.token || localStorage.getItem('token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 防重入:并发请求同时返回 401 时只登出一次,避免重复 router.push
let redirectingToLogin = false

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError<{ detail?: string }>) => {
    if (error.response?.status === 401) {
      // 401 不弹提示(对用户没有意义),但若当前持有 token,说明登录态已失效 ——
      // 必须真正清掉并跳登录。
      //
      // 此前这里只静默 reject,把跳转完全推给路由守卫;而路由守卫现已支持
      // 「已校验过则短路」,若继续只 reject,服务端 token 失效(本地 JWT 尚未过期)时
      // 会卡在「看似已登录 + 所有接口 401 + 无任何反馈」的死局。
      //
      // 不持有 token 的 401 来自登录接口本身(账号密码错误),交由调用方提示,这里不处理。
      if (localStorage.getItem("token") && !redirectingToLogin) {
        redirectingToLogin = true;
        // logout() 内部保证「先跳转、后清状态」的顺序
        useAuthStore()
          .logout()
          .finally(() => {
            redirectingToLogin = false;
          });
      }
      return Promise.reject(error);
    }
    const message = error.response?.data?.detail || error.message || '请求失败'
    notify('error', message)
    return Promise.reject(error)
  }
)

/**
 * 泛型请求方法。
 * 响应拦截器已将 response 剥壳(return response.data),故这里直接返回 Promise<T>,
 * 消除了 `as unknown as Promise<T>` 双重断言,给调用方精确的业务类型。
 */
async function request<T>(config: AxiosRequestConfig): Promise<T> {
  return api.request(config) as Promise<T>
}

function get<T>(url: string, params?: object, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ url, method: 'get', params, ...config })
}

function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ url, method: 'post', data, ...config })
}

function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ url, method: 'put', data, ...config })
}

function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ url, method: 'delete', ...config })
}

export { api, get, post, put, del }
export default api
