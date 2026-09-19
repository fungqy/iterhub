"""验证 get_current_user_from_header 已去重,只有 api.auth 一份定义。"""

import pathlib


def test_only_one_definition_exists():
    """扫描 backend/src,确保只有 api.auth 里定义了一次。"""
    src_root = pathlib.Path(__file__).resolve().parents[2] / "src"
    hits = []
    for py in src_root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if "def get_current_user_from_header" in text:
            # 统一成 POSIX 风格:Windows 下 relative_to 给出的是 "api\auth.py",
            # 断言里写死分隔符会让用例与平台绑定(跨平台开发/CI 必现失败)。
            hits.append(py.relative_to(src_root).as_posix())

    assert hits == ["api/auth.py"], f"存在重复定义: {hits}"


def test_routes_import_from_api_auth():
    """所有路由文件都应 from api.auth import get_current_user_from_header。"""
    routes_dir = pathlib.Path(__file__).resolve().parents[2] / "src" / "api" / "routes"
    for py in routes_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "Depends(get_current_user_from_header)" not in text:
            continue  # 没用鉴权的路由文件跳过
        assert (
            "from api.auth import get_current_user_from_header" in text
            or "from api.auth import" in text and "get_current_user_from_header" in text
        ), f"{py.name} 用了 Depends(get_current_user_from_header) 但未从 api.auth 导入"
