import { post, get } from './index'

export interface LoginRequest {
  username: string
  password: string
}

export interface UserInfo {
  id: number
  username: string
  created_at?: string
  updated_at?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export const authApi = {
  login(data: LoginRequest): Promise<LoginResponse> {
    return post<LoginResponse>('/auth/login', data)
  },

  getCurrentUser(): Promise<UserInfo> {
    return get<UserInfo>('/auth/me')
  },
}