-- ============================================================
-- Game Support Agent — MySQL Mock 数据
-- ============================================================
-- 参考：
--   - OpenTibia ForgottenServer: accounts + players 分表
--     https://github.com/otland/forgottenserver/blob/master/schema.sql
--   - MySQL-RPG-Schema: user 与 character 分离
--     https://github.com/jgoodman/MySQL-RPG-Schema
--
-- 说明：
--   - game_players：模拟游戏服玩家档案（原 accounts.json 迁入 MySQL）
--   - support_tickets：客服工单（与 SQLite tickets 结构对齐，供 MySQL 版使用）
--   - token 不存表：由游戏服用 GAME_JWT_SECRET 签发 JWT，客服 API 只验签名
-- ============================================================

CREATE DATABASE IF NOT EXISTS game_support
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE game_support;

SET NAMES utf8mb4;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;

-- ------------------------------------------------------------
-- 玩家表（对应游戏服 player / character）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_players (
    uid              VARCHAR(32)  NOT NULL COMMENT '玩家 UID，对外唯一标识',
    nickname         VARCHAR(64)  NOT NULL COMMENT '昵称',
    server_id        VARCHAR(16)  NOT NULL DEFAULT 's1' COMMENT '区服',
    level            INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '等级',
    vip_level        TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'VIP 等级',
    status           ENUM('normal', 'banned', 'recharge_abnormal') NOT NULL DEFAULT 'normal',
    ban_reason       TEXT         NULL COMMENT '封禁原因',
    recharge_total   DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT '累计充值（元）',
    abnormal_detail  TEXT         NULL COMMENT '充值异常说明',
    last_login       DATETIME     NULL COMMENT '最后登录时间',
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (uid),
    KEY idx_players_status (status),
    KEY idx_players_server (server_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='游戏玩家档案（Mock）';

-- ------------------------------------------------------------
-- 工单表（客服域，player_uid 外键关联 game_players）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id        VARCHAR(32)  NOT NULL COMMENT '工单号 TK-YYYYMMDD-xxxx',
    player_uid       VARCHAR(32)  NOT NULL COMMENT '所属玩家 UID',
    title            VARCHAR(255) NOT NULL,
    description      TEXT         NOT NULL,
    category         VARCHAR(64)  NULL COMMENT 'account_ban/payment/bug/other',
    priority         ENUM('P0', 'P1', 'P2') NOT NULL DEFAULT 'P2',
    status           ENUM('pending', 'processing', 'resolved', 'escalated') NOT NULL DEFAULT 'pending',
    agent_reply      TEXT         NULL,
    human_reviewed   TINYINT(1)   NOT NULL DEFAULT 0,
    human_action     VARCHAR(64)  NULL,
    reviewer_id      VARCHAR(64)  NULL,
    interrupt_reason TEXT         NULL,
    session_id       VARCHAR(128) NULL COMMENT '关联 Agent 会话',
    tool_context     JSON         NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at      DATETIME     NULL,
    PRIMARY KEY (ticket_id),
    KEY idx_tickets_player (player_uid),
    KEY idx_tickets_status (status),
    KEY idx_tickets_created (created_at),
    CONSTRAINT fk_tickets_player
        FOREIGN KEY (player_uid) REFERENCES game_players (uid)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客服工单（Mock）';

-- ------------------------------------------------------------
-- Mock 玩家数据（来自 data/accounts.json，补充 nickname/level/vip）
-- ------------------------------------------------------------
INSERT INTO game_players
    (uid, nickname, server_id, level, vip_level, status, ban_reason, recharge_total, abnormal_detail, last_login)
VALUES
    ('10001', '风行者',   's1', 45, 2, 'normal',            NULL, 1280.00,  NULL, '2026-05-08 20:15:00'),
    ('10002', '暗夜猎手', 's1', 38, 0, 'banned',            '使用外挂程序，违反用户协议第3.2条', 328.00, NULL, '2026-04-10 18:23:00'),
    ('10003', '星辰法师', 's2', 52, 3, 'recharge_abnormal', NULL, 5000.00, '近期充值出现异常，充值未到账', '2026-05-20 14:30:00'),
    ('10004', '铁壁骑士', 's1', 29, 1, 'normal',            NULL, 648.00,  NULL, '2026-05-25 10:00:00'),
    ('10005', '流浪剑客', 's3', 15, 0, 'banned',            '恶意退款，违反用户协议第5.1条', 0.00, NULL, '2026-03-15 09:00:00'),
    ('10006', '圣光牧师', 's1', 60, 4, 'normal',            NULL, 2560.00, NULL, '2026-05-28 22:10:00'),
    ('10007', '新手小白', 's2', 8,  0, 'normal',            NULL, 30.00,   NULL, '2026-05-01 12:30:00'),
    ('10008', '烈焰战士', 's1', 33, 0, 'banned',            '发布违规言论，违反用户协议第7.5条', 128.00, NULL, '2026-02-20 16:45:00'),
    ('10009', '土豪玩家', 's1', 55, 5, 'recharge_abnormal', NULL, 9999.00, '单笔充值金额超过上限，触发风控', '2026-05-29 08:00:00'),
    ('10010', '休闲达人', 's2', 22, 0, 'normal',            NULL, 0.00,    NULL, '2026-05-28 19:00:00'),
    ('10011', '弓箭手',   's1', 41, 1, 'normal',            NULL, 198.00,  NULL, '2026-05-27 15:20:00'),
    ('10012', '迷途者',   's3', 36, 2, 'banned',            '账号被盗后用于发布广告，临时封禁', 648.00, NULL, '2026-04-01 11:00:00'),
    ('10013', '龙吟',     's1', 58, 4, 'normal',            NULL, 5200.00, NULL, '2026-05-29 07:30:00'),
    ('10014', '充值困惑', 's2', 27, 1, 'recharge_abnormal', NULL, 300.00,  '支付渠道返回异常，订单待核实', '2026-05-22 18:00:00'),
    ('10015', '老玩家',   's1', 48, 2, 'normal',            NULL, 128.00,  NULL, '2026-05-15 09:45:00'),
    ('10016', '举报狂魔', 's2', 31, 0, 'banned',            '多次恶意举报其他玩家，违反用户协议第4.6条', 2000.00, NULL, '2026-03-28 14:00:00'),
    ('10017', '月影',     's1', 44, 2, 'normal',            NULL, 888.00,  NULL, '2026-05-26 20:00:00'),
    ('10018', '萌新求带', 's3', 12, 0, 'normal',            NULL, 45.00,   NULL, '2026-05-10 16:30:00'),
    ('10019', '代充嫌疑', 's1', 50, 3, 'banned',            '使用非法第三方代充，违反用户协议第3.5条', 5000.00, NULL, '2026-01-05 10:00:00'),
    ('10020', '至尊VIP',  's1', 65, 5, 'normal',            NULL, 10000.00, NULL, '2026-05-29 06:00:00')
ON DUPLICATE KEY UPDATE
    nickname = VALUES(nickname),
    server_id = VALUES(server_id),
    level = VALUES(level),
    vip_level = VALUES(vip_level),
    status = VALUES(status),
    ban_reason = VALUES(ban_reason),
    recharge_total = VALUES(recharge_total),
    abnormal_detail = VALUES(abnormal_detail),
    last_login = VALUES(last_login);

-- ------------------------------------------------------------
-- Mock 工单（每个玩家 0~2 条，演示按 player_uid 隔离查询）
-- ------------------------------------------------------------
INSERT INTO support_tickets
    (ticket_id, player_uid, title, description, category, priority, status, agent_reply, session_id, created_at, resolved_at)
VALUES
    ('TK-20260501-1001', '10001', '充值未到账', '昨天充了648元原石没到账', 'payment', 'P1', 'resolved', '已补发，请查收邮件', '10001_sess_001', '2026-05-01 10:00:00', '2026-05-01 11:30:00'),
    ('TK-20260510-1002', '10001', '账号异地登录提醒', '收到异地登录短信是否正常', 'other', 'P2', 'resolved', '建议修改密码并开启二次验证', '10001_sess_002', '2026-05-10 14:20:00', '2026-05-10 14:45:00'),
    ('TK-20260410-2001', '10002', '申请解封', '我没有使用外挂，请核实', 'account_ban', 'P0', 'escalated', NULL, '10002_sess_001', '2026-04-10 19:00:00', NULL),
    ('TK-20260520-3001', '10003', '充值异常核实', '5000元充值显示异常', 'payment', 'P0', 'processing', '正在与支付渠道核实', '10003_sess_001', '2026-05-20 15:00:00', NULL),
    ('TK-20260528-6001', '10006', '活动奖励未发放', '完成活动未收到奖励', 'bug', 'P2', 'pending', NULL, '10006_sess_001', '2026-05-28 23:00:00', NULL),
    ('TK-20260529-9001', '10009', '大额充值风控', '9999元充值被拦截', 'payment', 'P0', 'processing', NULL, '10009_sess_001', '2026-05-29 08:30:00', NULL),
    ('TK-20260515-1501', '10015', '如何获得角色', '新手不知道如何抽卡', 'other', 'P2', 'resolved', '可在祈愿界面使用原石抽取', '10015_sess_001', '2026-05-15 10:00:00', '2026-05-15 10:05:00')
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    description = VALUES(description),
    agent_reply = VALUES(agent_reply);

-- Curated interview demo profiles
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
