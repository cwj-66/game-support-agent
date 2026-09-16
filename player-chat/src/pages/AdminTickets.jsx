import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Tag,
  Select,
  Input,
  Drawer,
  Descriptions,
  Spin,
  Empty,
  message,
  Typography,
  Button,
} from 'antd'
import { API_BASE } from '../config'
import { AUTH_HEADERS } from '../adminAuth'
import {
  STATUS_OPTIONS,
  STATUS_MAP,
  PRIORITY_MAP,
  CATEGORY_MAP,
  formatTime,
} from '../ticketMeta'
import './AdminPage.css'

function AdminTickets() {
  const navigate = useNavigate()
  const [tickets, setTickets] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [uidFilter, setUidFilter] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [currentTicket, setCurrentTicket] = useState(null)

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/ticket/stats`, { headers: AUTH_HEADERS })
      if (res.ok) setStats(await res.json())
    } catch {
      // 列表失败时再提示
    }
  }, [])

  const fetchTickets = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (statusFilter) params.set('status', statusFilter)
      if (uidFilter.trim()) params.set('player_uid', uidFilter.trim())

      const res = await fetch(`${API_BASE}/ticket/admin/list?${params}`, {
        headers: AUTH_HEADERS,
      })
      if (!res.ok) {
        message.error('获取工单列表失败')
        return
      }
      const data = await res.json()
      setTickets(data.tickets || [])
      setTotal(data.total || 0)
    } catch {
      message.error('网络异常，请检查后端是否启动')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter, uidFilter])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  useEffect(() => {
    fetchTickets()
  }, [fetchTickets])

  const openDetail = async (ticketId) => {
    setDrawerOpen(true)
    setDetailLoading(true)
    setCurrentTicket(null)
    try {
      const res = await fetch(`${API_BASE}/ticket/admin/${ticketId}`, {
        headers: AUTH_HEADERS,
      })
      if (!res.ok) {
        message.error('获取工单详情失败')
        setDrawerOpen(false)
        return
      }
      setCurrentTicket(await res.json())
    } catch {
      message.error('网络异常')
      setDrawerOpen(false)
    } finally {
      setDetailLoading(false)
    }
  }

  const columns = [
    {
      title: '工单号',
      dataIndex: 'ticket_id',
      key: 'ticket_id',
      width: 160,
      ellipsis: true,
    },
    {
      title: '玩家 UID',
      dataIndex: 'player_uid',
      key: 'player_uid',
      width: 100,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status) => {
        const info = STATUS_MAP[status] || { text: status, color: 'default' }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 90,
      render: (priority) => {
        const info = PRIORITY_MAP[priority] || { text: priority, color: 'default' }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (val) => formatTime(val),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Typography.Link onClick={() => openDetail(record.ticket_id)}>
          详情
        </Typography.Link>
      ),
    },
  ]

  return (
    <>
      <header className="admin-topbar">
        <h1>工单</h1>
        <div className="admin-topbar-actions">
          <span className="admin-topbar-meta">数据来自 MySQL support_tickets</span>
          <Button size="small" onClick={() => navigate('/')}>
            退出
          </Button>
        </div>
      </header>

      <div className="admin-content">
        <div className="stats-row stats-row-5">
          <div className="stat-card">
            <div className="stat-icon pending">📋</div>
            <div className="stat-info">
              <div className="stat-value">{stats?.total ?? '—'}</div>
              <div className="stat-label">全部</div>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon waiting">⏳</div>
            <div className="stat-info">
              <div className="stat-value">{stats?.pending ?? '—'}</div>
              <div className="stat-label">待处理</div>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon waiting">🔄</div>
            <div className="stat-info">
              <div className="stat-value">{stats?.processing ?? '—'}</div>
              <div className="stat-label">处理中</div>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon pending">✅</div>
            <div className="stat-info">
              <div className="stat-value">{stats?.resolved ?? '—'}</div>
              <div className="stat-label">已解决</div>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon risk">⚠️</div>
            <div className="stat-info">
              <div className="stat-value">{stats?.escalated ?? '—'}</div>
              <div className="stat-label">已升级</div>
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-card-header">
            <h3>全部工单</h3>
            <div className="admin-ticket-filters">
              <Input.Search
                allowClear
                placeholder="玩家 UID"
                style={{ width: 160 }}
                onSearch={(val) => {
                  setUidFilter(val)
                  setPage(1)
                }}
              />
              <Select
                value={statusFilter}
                options={STATUS_OPTIONS}
                style={{ width: 130 }}
                onChange={(val) => {
                  setStatusFilter(val)
                  setPage(1)
                }}
              />
            </div>
          </div>
          <Spin spinning={loading}>
            {tickets.length === 0 && !loading ? (
              <Empty description="数据库中暂无工单" />
            ) : (
              <Table
                rowKey="ticket_id"
                columns={columns}
                dataSource={tickets}
                pagination={{
                  current: page,
                  pageSize,
                  total,
                  showSizeChanger: true,
                  showTotal: (t) => `共 ${t} 条`,
                  onChange: (p, ps) => {
                    setPage(p)
                    setPageSize(ps)
                  },
                }}
              />
            )}
          </Spin>
        </div>
      </div>

      <Drawer
        title={currentTicket ? `工单 ${currentTicket.ticket_id}` : '工单详情'}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setCurrentTicket(null)
        }}
        width={520}
        destroyOnHidden
      >
        <Spin spinning={detailLoading}>
          {currentTicket && (
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="玩家 UID">
                {currentTicket.player_uid}
              </Descriptions.Item>
              <Descriptions.Item label="标题">{currentTicket.title}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_MAP[currentTicket.status]?.color || 'default'}>
                  {STATUS_MAP[currentTicket.status]?.text || currentTicket.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="优先级">
                <Tag color={PRIORITY_MAP[currentTicket.priority]?.color || 'default'}>
                  {PRIORITY_MAP[currentTicket.priority]?.text || currentTicket.priority}
                </Tag>
              </Descriptions.Item>
              {currentTicket.category && (
                <Descriptions.Item label="分类">
                  {CATEGORY_MAP[currentTicket.category] || currentTicket.category}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="问题描述">
                <div className="ticket-desc">{currentTicket.description}</div>
              </Descriptions.Item>
              {currentTicket.agent_reply && (
                <Descriptions.Item label="客服回复">
                  <div className="ticket-reply">{currentTicket.agent_reply}</div>
                </Descriptions.Item>
              )}
              {currentTicket.interrupt_reason && (
                <Descriptions.Item label="转人工原因">
                  {currentTicket.interrupt_reason}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="人工处理">
                {currentTicket.human_reviewed ? '是' : '否'}
              </Descriptions.Item>
              {currentTicket.reviewer_id && (
                <Descriptions.Item label="处理人">
                  {currentTicket.reviewer_id}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="创建时间">
                {formatTime(currentTicket.created_at)}
              </Descriptions.Item>
              {currentTicket.resolved_at && (
                <Descriptions.Item label="解决时间">
                  {formatTime(currentTicket.resolved_at)}
                </Descriptions.Item>
              )}
            </Descriptions>
          )}
        </Spin>
      </Drawer>
    </>
  )
}

export default AdminTickets
