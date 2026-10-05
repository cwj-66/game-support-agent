import { useEffect, useState } from 'react'
import { Button, Input, Spin } from 'antd'
import { API_BASE } from './config'

export default function AccessGate({ children }) {
  const [allowed, setAllowed] = useState(false)
  const [checking, setChecking] = useState(true)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    let portalManaged = false
    fetch(`${API_BASE}/access/status`, { credentials: 'same-origin', cache: 'no-store' })
      .then((r) => { if (!r.ok) throw new Error(); return r.json() })
      .then((data) => {
        portalManaged = data.portal_managed
        if (!cancelled && portalManaged && !data.authenticated) window.location.replace('/login')
        if (!cancelled) setAllowed(data.authenticated)
      })
      .catch(() => { if (!cancelled) setError('暂时无法连接演示，请稍后刷新。') })
      .finally(() => { if (!cancelled) setChecking(false) })
    const expired = () => {
      if (portalManaged) { window.location.replace('/login'); return }
      setAllowed(false); setError('访问已过期，请重新输入密码。')
    }
    window.addEventListener('demo-access-expired', expired)
    return () => { cancelled = true; window.removeEventListener('demo-access-expired', expired) }
  }, [])
  const login = async (event) => {
    event.preventDefault()
    if (busy || !password.trim()) return
    setBusy(true); setError('')
    try {
      const response = await fetch(`${API_BASE}/access/session`, {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: password.trim() }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '验证失败，请重试。')
      setPassword(''); setAllowed(true)
    } catch (e) { setError(e.message || '连接失败，请稍后重试。') }
    finally { setBusy(false) }
  }
  if (checking) return <div className="access-screen"><Spin tip="正在连接演示" /></div>
  if (allowed) return children
  return <main className="access-screen"><form className="access-card" onSubmit={login}>
    <div className="panel-eyebrow">PORTFOLIO / 作品集</div>
    <h1>欢迎查看我的作品集</h1>
    <p>请输入项目作者简历中手机号的后四位。</p>
    <Input.OTP length={4} type="text" size="large" aria-label="四位演示访问密码" value={password}
      onChange={setPassword} />
    {error && <p className="access-error" role="alert">{error}</p>}
    <Button type="primary" htmlType="submit" block loading={busy}>进入演示</Button>
    <small>验证后可浏览作品，并进入项目体验。</small>
  </form></main>
}
