"""项目配置序列化:robot_key 脱敏口径。

口径(见 db/models.py 的 to_dict):
- 列表接口(默认 mask_robot_key=True)返回掩码,不泄露 webhook key;
- 详情接口(mask_robot_key=False)返回明文,供编辑表单回显 ——
  若这里也回掩码,前端保存时会把掩码写回库,真实 key 被覆盖。
"""

from db.models import ProjectConfig

PLAIN = "abcd-1234-5678-efgh"


def _cfg(robot_key: str = PLAIN) -> ProjectConfig:
    return ProjectConfig(
        board_id="1",
        board_name="b",
        project_id="P1",
        project_name="p",
        robot_key=robot_key,
    )


def test_list_masks_robot_key():
    data = _cfg().to_dict(include_token=False)
    masked = data["robot_key"]
    assert masked.startswith("abcd")
    assert masked.endswith("efgh")
    assert "****" in masked
    # 中间真实字符不得出现
    assert "1234" not in masked


def test_detail_keeps_plaintext():
    data = _cfg().to_dict(include_token=True, mask_robot_key=False)
    assert data["robot_key"] == PLAIN


def test_empty_robot_key_stays_empty():
    """空值原样返回,不能把「未配置」显示成掩码"""
    assert _cfg(robot_key="").to_dict()["robot_key"] == ""
