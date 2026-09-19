-- 2026-09-17 取消用户身份(管理员)逻辑：删除 sys_users.is_admin
--
-- 背景：产品决定取消「管理员 / 普通用户」的角色区分，所有登录用户共享全部数据与功能。
--       角色判定原先散落在三处（JWT payload、项目与报表的可见性及增删改权限、
--       前端管理员标签与按钮 gating），已随本次变更一并移除。sys_users.is_admin
--       不再被任何代码读写，故从表中删除，避免留下与代码不一致的「幽灵字段」。
--
-- 应用对象：iterdb（仅删列，不影响 sys_users 的其余数据；sys_users 上的外键
--          由 project_jira_auth / project_configs 指向它，删本表的列不影响这些引用）
-- 执行方式：backend/.venv/Scripts/python.exe 里用 pymysql 执行（整段不是单条语句）
--
-- 与 sql/init_ddl.sql、sql/iterdb.sql、sql/iterdb-0915.sql 中的定义保持一致；
-- 改一处必须同步另一处。

use iterdb;

ALTER TABLE `sys_users` DROP COLUMN `is_admin`;
