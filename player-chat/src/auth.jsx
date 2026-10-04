import { demoFetch } from './access'
import { createContext, useCallback, useContext, useMemo, useState, useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { API_BASE } from './config'
import {
  clearSession,
  getStoredPlayer,
  getStoredToken,
  saveSession,
} from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [player, setPlayer] = useState(() =>
    getStoredToken() ? getStoredPlayer() : null,
  )

  useEffect(() => {
    let cancelled = false
    if (!getStoredToken()) return undefined
    demoFetch(`${API_BASE}/demo/players`).then((r) => r.ok ? r.json() : null).then((players) => {
      if (cancelled || !players) return
      const stored = getStoredPlayer()
      const fresh = players.find((p) => p.uid === stored?.uid)
      if (fresh) { saveSession(getStoredToken(), fresh); setPlayer(fresh) }
      else { clearSession(); setPlayer(null) }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const login = useCallback((token, profile) => {
    saveSession(token, profile)
    setPlayer(profile)
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setPlayer(null)
  }, [])

  const value = useMemo(
    () => ({ player, login, logout }),
    [player, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}

export function RequireAuth({ children }) {
  const { player } = useAuth()
  const location = useLocation()
  if (!player) {
    return (
      <Navigate
        to="/accounts"
        replace
        state={{ from: location, needAccount: true }}
      />
    )
  }
  return children
}
