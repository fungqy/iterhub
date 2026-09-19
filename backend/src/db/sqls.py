"""RDM 报表 SQL 常量已迁移

历史位置:本文件曾存放 RDM 报表派生表的 5 个大 SQL 常量,现已迁移至
`db.report_sqls`,本文件保留为兼容占位。

若代码 `from db.sqls import ...` 引入报表 SQL,请改为:
    from db.report_sqls import ...

说明:
- 迁移原因:把复杂报表 SQL 与业务逻辑分离,便于单独维护与测试。
- 不做 ORM 化迁移:这些 SQL 是整表 INSERT...SELECT 聚合,无 bind 参数,
  无参数化需求,保持 Python 常量更适合 pytest 直接断言。
"""
