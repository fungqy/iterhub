-- 2026-09-16 文档故障导入改版：rdm_doc_bug 对齐新表「应用平台现场问题沟通新.xlsx」
--
-- 背景：导入源从「问题编号/提出时间/完成时间/问题类型」那套旧表头，
--       换成了 docs/应用平台现场问题沟通新.xlsx 的「问题明细表」（26 列）。
--       列映射细则见 api/routes/data_import.py；本脚本只负责把已有库改成新结构。
--
-- 应用对象：iterdb.rdm_doc_bug（执行时该表为 0 行，故 MODIFY / UNIQUE 均无冲突风险）
-- 执行方式：backend/.venv/Scripts/python.exe 里用 pymysql 逐条执行（整段不是单条语句）

use iterdb;

ALTER TABLE `rdm_doc_bug`
  -- 旧表头的【提出人】在新表里已经不存在，且全仓库无任何消费点
  DROP COLUMN `propose`,
  -- 新表新增的 8 列
  ADD COLUMN `story_key` varchar(50) DEFAULT NULL COMMENT '故事号',
  ADD COLUMN `verify_note` varchar(512) DEFAULT NULL COMMENT '验证备注',
  ADD COLUMN `is_repeated` varchar(10) DEFAULT NULL COMMENT '反复(是/否)',
  ADD COLUMN `is_occasional` varchar(10) DEFAULT NULL COMMENT '偶发(是/否)',
  ADD COLUMN `last_editor` varchar(100) DEFAULT NULL COMMENT '最后编辑人',
  ADD COLUMN `last_edit_time` datetime DEFAULT NULL COMMENT '最后编辑时间',
  ADD COLUMN `bounce_count` int DEFAULT NULL COMMENT '打回次数',
  ADD COLUMN `rdm_key` varchar(50) DEFAULT NULL COMMENT 'rdm编号',
  -- 编号是导入的幂等键：唯一化后重导同一份文件走 ON DUPLICATE KEY UPDATE
  MODIFY COLUMN `key` varchar(50) NOT NULL COMMENT '编码',
  DROP INDEX `idx_doc_bug_key`,
  ADD UNIQUE KEY `uk_doc_bug_key` (`key`),
  -- 「已有数据 / 重新导入 / 列表」改成按项目维度查询，需要这个索引
  ADD KEY `idx_doc_bug_project_id` (`project_id`),
  -- 三个枚举列的注释随新表口径更新（类型/长度不变）
  MODIFY COLUMN `status` varchar(50) DEFAULT NULL COMMENT '状态(不处理、处理中、待测试、继续观察、未开始、验证通过、已解决、转任务、转需求、已排期)',
  MODIFY COLUMN `type` varchar(100) DEFAULT NULL COMMENT '类型(代码实现、需求完善、环境问题、沟通问题、功能优化、模型能力问题、其他)',
  MODIFY COLUMN `original_type` varchar(100) DEFAULT NULL COMMENT '原类型';
