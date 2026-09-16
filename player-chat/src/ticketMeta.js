export const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
]

export const STATUS_MAP = {
  pending: { text: '待处理', color: 'gold' },
  processing: { text: '处理中', color: 'blue' },
  resolved: { text: '已解决', color: 'green' },
  escalated: { text: '已升级', color: 'red' },
}

export const PRIORITY_MAP = {
  P0: { text: 'P0 紧急', color: 'red' },
  P1: { text: 'P1 高', color: 'orange' },
  P2: { text: 'P2 普通', color: 'default' },
}

export const CATEGORY_MAP = {
  gameplay: '玩法咨询',
  account: '账号问题',
  account_ban: '封禁申诉',
  payment: '充值支付',
  bug: 'Bug 反馈',
  complaint: '投诉建议',
  other: '其他',
}

export function formatTime(isoStr) {
  if (!isoStr) return '—'
  try {
    return new Date(isoStr).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return isoStr
  }
}
