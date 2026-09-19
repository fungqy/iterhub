-- 2026-09-16 文档故障截图入库：新增 rdm_doc_bug_image
--
-- 背景：源表「问题明细表」的【截图1】【截图2】两列存的是浮动图片（现 395 个锚点），
--       不是单元格值 —— 导入文本时（openpyxl read_only）会被整批跳过。为了让
--       「故障明细列表里点开文档故障能看到对应截图」，把图片二进制落库。
--       归属由导入侧解析 xl/drawings/drawing1.xml 的 oneCellAnchor 反算得到：
--         sheet 行 = 锚点 0-based row + 1；列 8 → 截图1、列 11 → 截图2。
--       （已验证：395 个锚点全部落在列 8/11；工作簿只有「问题明细表」一张 sheet，
--         故 sheet2.xml → drawing1.xml 的行号对齐是确定的。）
--
-- 应用对象：iterdb（新增表，对既有数据无影响）
-- 执行方式：backend/.venv/Scripts/python.exe 里用 pymysql 执行（整段不是单条语句）
--
-- 与 sql/init_ddl.sql 中的定义保持一致；改一处必须同步另一处。

use iterdb;

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
