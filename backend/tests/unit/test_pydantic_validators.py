"""ProjectReminderSettingsCreate 的 HH:MM 校验"""

import pytest
from pydantic import ValidationError

from api.routes.projects import ProjectReminderSettingsCreate


def test_valid_times_accepted():
    obj = ProjectReminderSettingsCreate(
        story_remind_time="09:00",
        task_remind_time="18:30",
        sonar_remind_time="23:59",
    )
    assert obj.story_remind_time == "09:00"
    assert obj.task_remind_time == "18:30"
    assert obj.sonar_remind_time == "23:59"


def test_none_and_empty_allowed():
    obj1 = ProjectReminderSettingsCreate(story_remind_time=None)
    obj2 = ProjectReminderSettingsCreate(story_remind_time="")
    assert obj1.story_remind_time is None
    assert obj2.story_remind_time == ""


@pytest.mark.parametrize(
    "bad",
    [
        "25:00",        # hour > 23
        "09:60",        # minute > 59
        "9:30",         # 单位数小时
        "0930",         # 缺冒号
        "09:3",         # 单位数分钟
        "abc",
        "09:30:00",     # 带秒
    ],
)
def test_invalid_time_rejected(bad):
    with pytest.raises(ValidationError):
        ProjectReminderSettingsCreate(story_remind_time=bad)
