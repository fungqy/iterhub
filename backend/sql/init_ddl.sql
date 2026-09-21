-- ================================================
-- 数据库初始化脚本
-- 数据库: iterdb
-- ================================================

use iterdb;

-- 系统用户表
CREATE TABLE IF NOT EXISTS sys_users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '用户ID',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT '用户名',
    password VARCHAR(255) NOT NULL COMMENT '密码(加密存储)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT '用户表';

-- 工作日表
CREATE TABLE IF NOT EXISTS sys_workday (
    year INT COMMENT '年份',
    datestr CHAR(10) COMMENT '日期',
    UNIQUE KEY uk_datestr (datestr)
) COMMENT '工作日表';


-- JIRA认证配置表(全局共享,单行;与登录用户无关)
CREATE TABLE IF NOT EXISTS project_jira_auth (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '配置ID',
    jira_url VARCHAR(255) NOT NULL DEFAULT 'http://rdm.zvos.zoomlion.com' COMMENT 'JIRA服务器地址',
    jira_user VARCHAR(100) NOT NULL COMMENT 'JIRA用户名',
    jira_token VARCHAR(255) NOT NULL COMMENT 'JIRA Token/Password',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT 'JIRA认证配置表(全局共享)';

-- 项目配置表
CREATE TABLE IF NOT EXISTS project_configs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '配置ID',
    board_id VARCHAR(50) NOT NULL COMMENT 'JIRA面板ID',
    board_name VARCHAR(255) NOT NULL COMMENT 'JIRA面板名称',
    project_id VARCHAR(50) NOT NULL COMMENT 'JIRA项目ID',
    project_name VARCHAR(255) NOT NULL COMMENT 'JIRA项目名称',
    gitlab_group_key VARCHAR(100) DEFAULT '' COMMENT 'GitLab Group Key',
    sonar_key_prefix VARCHAR(100) DEFAULT '' COMMENT 'Sonar Key前缀',
    sonar_scan_remind_default_person VARCHAR(100) DEFAULT '' COMMENT 'Sonar扫描默认提醒人',
    robot_key VARCHAR(100) DEFAULT '' COMMENT '企业微信机器人key',
    jira_user VARCHAR(100) DEFAULT '' COMMENT 'JIRA用户名',
    jira_token VARCHAR(255) DEFAULT '' COMMENT 'JIRA Token',
    jira_auth_config_id BIGINT COMMENT '关联的JIRA认证配置ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_board_id (board_id),
    UNIQUE KEY uk_project_id (project_id),
    FOREIGN KEY (jira_auth_config_id) REFERENCES project_jira_auth(id) ON DELETE SET NULL
) COMMENT '项目配置表';

-- 项目提醒设置表
CREATE TABLE IF NOT EXISTS project_reminder_settings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    project_config_id BIGINT NOT NULL UNIQUE COMMENT '关联的项目配置ID',
    need_story_remind TINYINT(1) DEFAULT 0 COMMENT '是否需要故事提醒',
    need_task_remind TINYINT(1) DEFAULT 0 COMMENT '是否需要子任务到期提醒',
    need_sonar_scan_remind TINYINT(1) DEFAULT 0 COMMENT '是否需要Sonar扫描提醒',
    need_report_data TINYINT(1) DEFAULT 0 COMMENT '是否需要生产报表数据',
    story_remind_time VARCHAR(10) DEFAULT NULL COMMENT '故事提醒时间(HH:MM格式)',
    task_remind_time VARCHAR(10) DEFAULT NULL COMMENT '任务提醒时间(HH:MM格式)',
    sonar_remind_time VARCHAR(10) DEFAULT NULL COMMENT 'Sonar扫描提醒时间(HH:MM格式)',
    report_data_time VARCHAR(10) DEFAULT NULL COMMENT '报表数据生成时间(HH:MM格式)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (project_config_id) REFERENCES project_configs(id) ON DELETE CASCADE
) COMMENT '项目提醒设置表';

-- ================================================
-- 业务报表相关表
-- ================================================

-- RDM故事完成时长
CREATE TABLE IF NOT EXISTS rdm_story_duration (
    project_id BIGINT COMMENT '项目ID',
    project_name VARCHAR(255) COMMENT '项目名称',
    sprint_id BIGINT COMMENT 'Sprint ID',
    sprint_name VARCHAR(255) COMMENT 'Sprint名称',
    story_id BIGINT COMMENT '故事ID',
    story_key VARCHAR(50) COMMENT '故事Key',
    story_name VARCHAR(500) COMMENT '故事名称',
    create_time DATETIME COMMENT '故事创建时间',
    complete_time DATETIME COMMENT '故事完成时间',
    duration INT COMMENT '故事完成时长(工作日秒数)',
    duration_str VARCHAR(50) COMMENT '故事完成时长(字符串格式)',
    duration_all INT COMMENT '故事完成时长(包含非工作日秒数)',
    duration_all_str VARCHAR(50) COMMENT '故事完成时长(包含非工作日,字符串格式)'
) COMMENT 'RDM故事完成时长';

-- RDM故障解决时长
CREATE TABLE IF NOT EXISTS rdm_bug_duration (
    project_id BIGINT COMMENT '项目ID',
    project_name VARCHAR(255) COMMENT '项目名称',
    sprint_id BIGINT COMMENT 'Sprint ID',
    sprint_name VARCHAR(255) COMMENT 'Sprint名称',
    short_sprint_name VARCHAR(100) COMMENT 'Sprint简称',
    sprint_seqno INT COMMENT 'Sprint序号',
    bug_id BIGINT COMMENT '故障ID',
    bug_key VARCHAR(50) COMMENT '故障Key',
    bug_name VARCHAR(500) COMMENT '故障名称',
    author VARCHAR(100) COMMENT '开发人员',
    create_time DATETIME COMMENT '创建时间',
    test_time DATETIME COMMENT '测试开始时间',
    finish_time DATETIME COMMENT '完成时间',
    dev_seconds_all BIGINT COMMENT '开发时长(包含非工作日,秒数)',
    dev_seconds BIGINT COMMENT '开发时长(工作日秒数)',
    dev_time_all_str VARCHAR(50) COMMENT '开发时长(包含非工作日,字符串格式)',
    dev_time_str VARCHAR(50) COMMENT '开发时长(字符串格式)',
    test_seconds_all BIGINT COMMENT '测试时长(包含非工作日,秒数)',
    test_seconds BIGINT COMMENT '测试时长(工作日秒数)',
    test_time_all_str VARCHAR(50) COMMENT '测试时长(包含非工作日,字符串格式)',
    test_time_str VARCHAR(50) COMMENT '测试时长(字符串格式)',
    finish_seconds_all BIGINT COMMENT '总完成时长(包含非工作日,秒数)',
    finish_seconds BIGINT COMMENT '总完成时长(工作日秒数)',
    finish_time_all_str VARCHAR(50) COMMENT '总完成时长(包含非工作日,字符串格式)',
    finish_time_str VARCHAR(50) COMMENT '总完成时长(字符串格式)'
) COMMENT 'RDM故障解决时长';

-- RDM各Sprint故障平均解决时长
CREATE TABLE IF NOT EXISTS rdm_bug_avgtime_sprint (
    project_id BIGINT COMMENT '项目ID',
    project_name VARCHAR(255) COMMENT '项目名称',
    sprint_id BIGINT COMMENT 'Sprint ID',
    sprint_name VARCHAR(255) COMMENT 'Sprint名称',
    short_sprint_name VARCHAR(100) COMMENT 'Sprint简称',
    sprint_seqno INT COMMENT 'Sprint序号',
    dev_seconds_all INT COMMENT '平均开发时长(包含非工作日,秒数)',
    dev_seconds INT COMMENT '平均开发时长(工作日秒数)',
    dev_time_all_str VARCHAR(50) COMMENT '平均开发时长(包含非工作日,字符串格式)',
    dev_time_str VARCHAR(50) COMMENT '平均开发时长(字符串格式)',
    test_seconds_all INT COMMENT '平均测试时长(包含非工作日,秒数)',
    test_seconds INT COMMENT '平均测试时长(工作日秒数)',
    test_time_all_str VARCHAR(50) COMMENT '平均测试时长(包含非工作日,字符串格式)',
    test_time_str VARCHAR(50) COMMENT '平均测试时长(字符串格式)',
    finish_seconds_all INT COMMENT '平均总完成时长(包含非工作日,秒数)',
    finish_seconds INT COMMENT '平均总完成时长(工作日秒数)',
    finish_time_all_str VARCHAR(50) COMMENT '平均总完成时长(包含非工作日,字符串格式)',
    finish_time_str VARCHAR(50) COMMENT '平均总完成时长(字符串格式)'
) COMMENT 'RDM各Sprint故障平均解决时长';

-- RDM各开发人员的故障平均解决时长
CREATE TABLE IF NOT EXISTS rdm_bug_avgtime_author (
    project_id BIGINT COMMENT '项目ID',
    project_name VARCHAR(255) COMMENT '项目名称',
    sprint_id BIGINT COMMENT 'Sprint ID',
    sprint_name VARCHAR(255) COMMENT 'Sprint名称',
    short_sprint_name VARCHAR(100) COMMENT 'Sprint简称',
    sprint_seqno INT COMMENT 'Sprint序号',
    author VARCHAR(100) COMMENT '开发人员',
    bug_count INT COMMENT '故障数量',
    dev_seconds_all INT COMMENT '平均开发时长(包含非工作日,秒数)',
    dev_seconds INT COMMENT '平均开发时长(工作日秒数)',
    dev_time_all_str VARCHAR(50) COMMENT '平均开发时长(包含非工作日,字符串格式)',
    dev_time_str VARCHAR(50) COMMENT '平均开发时长(字符串格式)',
    test_seconds_all INT COMMENT '平均测试时长(包含非工作日,秒数)',
    test_seconds INT COMMENT '平均测试时长(工作日秒数)',
    test_time_all_str VARCHAR(50) COMMENT '平均测试时长(包含非工作日,字符串格式)',
    test_time_str VARCHAR(50) COMMENT '平均测试时长(字符串格式)',
    finish_seconds_all INT COMMENT '平均总完成时长(包含非工作日,秒数)',
    finish_seconds INT COMMENT '平均总完成时长(工作日秒数)',
    finish_time_all_str VARCHAR(50) COMMENT '平均总完成时长(包含非工作日,字符串格式)',
    finish_time_str VARCHAR(50) COMMENT '平均总完成时长(字符串格式)'
) COMMENT 'RDM各开发人员的故障平均解决时长';



-- 任务执行记录表
CREATE TABLE IF NOT EXISTS project_task_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    project_config_id BIGINT NOT NULL COMMENT '项目配置ID',
    task_type VARCHAR(50) NOT NULL COMMENT '任务类型(story_reminder/task_reminder/sonar_reminder/report_data)',
    scheduled_time DATETIME NOT NULL COMMENT '计划执行时间',
    executed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '实际执行时间',
    status VARCHAR(20) NOT NULL COMMENT '执行状态(success/failed)',
    error_message VARCHAR(500) DEFAULT '' COMMENT '错误信息',
    task_exec_type VARCHAR(50) NOT NULL COMMENT '任务执行类型(manual/automatic)',
    FOREIGN KEY (project_config_id) REFERENCES project_configs(id) ON DELETE CASCADE
) COMMENT '任务执行记录表';


-- ==================================
-- RDM
-- ==================================
-- iterdb.rdm_issue definition

CREATE TABLE IF NOT EXISTS `rdm_issue` (
  `issue_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'issue_id',
  `sprint_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'sprint_id',
  `sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'sprint名称',
  `issue_key` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'issue_key',
  `issue_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'issue类型',
  `issue_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'issue名称',
  `reporter` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '报告人',
  `assignee` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '经办人',
  `created` datetime DEFAULT NULL COMMENT '创建时间',
  `updated` datetime DEFAULT NULL COMMENT '更新时间',
  `description` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '描述',
  `status` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '状态',
  `resolution` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '解决结果',
  `priority` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '优先级',
  `require_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '需求类型',
  `callback` int DEFAULT NULL COMMENT '打回次数',
  `developer` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '开发负责人',
  `tester` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '测试负责人',
  `duedate` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '到期日',
  `module` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '模块',
  `bug_story` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属故事',
  `bug_type` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '故障类型',
  `bug_flag` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '故障标签',
  `bug_reason` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '故障原因',
  `bug_solver` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '故障修复人',
  `bug_maker` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '故障产生人',
  `is_unplaned` tinyint DEFAULT NULL COMMENT '是否计划外',
  `sprint_active_date` datetime DEFAULT NULL COMMENT 'sprint启动时间',
  `plan_worktime` float DEFAULT NULL COMMENT '计划工时',
  `actual_worktime` float DEFAULT NULL COMMENT '实际工时',
  `actual_worktime2` varchar(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '镜像提交信息',
  KEY `idx_issues_sprint_id_name` (`sprint_id`,`sprint_name`),
  KEY `idx_issues_sprint_id` (`sprint_id`),
  KEY `idx_issues_id` (`issue_id`),
  KEY `idx_issues_key` (`issue_key`),
  KEY `idx_issues_id_key` (`issue_id`,`issue_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='rdm issue数据';

-- iterdb.sprint definition

CREATE TABLE IF NOT EXISTS `rdm_sprint` (
  `board_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '看板id',
  `board_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '看板名称',
  `project_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目id',
  `project_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目名称',
  `sprint_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint id',
  `origin_sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '原Sprint名称',
  `sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint名称',
  `short_sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短Sprint名称',
  `startdate` datetime DEFAULT NULL COMMENT 'Sprint计划开始日期',
  `enddate` datetime DEFAULT NULL COMMENT 'Sprint计划结束日期',
  `activated_date` datetime DEFAULT NULL COMMENT 'Sprint激活日期',
  `complete_date` datetime DEFAULT NULL COMMENT 'Sprint完成日期',
  `state` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint状态',
  `goal` varchar(1024) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint目标',
  KEY `idx_sprint_id_name` (`sprint_id`,`sprint_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='rdm sprint数据';


-- iterdb.bug_flag_class definition

CREATE TABLE IF NOT EXISTS `rdm_bug_label_class` (
  `class_id` int DEFAULT NULL COMMENT 'Bug标签分类ID',
  `class_name` varchar(50) DEFAULT NULL COMMENT 'Bug标签分类名称',
  `label` varchar(512) DEFAULT NULL COMMENT 'Bug标签'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bug标签分类';


-- iterdb.bug_changelog definition

CREATE TABLE IF NOT EXISTS `rdm_bug_changelog` (
  `log_id` varchar(50) DEFAULT NULL COMMENT '变更日志id',
  `bug_id` varchar(50) DEFAULT NULL COMMENT '故障id',
  `bug_key` varchar(50) DEFAULT NULL COMMENT '故障key',
  `bug_name` varchar(512) DEFAULT NULL COMMENT '故障名称',
  `bug_solver` varchar(100) DEFAULT NULL COMMENT '故障归属人',
  `author` varchar(100) DEFAULT NULL COMMENT '变更人',
  `change_time` datetime DEFAULT NULL COMMENT '变更时间',
  `change_type` varchar(50) DEFAULT NULL COMMENT '变更类型',
  `change_detail` varchar(512) DEFAULT NULL COMMENT '变更详情',
  `project_id` varchar(50) DEFAULT NULL COMMENT '项目id',
  `project_name` varchar(512) DEFAULT NULL COMMENT '项目名称',
  `sprint_id` varchar(50) DEFAULT NULL COMMENT 'SprintID',
  `sprint_name` varchar(512) DEFAULT NULL COMMENT '看板id',
  KEY `idx_project_sprint_bug` (`project_id`,`sprint_id`,`bug_id`),
  KEY `idx_project_bug` (`project_id`,`bug_id`),
  KEY `idx_sprint_bug` (`sprint_id`,`bug_id`),
  KEY `idx_sprint` (`sprint_id`),
  KEY `idx_bug` (`bug_id`),
  KEY `idx_key` (`bug_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='bug变更记录';


-- iterdb.story_changelog definition

CREATE TABLE IF NOT EXISTS `rdm_story_changelog` (
  `log_id` varchar(50) DEFAULT NULL COMMENT '日志id',
  `story_id` varchar(50) DEFAULT NULL COMMENT '故事id',
  `story_key` varchar(50) DEFAULT NULL COMMENT '故事key',
  `complete_time` datetime DEFAULT NULL COMMENT '完成时间',
  `author` varchar(100) DEFAULT NULL COMMENT '变更人',
  `change_time` datetime DEFAULT NULL COMMENT '变更时间',
  `change_detail` varchar(512) DEFAULT NULL COMMENT '变更详情',
  KEY `idx_story_id` (`story_id`),
  KEY `idx_story_key` (`story_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事变更记录';


-- iterdb.rdm_testcase definition
-- 测试用例由「文档导入」写入,归属 sprint 由用例引用的故事号(【需求】列)反查 rdm_issue 得到

CREATE TABLE IF NOT EXISTS `rdm_testcase` (
  `case_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例issue_id',
  `case_key` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例key',
  `case_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例名称',
  `status` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例状态',
  `exec_status` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '执行状态(cf_11107)',
  `module` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '模块(cf_11102)',
  `story_key` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '归属故事key(文档导入的【需求】列)',
  `labels` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '标签',
  `description` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '描述',
  `steps` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '测试步骤(JSON数组:no/action/data/expected)',
  `sprint_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint id',
  `sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint名称',
  `project_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目id',
  `project_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目名称',
  `created` datetime DEFAULT NULL COMMENT '创建时间',
  `updated` datetime DEFAULT NULL COMMENT '更新时间',
  KEY `idx_testcase_sprint_id` (`sprint_id`),
  KEY `idx_testcase_case_id` (`case_id`),
  KEY `idx_testcase_case_key` (`case_key`),
  KEY `idx_testcase_story_key` (`story_key`),
  UNIQUE KEY `uk_testcase_case_story` (`case_id`, `story_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='rdm测试用例数据';


-- ==================================
-- DOC
-- ==================================
-- iterdb.rdm_doc_bug definition
--
-- 数据来源：docs/应用平台现场问题沟通新.xlsx 的「问题明细表」（单 sheet、26 列）。
-- 列号→字段的完整映射与导入规则见 api/routes/data_import.py 的「文档故障导入」一节，
-- 两侧必须同步改。
--
-- 三个口径要点：
--   1. sprint_id 由表内【sprint】列决定（名称归一化匹配 rdm_sprint），**不由上传参数决定**；
--      project_id 跟着命中的 rdm_sprint.project_id 走。
--   2. key（自动编号，形如 m0609001）全表唯一 —— 重复导入走 ON DUPLICATE KEY UPDATE，
--      因此重导同一份文件是幂等的，不会堆重复行。
--   3. 旧表头的【提出人】(propose)、【处理状态】里没有的【已排期】等差异已随新表口径重写。

CREATE TABLE IF NOT EXISTS `rdm_doc_bug` (
  `key` varchar(50) NOT NULL COMMENT '编码',  -- 取【自动编号】列（旧表头叫「问题编号」）：m+MMDD+当日流水，全表唯一
  `name` text DEFAULT NULL COMMENT '名称', -- 取【功能点】和【问题详述】列进行拼接，拼接规则：【功能点】>【问题详述】，若【功能点】为空，只取【问题详述】
  `priority` varchar(50) DEFAULT NULL COMMENT '优先级', -- 取【优先级】列原值直通：极高/高/中/低/优化。「优化」是新表原生值，不再只由「低」转换而来（两者落同一个桶）
  `reason` varchar(512) DEFAULT NULL COMMENT '原因', -- 取【原因分析】和【处理意见】列进行拼接，拼接规则：【原因分析】>【处理意见】，若【处理意见】为空，只取【原因分析】
  `resolve_method` mediumtext DEFAULT NULL COMMENT '解决方法', -- 取【处理方式】列：开发修改/需求变更/不处理，多值用逗号拼接
  `maker` varchar(100) DEFAULT NULL COMMENT '产生人',  -- 取【处理人】列。需要将内容中的@、换行符、中文逗号都转换成英文逗号，然后按英文逗号分隔，取最后一个不为空的值
  `propose_time` datetime DEFAULT NULL COMMENT '提出时间',  -- 取【创建日期】列（旧表头叫「提出时间」）
  `resolve_time` datetime DEFAULT NULL COMMENT '解决时间',  -- 取【解决日期】列（旧表头叫「完成时间」）
  `status` varchar(50) DEFAULT NULL COMMENT '状态(不处理、处理中、待测试、继续观察、未开始、验证通过、已解决、转任务、转需求、已排期)',  -- 取【处理状态】列，不在上述范围内则拒绝该行并提示
  `type` varchar(100) DEFAULT NULL COMMENT '类型(代码问题、需求完善、功能优化、环境问题、沟通问题、模型能力问题、其他)', -- 取【问题类别】列，经 data_import.CATEGORY_MAP 归一化；空值/未识别归「其他」。⚠ 词表对齐 reports.py 的 CANONICAL_TAGS，09-17 起「代码实现」改称「代码问题」
  `original_type` varchar(100) DEFAULT NULL COMMENT '原类型', -- 取【问题类别】列原值（旧表头叫「问题类型」）
  `sprint_id` varchar(50) DEFAULT NULL COMMENT 'SprintID',  -- 取【sprint】列，按「去空白/连字符 + 忽略大小写」匹配 rdm_sprint.sprint_name 得到 id
  `project_id` varchar(512) DEFAULT NULL COMMENT '项目ID', -- 由命中的 rdm_sprint.project_id 反查，不由上传参数决定
  `story_key` varchar(50) DEFAULT NULL COMMENT '故事号',  -- 取【故事号】列（库里对应 rdm_issue.issue_key 的后缀，如 4068 → EMBODIED_ADP-4068）
  `verify_note` varchar(512) DEFAULT NULL COMMENT '验证备注',  -- 取【验证备注】列
  `is_repeated` varchar(10) DEFAULT NULL COMMENT '反复(是/否)',  -- 取【反复】列
  `is_occasional` varchar(10) DEFAULT NULL COMMENT '偶发(是/否)',  -- 取【偶发】列
  `last_editor` varchar(100) DEFAULT NULL COMMENT '最后编辑人',  -- 取【最后编辑人】列
  `last_edit_time` datetime DEFAULT NULL COMMENT '最后编辑时间',  -- 取【最后编辑时间】列（源格式为「2026年9月7日」）
  `bounce_count` int DEFAULT NULL COMMENT '打回次数',  -- 取【打回次数】列，非数字落 NULL
  `rdm_key` varchar(50) DEFAULT NULL COMMENT 'rdm编号',  -- 取【rdm】列
  UNIQUE KEY `uk_doc_bug_key` (`key`),
  KEY `idx_doc_bug_sprint_id` (`sprint_id`),
  KEY `idx_doc_bug_project_id` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档故障';


-- ==================================
-- 文档故障截图
-- ==================================
-- iterdb.rdm_doc_bug_image definition
--
-- 源表「问题明细表」里的【截图1】【截图2】两列存的是**浮动图片**(现 395 个锚点),
-- 不是单元格的值 —— openpyxl 的 read_only 会整个跳过 xl/media,所以导入文本时拿不到它们。
-- 本表把图片二进制落库,由导入侧解析 xl/drawings/drawing1.xml 的 oneCellAnchor 反算归属。
--
-- 设计取舍(全部是踩过/量过之后的结论,改前先看):
--   1. **按 (doc_bug_key, seq) 存,不按内容哈希去重。** 实测同一张图会被两个不同故障
--      引用(image313/314/315 同时属于 m09021020 与 m09031042),一个 key 内也有重复引用。
--      图片的语义是「属于哪个故障」,不是「文件去重」,用哈希做主键会把两个故障的图错误合并。
--   2. **外键 + ON DELETE CASCADE**:清空/删除 rdm_doc_bug 时图片自动跟走,不需要在
--      业务代码里记得清理,天然不会留孤儿行。
--   3. **原图与缩略图分列存**:原图中位 2618×1448 / 587KiB,直接铺在弹窗里偏重;
--      缩略图(WebP,宽 ≤560)供缩略图带与首屏用,原图只在「看大图」时才取。
--   4. `seq` 的排序口径:先按来源列(截图1 在 截图2 前),再按表内锚点的原始行序。
--   5. 只会有**有 sprint 的行**的图片入表(现 54 张 / 31MiB)—— 无 sprint 的行不导入,
--      其图片(341 张)一并跳过,与本表的存留范围严格一致。

CREATE TABLE IF NOT EXISTS `rdm_doc_bug_image` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `doc_bug_key` varchar(50) NOT NULL COMMENT '所属文档故障编码,对应 rdm_doc_bug.key',
  `seq` int NOT NULL COMMENT '同一故障内的图片序号(从 1 开始)',
  `column_label` varchar(16) DEFAULT NULL COMMENT '来源列:截图1 / 截图2',
  `source_name` varchar(128) DEFAULT NULL COMMENT '源文件内条目名(如 xl/media/image120.png),便于追溯',
  `mime_type` varchar(64) NOT NULL DEFAULT 'image/png' COMMENT '原图 MIME',
  `byte_size` int DEFAULT NULL COMMENT '原图字节数',
  `width` int DEFAULT NULL COMMENT '原图宽(px,取自 PNG IHDR)',
  `height` int DEFAULT NULL COMMENT '原图高(px)',
  `sha256` char(64) DEFAULT NULL COMMENT '原图内容哈希,用于 ETag 与变更判定',
  `thumb_mime` varchar(64) DEFAULT NULL COMMENT '缩略图 MIME(image/webp,生成失败时为 NULL)',
  `thumb_byte_size` int DEFAULT NULL COMMENT '缩略图字节数',
  `data` mediumblob NOT NULL COMMENT '原图二进制',
  `thumb` mediumblob DEFAULT NULL COMMENT '缩略图二进制(缩略图带/首屏用)',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_doc_bug_image_seq` (`doc_bug_key`, `seq`),
  CONSTRAINT `fk_doc_bug_image_key` FOREIGN KEY (`doc_bug_key`)
    REFERENCES `rdm_doc_bug` (`key`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档故障截图';


-- ==================================
-- Sprint 展示控制
-- ==================================
-- iterdb.rdm_sprint_exclude definition
--
-- 「不参与前端展示」的 Sprint 屏蔽名单(人工维护)。
-- 语义:名单内的 sprint_id 一律不作为展示迭代返回给前端,覆盖四处展示入口
--   A 报表页 Sprint 时间轴   GET /api/reports/db-sprints/{id}
--   B 报表页 趋势图/重开分布 GET /api/reports/project-metrics/{id}
--   C 数据导入 Sprint 下拉   GET /api/data-import/sprints/{id}
--   D 作业页 手动执行下拉    GET /api/reports/sprints/{id}(RDM 实时拉取)
-- 隔离方式:刻意**不删除** rdm_sprint 中的原始行 —— 屏蔽只在读取侧生效,
-- 因此解屏蔽是即时的,且不会因 D 路径的「全量覆盖写入」而被重新引入。
-- 本表为空时行为与不存在该功能完全一致。

CREATE TABLE IF NOT EXISTS rdm_sprint_exclude (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  sprint_id VARCHAR(50) NOT NULL COMMENT 'Sprint id(对应 rdm_sprint.sprint_id)',
  project_id VARCHAR(50) DEFAULT NULL COMMENT 'JIRA项目id(便于按项目排查与清理)',
  sprint_name VARCHAR(512) DEFAULT NULL COMMENT 'Sprint名称(入表时快照,便于人工核对)',
  reason VARCHAR(255) DEFAULT NULL COMMENT '屏蔽原因',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '加入名单时间',
  UNIQUE KEY uk_sprint_exclude_sprint (sprint_id),
  KEY idx_sprint_exclude_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='不参与前端展示的Sprint屏蔽名单(人工维护)';


-- ==================================
-- WIKI 代码评审
-- ==================================
-- iterdb.review_records_details definition
--
-- 由 task/report_wiki_data.py 这个**独立脚本**写入(它不在调度器里,需手工执行):
--   1. 每次运行先 TRUNCATE 本表,再从 Confluence 抓「代码评审」段落、解析附件 xlsx,全量重写;
--   2. 一行 = 一条评审意见明细(某条评审记录 × xlsx 里的一行),故 project / sprint / title
--      这些「记录级」字段会在多行之间重复。
--
-- 列就是该脚本 DataFrame 的列,**不多不少**:脚本用 to_sql(if_exists="append") 按列名写入,
-- 本表结构与 parse_record / parse_detail_from_xlsx 的返回字段必须同步改。
--
-- ⚠ 补记(2026-09-20):本表此前只存在于线上库,任何建表脚本里都没有 —— 新库首次跑脚本会因
--   TRUNCATE 报「表不存在」而失败(truncate_table 现已失败即抛,不再静默吞掉)。

CREATE TABLE IF NOT EXISTS `review_records_details` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project` varchar(255) DEFAULT NULL COMMENT '项目名(取 Confluence 页面名)',
  `sprint` varchar(50) DEFAULT NULL COMMENT 'Sprint 编号(从评审标题正则提取,如 Sprint12)',
  `title` varchar(512) DEFAULT NULL COMMENT '评审标题(含「代码评审」的那一行原文)',
  `review_type` varchar(20) DEFAULT NULL COMMENT '评审类型:前端/后端(取不到为 NULL)',
  `review_date` varchar(50) DEFAULT NULL COMMENT '评审日期(原文直通,未做日期解析)',
  `reviewers` varchar(512) DEFAULT NULL COMMENT '评审人员(原文)',
  `attachments` varchar(512) DEFAULT NULL COMMENT '附件文件名,多个以换行拼接',
  `code_filepath` varchar(1024) DEFAULT NULL COMMENT '代码文件路径(xlsx【文件路径】列)',
  `code_linenumber` varchar(50) DEFAULT NULL COMMENT '代码行号(xlsx【代码行号】列)',
  `code_snippet` mediumtext COMMENT '代码片段(xlsx【代码片段】列)',
  `comment_type` varchar(50) DEFAULT NULL COMMENT '意见类型',
  `checked_by` varchar(255) DEFAULT NULL COMMENT '检视人员',
  `comment` mediumtext COMMENT '检视意见',
  `confirmed_by` varchar(255) DEFAULT NULL COMMENT '实际确认人员',
  `confirm_result` varchar(255) DEFAULT NULL COMMENT '确认结果',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间(每次全量重写时刷新)',
  PRIMARY KEY (`id`),
  KEY `idx_review_project_sprint` (`project`, `sprint`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='WIKI代码评审明细(脚本全量重写)';
