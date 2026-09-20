import json
import logging
import os

import requests

logger = logging.getLogger("QyWx")

# 企微推送总开关
# - PUSH_ENABLED=true  (或 1/yes) : 真实推送到企微群
# - PUSH_ENABLED=false (或 0/no，默认) : 仅记录日志，不推送（开发环境使用）
# 修改 backend/.env 中的 PUSH_ENABLED 即可切换
PUSH_ENABLED = os.getenv("PUSH_ENABLED", "false").strip().lower() in (
    "true",
    "1",
    "yes",
)


def mask_key(robot_key: str) -> str:
    """对 robot_key 做脱敏(日志与对外接口共用),避免泄露完整 webhook"""
    if not robot_key:
        return "<empty>"
    if len(robot_key) <= 8:
        return "***"
    return f"{robot_key[:4]}****{robot_key[-4:]}"


def post(robot_key: str, message: str | None = None) -> None:
    """实际发送企业微信群通知（请通过 send_or_log 调用）"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={robot_key}"
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"msgtype": "markdown", "markdown": {"content": message}},
            timeout=10,
        )
        body = json.loads(response.content.decode("utf-8"))
        if response.status_code == 200 and body.get("errcode") == 0:
            logger.info("企微消息已发送")
        else:
            logger.error(f"企微消息发送失败: {body.get('errmsg')}")
    except Exception as e:
        logger.error(f"企微消息发送异常: {e}")


def send_or_log(robot_key: str, message: str | None) -> None:
    """根据 PUSH_ENABLED 开关决定真实推送还是仅记录日志

    - PUSH_ENABLED=true ：调用企微 webhook 真实发送
    - PUSH_ENABLED=false（默认）：仅将消息内容写入日志，不打扰企微群
    """
    if not message:
        return
    if PUSH_ENABLED:
        post(robot_key, message)
    else:
        logger.info(
            f"[PUSH_DISABLED] 已生成企微消息（未发送） "
            f"robot_key={mask_key(robot_key)} "
            f"message=\n{message}"
        )


if __name__ == "__main__":
    # 直接运行本文件时使用 send_or_log，避免开发期间误发
    send_or_log("test-webhook-key", "## 测试消息\n这是一条测试")
