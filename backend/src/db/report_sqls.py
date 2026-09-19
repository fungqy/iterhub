"""RDM 报表派生表的 SQL 常量

由 task/report_rdm_data.py 在生成报表数据时执行(整表 INSERT...SELECT)。
这些 SQL 是复杂的报表聚合逻辑,刻意保持为 Python 常量以便 pytest 直接
import 断言内容,不做 ORM 化迁移(收益低、风险高)。

说明:
- RDM_STORY_DURATION_SQL / RDM_BUG_DURATION_SQL: 由 report_rdm_data.
  process_sprint 直接执行(常规调度入口)。
- RDM_BUG_AVGTIME_SPRINT_SQL / AUTHORS_BUGS_AVG_COMPLETE_
  DURATION_SQL: 平均完成时长派生表,当前无调度入口,保留为历史与后续扩展。
"""

# 生成故事完成时长表数据
RDM_STORY_DURATION_SQL = """
insert into rdm_story_duration
select
    t3.project_id,
    t3.project_name,
    t2.sprint_id,
    t2.sprint_name,
    t1.story_id,
	t1.story_key,
	t2.story_name,
	t1.create_time,
	t1.complete_time,
	t1.duration,
    CONCAT_WS('',
        CASE WHEN FLOOR((t1.duration + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((t1.duration + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((t1.duration + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration + 43200) / 86400) = 0
             AND FLOOR((t1.duration + 30) / 3600) > 0
             THEN CONCAT(FLOOR((t1.duration + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration + 43200) / 86400) = 0
             AND FLOOR(((t1.duration + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((t1.duration + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS duration_str,
    t1.duration_all,
    CONCAT_WS('',
        CASE WHEN FLOOR((t1.duration_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((t1.duration_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((t1.duration_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration_all + 43200) / 86400) = 0
             AND FLOOR((t1.duration_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((t1.duration_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((t1.duration_all + 43200) / 86400) = 0
             AND FLOOR(((t1.duration_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((t1.duration_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS duration_all_str
from
( 
     SELECT
     t.story_id,
     t.story_key,
     t.change_time as create_time,
     t.complete_time,
     SUM(
          TIMESTAMPDIFF(SECOND,
               GREATEST(t.change_time, CONCAT(di.datestr, ' 00:00:00')),
               LEAST(t.complete_time, CONCAT(di.datestr, ' 23:59:59'))
          )
     ) AS duration,
     SUM(
          TIMESTAMPDIFF(SECOND,
               GREATEST(t.change_time, CONCAT(di.datestr, ' 00:00:00')),
               LEAST(t.complete_time, CONCAT(di.datestr, ' 23:59:59'))
          )
     ) AS duration_all
     FROM
     (
     SELECT * 
     FROM rdm_story_changelog 
     WHERE log_id = 1 
          AND complete_time IS NOT NULL
     ) t
     JOIN
     sys_workday di
     ON
     di.datestr BETWEEN DATE(t.change_time) AND DATE(t.complete_time)
     GROUP BY
     t.story_id, 
     t.story_key, 
     t.change_time, 
     t.complete_time
) t1
left join
(
	select
		issue_id,
        issue_key,
        issue_name as story_name,
        sprint_id,
        sprint_name,
        ROW_NUMBER() OVER(partition by issue_id, issue_key order by sprint_id desc) rn
    from iterdb.rdm_issue
)  t2
on
	t1.story_id = t2.issue_id
and
	t1.story_key = t2.issue_key
and
	t2.rn = 1
left JOIN
	iterdb.rdm_sprint t3
on
	t2.sprint_id = t3.sprint_id
"""

# 生成故障完成时长表数据
RDM_BUG_DURATION_SQL = """
insert into rdm_bug_duration
WITH
t_bugs AS (
	select t.* from
	(select t.* ,row_number() over(partition by sprint_id, bug_id, change_detail order by change_time desc) rn
	 from iterdb.rdm_bug_changelog t
     where bug_name not like '%视觉%'
     and (change_type = 'create' or change_detail in ('待测试 -> 完成', '处理中 -> 待测试'))
	) t
	where rn = 1
),
t_bugs_create_time AS (select * from t_bugs where change_type = 'create'),
t_bugs_finish_time AS (select * from t_bugs where change_detail = '待测试 -> 完成'),
t_bugs_test_time AS (select * from t_bugs where change_detail = '处理中 -> 待测试'),
t_sprint_seqno AS (select project_id, sprint_id, short_sprint_name, row_number() over(partition by project_id order by sprint_id) sprint_seqno from iterdb.rdm_sprint),
t_main AS (
            select
                t1.project_id,
            	t1.project_name,
                t1.sprint_id,
            	t1.sprint_name,
            	t4.short_sprint_name,
            	t4.sprint_seqno,
	        	t1.bug_id,
                t1.bug_key,
                t1.bug_name,
                replace(t1.bug_solver, 'OLD', '') author,
            	t3.change_time as create_time,
            	t2.change_time as test_time,
            	t1.change_time as finish_time
            from t_bugs_finish_time t1
            inner join t_bugs_test_time t2
            on t1.sprint_id = t2.sprint_id and t1.bug_id = t2.bug_id
            inner join t_bugs_create_time t3
            on t1.sprint_id = t3.sprint_id and t1.bug_id = t3.bug_id
            left join t_sprint_seqno t4
            on t1.project_id = t4.project_id and t1.sprint_id = t4.sprint_id
          )
select
    dev.*,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev.dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev.dev_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev.dev_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR((dev.dev_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev.dev_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((dev.dev_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev.dev_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev.dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev.dev_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev.dev_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds + 43200) / 86400) = 0
             AND FLOOR((dev.dev_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev.dev_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev.dev_seconds + 43200) / 86400) = 0
             AND FLOOR(((dev.dev_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev.dev_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_str,
	test.test_seconds_all,
    test.test_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((test.test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test.test_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test.test_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds_all + 43200) / 86400) = 0
             AND FLOOR((test.test_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test.test_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((test.test_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test.test_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((test.test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test.test_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test.test_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds + 43200) / 86400) = 0
             AND FLOOR((test.test_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test.test_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test.test_seconds + 43200) / 86400) = 0
             AND FLOOR(((test.test_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test.test_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_str,
	finish.finish_seconds_all,
	finish.finish_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish.finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish.finish_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish.finish_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR((finish.finish_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish.finish_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((finish.finish_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish.finish_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish.finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish.finish_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish.finish_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds + 43200) / 86400) = 0
             AND FLOOR((finish.finish_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish.finish_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish.finish_seconds + 43200) / 86400) = 0
             AND FLOOR(((finish.finish_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish.finish_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_str
from
(
     SELECT
     t.project_id,
     t.project_name,
     t.sprint_id,
     t.sprint_name,
     t.short_sprint_name,
     t.sprint_seqno,
     t.bug_id,
     t.bug_key,
     t.bug_name,
     t.author,
     t.create_time,
     t.test_time,
     t.finish_time,
     TIMESTAMPDIFF(SECOND, t.create_time, t.test_time) AS dev_seconds_all,  -- 自然日总时长
     COALESCE(SUM(TIMESTAMPDIFF(SECOND,
          GREATEST(t.create_time, CONCAT(dev.datestr, ' 00:00:00')),
          LEAST(t.test_time, CONCAT(dev.datestr, ' 23:59:59'))
     )), 0) AS dev_seconds  -- 工作日时长
     FROM t_main t
     LEFT JOIN sys_workday dev  -- 改为 LEFT JOIN
     ON dev.datestr BETWEEN DATE(t.create_time) AND DATE(t.test_time)
     GROUP BY
     t.project_id,
     t.project_name,
     t.sprint_id,
     t.sprint_name,
     t.short_sprint_name,
     t.sprint_seqno,
     t.bug_id,
     t.bug_key,
     t.bug_name,
     t.author,
     t.create_time,
     t.test_time,
     t.finish_time
) dev
left join
(
     SELECT
     t.project_id,
     t.sprint_id,
     t.bug_id,
     t.test_time,
     t.finish_time,
     TIMESTAMPDIFF(SECOND, t.test_time, t.finish_time) AS test_seconds_all,  -- 自然日总时长
     COALESCE(SUM(TIMESTAMPDIFF(SECOND,
          GREATEST(t.test_time, CONCAT(test.datestr, ' 00:00:00')),
          LEAST(t.finish_time, CONCAT(test.datestr, ' 23:59:59'))
     )), 0) AS test_seconds  -- 工作日时长
     FROM t_main t
     LEFT JOIN sys_workday test  -- 改为 LEFT JOIN
     ON test.datestr BETWEEN DATE(t.test_time) AND DATE(t.finish_time)
     GROUP BY
     t.project_id,
     t.sprint_id,
     t.bug_id,
     t.test_time,
     t.finish_time
) test
on dev.project_id = test.project_id and dev.sprint_id = test.sprint_id and dev.bug_id = test.bug_id
left join
(
     SELECT
     t.project_id,
     t.sprint_id,
     t.bug_id,
     t.create_time,
     t.finish_time,
     TIMESTAMPDIFF(SECOND, t.create_time, t.finish_time) AS finish_seconds_all,  -- 自然日总时长
     COALESCE(SUM(TIMESTAMPDIFF(SECOND,
          GREATEST(t.create_time, CONCAT(finish.datestr, ' 00:00:00')),
          LEAST(t.finish_time, CONCAT(finish.datestr, ' 23:59:59'))
     )), 0) AS finish_seconds  -- 工作日时长
     FROM t_main t
     LEFT JOIN sys_workday finish  -- 改为 LEFT JOIN
     ON finish.datestr BETWEEN DATE(t.create_time) AND DATE(t.finish_time)
     GROUP BY
     t.project_id,
     t.sprint_id,
     t.bug_id,
     t.create_time,
     t.finish_time
) finish
on dev.project_id = finish.project_id and dev.sprint_id = finish.sprint_id and dev.bug_id = finish.bug_id
"""

# 生成各Sprint故障平均完成时长表数据
RDM_BUG_AVGTIME_SPRINT_SQL = """
insert into rdm_bug_avgtime_sprint
select
    project_id,
    project_name,
    sprint_id,
    sprint_name,
    short_sprint_name,
    sprint_seqno,
    dev_seconds_all,
    dev_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR((dev_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((dev_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) = 0
             AND FLOOR((dev_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) = 0
             AND FLOOR(((dev_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_str,
    test_seconds_all,
    test_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) = 0
             AND FLOOR((test_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((test_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) = 0
             AND FLOOR((test_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) = 0
             AND FLOOR(((test_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_str,
    finish_seconds_all,
    finish_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR((finish_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((finish_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) = 0
             AND FLOOR((finish_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) = 0
             AND FLOOR(((finish_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_str
from
(
    select
        project_id,
        project_name,
        sprint_id,
        sprint_name,
        short_sprint_name,
        sprint_seqno,
        FLOOR(avg(dev_seconds_all)) as dev_seconds_all,
        FLOOR(avg(dev_seconds)) as dev_seconds,
        FLOOR(avg(test_seconds_all)) as test_seconds_all,
        FLOOR(avg(test_seconds)) as test_seconds,
        FLOOR(avg(finish_seconds_all)) as finish_seconds_all,
        FLOOR(avg(finish_seconds)) as finish_seconds
    from rdm_bug_duration
    group by
        project_id,
        project_name,
        sprint_id,
        sprint_name,
        short_sprint_name,
        sprint_seqno
) t
"""

# 生成各开发人员的故障平均完成时长表的数据
RDM_BUG_AVGTIME_AUTHOR_SQL = """
insert into rdm_bug_avgtime_author
select
    project_id,
    project_name,
    sprint_id,
    sprint_name,
    short_sprint_name,
    sprint_seqno,
    author,
    bug_count,
    dev_seconds_all,
    dev_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR((dev_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((dev_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((dev_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((dev_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) = 0
             AND FLOOR((dev_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((dev_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((dev_seconds + 43200) / 86400) = 0
             AND FLOOR(((dev_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((dev_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS dev_time_str,
    test_seconds_all,
    test_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) = 0
             AND FLOOR((test_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((test_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((test_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((test_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) = 0
             AND FLOOR((test_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((test_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((test_seconds + 43200) / 86400) = 0
             AND FLOOR(((test_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((test_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS test_time_str,
    finish_seconds_all,
    finish_seconds,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish_seconds_all + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish_seconds_all + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR((finish_seconds_all + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish_seconds_all + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds_all + 43200) / 86400) = 0
             AND FLOOR(((finish_seconds_all + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish_seconds_all + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_all_str,
    CONCAT_WS('',
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR((finish_seconds + 43200) / 86400), '天')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) > 0
             THEN CONCAT(FLOOR(((finish_seconds + 1800) % 86400) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) = 0
             AND FLOOR((finish_seconds + 30) / 3600) > 0
             THEN CONCAT(FLOOR((finish_seconds + 30) / 3600), '小时')
             ELSE '' END,
        CASE WHEN FLOOR((finish_seconds + 43200) / 86400) = 0
             AND FLOOR(((finish_seconds + 30) % 3600) / 60) > 0
             THEN CONCAT(FLOOR(((finish_seconds + 30) % 3600) / 60), '分')
             ELSE '' END
    ) AS finish_time_str
from
(
    select
        project_id,
        project_name,
        sprint_id,
        sprint_name,
        short_sprint_name,
        sprint_seqno,
        author,
        count(1) as bug_count,
        FLOOR(avg(dev_seconds_all)) as dev_seconds_all,
        FLOOR(avg(dev_seconds)) as dev_seconds,
        FLOOR(avg(test_seconds_all)) as test_seconds_all,
        FLOOR(avg(test_seconds)) as test_seconds,
        FLOOR(avg(finish_seconds_all)) as finish_seconds_all,
        FLOOR(avg(finish_seconds)) as finish_seconds
    from rdm_bug_duration
    group by
        project_id,
        project_name,
        sprint_id,
        sprint_name,
        short_sprint_name,
        sprint_seqno,
        author
) t
"""
