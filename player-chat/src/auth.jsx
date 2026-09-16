import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
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
