import { Descriptions, Tag } from 'antd'
import { DEMO_SCENARIOS } from './demoScenarios'

export const STATUS_META = {
  normal: { text: '正常', color: 'success' },
  banned: { text: '已封禁', color: 'error' },
  recharge_abnormal: { text: '充值异常', color: 'warning' },
}

export const STATUS_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'normal', label: '正常' },
  { value: 'banned', label: '已封禁' },
  { value: 'recharge_abnormal', label: '充值异常' },
]

export function scenarioOf(player) {
  if (DEMO_SCENARIOS[player.uid]) return DEMO_SCENARIOS[player.uid].description
  if (player.status === 'banned') return '可测：解封申诉、账号状态查询'
  if (player.status === 'recharge_abnormal') return '可测：充值未到账、风控核实'
  return '可测：攻略咨询、账号查询、工单'
}

export function formatLastLogin(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16)
}

export function statusTag(status) {
  const meta = STATUS_META[status] || { text: status || '未知', color: 'default' }
  return <Tag color={meta.color}>{meta.text}</Tag>
}

/** 玩家档案字段列表，供账号卡片和聊天页抽屉共用 */
export function PlayerProfileDesc({ player, compact = false }) {
  if (!player) return null
  return (
    <Descriptions
      column={1}
      size="small"
      className={compact ? 'player-profile-desc compact' : 'player-profile-desc'}
    >
      <Descriptions.Item label="UID">{player.uid}</Descriptions.Item>
      <Descriptions.Item label="昵称">{player.nickname || '—'}</Descriptions.Item>
      <Descriptions.Item label="状态">{statusTag(player.status)}</Descriptions.Item>
      <Descriptions.Item label="区服">{player.server_id || '—'}</Descriptions.Item>
      <Descriptions.Item label="等级">Lv.{player.level ?? '—'}</Descriptions.Item>
      <Descriptions.Item label="VIP">VIP{player.vip_level ?? 0}</Descriptions.Item>
      <Descriptions.Item label="累计充值">
        ¥{Number(player.recharge_total || 0).toFixed(0)}
      </Descriptions.Item>
      <Descriptions.Item label="最后登录">
        {formatLastLogin(player.last_login)}
      </Descriptions.Item>
      {player.ban_reason ? (
        <Descriptions.Item label="封禁原因">{player.ban_reason}</Descriptions.Item>
      ) : null}
      {player.abnormal_detail ? (
        <Descriptions.Item label="充值异常">{player.abnormal_detail}</Descriptions.Item>
      ) : null}
    </Descriptions>
  )
}
