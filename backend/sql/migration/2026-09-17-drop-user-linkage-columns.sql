-- 2026-09-17 取消「业务数据与登录用户」的关联:删除各表中的用户关联字段
--
-- 背景：产品决定用户只用于登录识别,业务数据全部与用户无关、所有用户共享。故把
--       「谁创建/谁更新/操作人/凭据所属用户」这类字段从业务表中彻底移除:
--         project_configs.created_by / updated_by   —— 项目创建者/更新者
--         project_jira_auth.user_id                 —— JIRA 凭据的所属用户
--         rdm_sprint_exclude.created_by             —— Sprint 屏蔽名单的操作人
--       JIRA 凭据改为全局共享(project_jira_auth 单行,代码取 id 最小的一行)。
--
-- 应用对象：iterdb
-- 执行方式：backend/.venv/Scripts/python.exe 里用 pymysql 执行（整段不是单条语句）
--
-- ⚠ 外键必须先删,再删列;若线上约束名与下文不同(例如由 create_all 建表),请先用
--    SHOW CREATE TABLE <表名> 确认后再改这里的名字。
-- 与 sql/init_ddl.sql、sql/iterdb.sql、sql/iterdb-0915.sql 中的定义保持一致;
-- 改一处必须同步另一处。

use iterdb;

-- 项目配置表:去掉 created_by / updated_by(及其外键与索引)
ALTER TABLE `project_configs` DROP FOREIGN KEY `project_configs_ibfk_2`;
ALTER TABLE `project_configs` DROP FOREIGN KEY `project_configs_ibfk_3`;
ALTER TABLE `project_configs` DROP COLUMN `created_by`;
ALTER TABLE `project_configs` DROP COLUMN `updated_by`;

-- JIRA 认证配置表:去掉所属用户,改为全局共享(唯一键随列一并删除)
ALTER TABLE `project_jira_auth` DROP FOREIGN KEY `project_jira_auth_ibfk_1`;
ALTER TABLE `project_jira_auth` DROP COLUMN `user_id`;

-- 若历史上多个用户各配置过一份 JIRA 凭据,删列后表中会留下多行;代码取 id 最小的一行。
-- 如要收敛为单行,确认保留哪一行后取消下面一行的注释再执行(会删除其余行):
-- DELETE FROM `project_jira_auth` WHERE `id` <> (SELECT * FROM (SELECT MIN(`id`) FROM `project_jira_auth`) AS keep);

-- Sprint 展示屏蔽名单:去掉操作人
ALTER TABLE `rdm_sprint_exclude` DROP COLUMN `created_by`;
