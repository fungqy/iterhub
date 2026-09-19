"""classify_error 单元测试"""

from unittest.mock import MagicMock

import requests

from util.errors import classify_error

# 真实生产中 requests.ConnectionError 的 str 格式,直接构造与日志一致
DNS_ERR_STR = (
    "HTTPConnectionPool(host='rdm.zvos.zoomlion.com', port=80): "
    "Max retries exceeded with url: /rest/agile/1.0/board/1044/sprint?state=active "
    "(Caused by NameResolutionError(\"<urllib3.connection.HTTPConnection object>: "
    "Failed to resolve 'rdm.zvos.zoomlion.com' "
    "([Errno -2] Name or service not known)\"))"
)


def test_connection_error_dns_failure_returns_502_with_host():
    """对应用户实际遇到的场景:DNS 解析失败"""
    err = requests.exceptions.ConnectionError(DNS_ERR_STR)

    status, msg = classify_error(err)

    assert status == 502
    assert "rdm.zvos.zoomlion.com" in msg
    assert "无法解析域名" in msg
    # 不应包含原始 traceback 或内部对象地址
    assert "Traceback" not in msg
    assert "0x" not in msg


def test_connection_error_connection_refused():
    err = requests.exceptions.ConnectionError(
        "HTTPConnectionPool(host='jira.example.com', port=80): Max retries exceeded "
        "(Caused by NewConnectionError('<urllib3.connection.HTTPConnection object>: "
        "Failed to establish a new connection: [Errno 111] Connection refused'))"
    )
    status, msg = classify_error(err)
    assert status == 502
    assert "jira.example.com" in msg
    assert "连接被拒绝" in msg


def test_timeout_returns_504():
    err = requests.exceptions.Timeout("read timed out")
    status, msg = classify_error(err)
    assert status == 504
    assert "超时" in msg


def test_http_error_5xx():
    response = MagicMock()
    response.status_code = 502
    response.text = "Bad Gateway"
    err = requests.exceptions.HTTPError(response=response)
    status, msg = classify_error(err)
    assert status == 502
    assert "502" in msg
    assert "Bad Gateway" in msg


def test_http_error_no_response():
    err = requests.exceptions.HTTPError("internal")
    status, msg = classify_error(err)
    assert status == 502
    assert "HTTP ?" in msg


def test_ssl_error():
    err = requests.exceptions.SSLError("certificate verify failed")
    status, msg = classify_error(err)
    assert status == 502
    assert "SSL" in msg


def test_generic_request_exception():
    err = requests.exceptions.RequestException("weird thing")
    status, msg = classify_error(err)
    assert status == 502
    assert "weird thing" in msg


def test_unexpected_exception_returns_500_with_type():
    err = ValueError("some validation failure")
    status, msg = classify_error(err)
    assert status == 500
    assert "ValueError" in msg
    assert "some validation failure" in msg


def test_long_message_truncated_to_200():
    err = ValueError("x" * 500)
    status, msg = classify_error(err)
    assert status == 500
    assert len(msg) <= 250  # "ValueError: " 前缀 + 200 字符


def test_empty_message_does_not_crash():
    err = ValueError("")
    status, msg = classify_error(err)
    assert status == 500
    assert "ValueError" in msg
    assert "无详细信息" in msg


def test_no_host_in_message_uses_generic_target():
    err = requests.exceptions.ConnectionError("some other error")
    status, msg = classify_error(err)
    assert status == 502
    assert "目标服务" in msg
