import { demoFetch } from './access'
import { API_BASE } from './config'

const TOKEN_KEY = 'gsa_player_token'
const PLAYER_KEY = 'gsa_player_profile'

export function getStoredToken() {
  return sessionStorage.getItem(TOKEN_KEY) || ''
}

export function getStoredPlayer() {
  try {
    const raw = sessionStorage.getItem(PLAYER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveSession(token, player) {
  sessionStorage.setItem(TOKEN_KEY, token)
  sessionStorage.setItem(PLAYER_KEY, JSON.stringify(player))
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(PLAYER_KEY)
}

export function authHeaders() {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function newRequestId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/** 读取后端错误：优先使用服务端面向玩家的 message，附带错误码与 Retry-After 秒数 */
export async function readError(res, fallback) {
  let body = {}
  try { body = await res.json() } catch { /* 非 JSON 响应使用兜底文案 */ }
  const retryAfter = Number(res.headers.get('Retry-After')) || null
  const detail = typeof body.detail === 'string' ? body.detail : ''
  return { code: body.error_code || '', message: body.message || detail || fallback, retryAfter, status: res.status }
}

export async function apiFetch(path, options = {}) {
  const { headers, ...rest } = options
  return demoFetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      ...authHeaders(),
      ...headers,
    },
  })
}
