-- 与客服库共用同一 MySQL 实例：仅创建知识库 schema 与账号。
-- 由 compose 的 db-init 每次启动执行（IF NOT EXISTS，可重复跑）。
-- 表结构由 enterprise-rag 启动时 SQLAlchemy create_all 创建。

CREATE DATABASE IF NOT EXISTS rag_database
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'rag_user'@'%' IDENTIFIED BY 'rag_password';
GRANT ALL PRIVILEGES ON rag_database.* TO 'rag_user'@'%';
FLUSH PRIVILEGES;
