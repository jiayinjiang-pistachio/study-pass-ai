import { request } from './request'

export interface AuthCredentials {
  username: string
  password: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface AuthUser {
  id: number
  username: string
  create_time: string
}

export function login(payload: AuthCredentials): Promise<TokenPair> {
  return request<TokenPair>('/auth/login', { method: 'POST', body: payload })
}

export function register(payload: AuthCredentials): Promise<AuthUser> {
  return request<AuthUser>('/auth/register', { method: 'POST', body: payload })
}

export function fetchCurrentUser(silent = false): Promise<AuthUser> {
  return request<AuthUser>('/auth/me', { silent })
}
