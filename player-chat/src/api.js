import { API_BASE } from './config'

const TOKEN_KEY = 'gsa_player_token'
const PLAYER_KEY = 'gsa_player_profile'

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getStoredPlayer() {
  try {
    const raw = localStorage.getItem(PLAYER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveSession(token, player) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(PLAYER_KEY, JSON.stringify(player))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(PLAYER_KEY)
}

export function authHeaders() {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function apiFetch(path, options = {}) {
  const { headers, ...rest } = options
  return fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      ...authHeaders(),
      ...headers,
    },
  })
}
