import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Tag,
  Select,
  Drawer,
  Descriptions,
  Spin,
  Empty,
  message,
  Typography,
} from 'antd'
import { API_BASE } from '../config'
import './TicketsPage.css'

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
]

const STATUS_MAP = {
  pending: { text: '待处理', color: 'gold' },
  processing: { text: '处理中', color: 'blue' },
  resolved: { text: '已解决', color: 'green' },
  escalated: { text: '已升级', color: 'red' },
}

const PRIORITY_MAP = {
  P0: { text: 'P0 紧急', color: 'red' },
  P1: { text: 'P1 高', color: 'orange' },
  P2: { text: 'P2 普通', color: 'default' },
}

const CATEGORY_MAP = {
  gameplay: '玩法咨询',
  account: '账号问题',
  payment: '充值支付',
  bug: 'Bug 反馈',
  complaint: '投诉建议',
  other: '其他',
}

/** 格式化 ISO 时间为本地可读字符串 */
const formatTime = (isoStr) => {
  if (!isoStr) return '—'
  try {
    return new Date(isoStr).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return isoStr
  }
}

function TicketsPage() {
  const [tickets, setTickets] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [currentTicket, setCurrentTicket] = useState(null)

  const fetchTickets = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (statusFilter) params.set('status', statusFilter)

      const res = await fetch(`${API_BASE}/ticket/list?${params}`)
      if (!res.ok) {
        message.error(res.status === 401 ? '请先登录' : '获取工单列表失败')
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
  }, [page, pageSize, statusFilter])

  useEffect(() => {
    fetchTickets()
  }, [fetchTickets])

  const openDetail = async (ticketId) => {
    setDrawerOpen(true)
    setDetailLoading(true)
    setCurrentTicket(null)
    try {
      const res = await fetch(`${API_BASE}/ticket/${ticketId}`)
      if (!res.ok) {
        message.error('获取工单详情失败')
        setDrawerOpen(false)
        return
      }
      const data = await res.json()
      setCurrentTicket(data)
    } catch {
      message.error('网络异常')
      setDrawerOpen(false)
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDrawer = () => {
    setDrawerOpen(false)
    setCurrentTicket(null)
  }

  const columns = [
    {
      title: '工单号',
      dataIndex: 'ticket_id',
      key: 'ticket_id',
      width: 140,
      ellipsis: true,
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
      width: 100,
      render: (status) => {
        const info = STATUS_MAP[status] || { text: status, color: 'default' }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 100,
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
    <div className="tickets-page">
      <div className="tickets-toolbar">
        <Typography.Title level={4} style={{ margin: 0 }}>
          历史工单
        </Typography.Title>
        <Select
          value={statusFilter}
          options={STATUS_OPTIONS}
          style={{ width: 140 }}
          onChange={(val) => {
            setStatusFilter(val)
            setPage(1)
          }}
        />
      </div>

      <Spin spinning={loading}>
        {tickets.length === 0 && !loading ? (
          <Empty description="暂无工单记录" className="tickets-empty" />
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

      <Drawer
        title={currentTicket ? `工单 ${currentTicket.ticket_id}` : '工单详情'}
        open={drawerOpen}
        onClose={closeDrawer}
        width={520}
        destroyOnHidden
      >
        <Spin spinning={detailLoading}>
          {currentTicket && (
            <Descriptions column={1} bordered size="small">
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
    </div>
  )
}

export default TicketsPage
