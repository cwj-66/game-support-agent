import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button, Card, Empty, Segmented, Spin, message } from 'antd'
import { API_BASE } from '../config'
import { useAuth } from '../auth'
import {
  STATUS_FILTERS,
  formatLastLogin,
  scenarioOf,
  statusTag,
} from '../PlayerProfile'
import './AccountsPage.css'

function AccountsPage() {
  const { player: current, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [loggingUid, setLoggingUid] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  useEffect(() => {
    if (!location.state?.needAccount) return
    message.warning({
      content: '请先选择一个测试账号',
      key: 'need-account',
    })
    navigate('.', { replace: true, state: { from: location.state.from } })
  }, [location.state, navigate])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${API_BASE}/demo/players`)
        if (!res.ok) {
          message.error(
            res.status === 503
              ? '账号数据库不可用，请确认 MySQL 已启动'
              : '获取测试账号失败',
          )
          return
        }
        const data = await res.json()
        if (!cancelled) setPlayers(Array.isArray(data) ? data : [])
      } catch {
        message.error('网络异常，请检查后端是否启动')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const visible = useMemo(() => {
    if (statusFilter === 'all') return players
    return players.filter((p) => p.status === statusFilter)
  }, [players, statusFilter])

  const handleLogin = async (uid) => {
    setLoggingUid(uid)
    try {
      const res = await fetch(`${API_BASE}/demo/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid }),
      })
      if (!res.ok) {
        let detail = '登录失败，请稍后重试'
        try {
          const err = await res.json()
          detail = err.detail || detail
        } catch {
          if (res.status === 500) detail = '服务端未配置 GAME_JWT_SECRET'
        }
        message.error(detail)
        return
      }
      const data = await res.json()
      login(data.token, data.player)
      message.success(`已登录 ${data.player.nickname}（${data.player.uid}）`)
      const to = location.state?.from?.pathname || '/'
      navigate(to, { replace: true })
    } catch {
      message.error('网络异常，请检查后端是否启动')
    } finally {
      setLoggingUid('')
    }
  }

  return (
    <div className="accounts-page">
      <div className="accounts-hero">
        <h2>选择测试账号</h2>
        <p>
          点选下方账号即可进入玩家端。不同账号覆盖正常、封禁、充值异常等状态，方便验证客服流程。
        </p>
        <Segmented
          value={statusFilter}
          options={STATUS_FILTERS}
          onChange={setStatusFilter}
        />
      </div>

      <Spin spinning={loading}>
        {visible.length === 0 && !loading ? (
          <Empty description="暂无测试账号" />
        ) : (
          <div className="accounts-grid">
            {visible.map((p) => {
              const selected = current?.uid === p.uid
              return (
                <Card
                  key={p.uid}
                  className={`account-card${selected ? ' selected' : ''}`}
                  size="small"
                >
                  <div className="account-card-head">
                    <div>
                      <div className="account-nickname">{p.nickname}</div>
                      <div className="account-uid">UID {p.uid}</div>
                    </div>
                    {statusTag(p.status)}
                  </div>
                  <dl className="account-fields">
                    <div>
                      <dt>区服</dt>
                      <dd>{p.server_id || '—'}</dd>
                    </div>
                    <div>
                      <dt>等级</dt>
                      <dd>Lv.{p.level ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>VIP</dt>
                      <dd>VIP{p.vip_level ?? 0}</dd>
                    </div>
                    <div>
                      <dt>累计充值</dt>
                      <dd>¥{Number(p.recharge_total || 0).toFixed(0)}</dd>
                    </div>
                    <div className="span-2">
                      <dt>最后登录</dt>
                      <dd>{formatLastLogin(p.last_login)}</dd>
                    </div>
                  </dl>
                  {p.ban_reason && (
                    <div className="account-reason">
                      <span>封禁原因</span>
                      {p.ban_reason}
                    </div>
                  )}
                  {p.abnormal_detail && (
                    <div className="account-reason">
                      <span>充值异常</span>
                      {p.abnormal_detail}
                    </div>
                  )}
                  <div className="account-hint">{scenarioOf(p)}</div>
                  <Button
                    type={selected ? 'default' : 'primary'}
                    block
                    loading={loggingUid === p.uid}
                    disabled={Boolean(loggingUid) && loggingUid !== p.uid}
                    onClick={() => handleLogin(p.uid)}
                  >
                    {selected ? '当前账号，重新进入' : '选择并登录'}
                  </Button>
                </Card>
              )
            })}
          </div>
        )}
      </Spin>
    </div>
  )
}

export default AccountsPage
