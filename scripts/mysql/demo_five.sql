-- Update the five public demo profiles without deleting historical players/tickets.
USE game_support;
SET NAMES utf8mb4;
START TRANSACTION;
UPDATE game_players SET nickname='玩家1', status='normal', ban_reason=NULL, abnormal_detail=NULL WHERE uid='10001';
UPDATE game_players SET nickname='玩家2', status='banned', ban_reason='使用外挂程序，违反用户协议第3.2条', abnormal_detail=NULL WHERE uid='10002';
UPDATE game_players SET nickname='玩家3', status='recharge_abnormal', ban_reason=NULL, abnormal_detail='充值订单已支付但未到账，正在核实支付渠道记录' WHERE uid='10003';
UPDATE game_players SET nickname='玩家4', status='normal', ban_reason=NULL, abnormal_detail=NULL WHERE uid='10004';
UPDATE game_players SET nickname='玩家5', status='normal', level=8, vip_level=0, recharge_total=0, ban_reason=NULL, abnormal_detail=NULL WHERE uid='10005';
INSERT INTO support_tickets
    (ticket_id, player_uid, title, description, category, priority, status, agent_reply, session_id)
VALUES
    ('TK-DEMO-10004', '10004', '活动奖励未到账', '完成活动任务后未收到奖励，请核实发放记录。', 'bug', 'P2', 'processing', '客服已受理，正在核实活动完成和奖励发放记录。', '10004_demo_ticket')
ON DUPLICATE KEY UPDATE status='processing', resolved_at=NULL, agent_reply=VALUES(agent_reply);
-- Resolved history is separate from each player's current account status.
INSERT INTO support_tickets
    (ticket_id, player_uid, title, description, category, priority, status, agent_reply, session_id, created_at, resolved_at, human_reviewed, human_action, reviewer_id)
VALUES
    ('TK-DEMO-DONE-10001', '10001', '背包道具显示异常已修复', '更新后背包道具数量显示不正确。', 'bug', 'P2', 'resolved', '已修复背包显示缓存问题，道具实际数量未受影响，重新登录后显示正常。', '10001_demo_history', '2026-09-10 10:00:00', '2026-09-11 15:00:00', 1, 'resolve', 'admin_001'),
    ('TK-DEMO-DONE-10002', '10002', '历史活动奖励补发完成', '此前活动奖励领取成功但邮件未收到。', 'bug', 'P2', 'resolved', '已核实活动参与记录并补发奖励，玩家已确认收到；此历史工单不涉及当前外挂封禁。', '10002_demo_history', '2026-09-12 10:00:00', '2026-09-13 15:00:00', 1, 'resolve', 'admin_001'),
    ('TK-DEMO-DONE-10003', '10003', '历史充值订单补单完成', '此前一笔充值订单因渠道延迟未及时到账。', 'payment', 'P1', 'resolved', '已核实历史订单并完成补单，玩家已确认到账；当前的新充值异常仍在另一个工单中核实。', '10003_demo_history', '2026-09-14 10:00:00', '2026-09-15 15:00:00', 1, 'resolve', 'admin_001'),
    ('TK-DEMO-DONE-10004', '10004', '角色卡在场景中已修复', '角色卡在地图边缘无法移动。', 'bug', 'P2', 'resolved', '已将角色移动至安全位置，并修复该场景碰撞问题；当前活动奖励工单继续处理中。', '10004_demo_history', '2026-09-16 10:00:00', '2026-09-17 15:00:00', 1, 'resolve', 'admin_001'),
    ('TK-DEMO-DONE-10005', '10005', '新手任务进度异常已修复', '完成新手任务后任务进度没有更新。', 'bug', 'P2', 'resolved', '已同步新手任务进度并补发任务奖励，玩家已确认可继续任务。', '10005_demo_history', '2026-09-18 10:00:00', '2026-09-19 15:00:00', 1, 'resolve', 'admin_001')
ON DUPLICATE KEY UPDATE
    title=VALUES(title), description=VALUES(description), agent_reply=VALUES(agent_reply);
COMMIT;
