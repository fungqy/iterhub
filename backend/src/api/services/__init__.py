"""API 服务层

放置各类业务/数据访问逻辑,由 api/scheduler.py、routes/* 调用。
api/scheduler.py 保持为编排层,并对本节中的叶子函数做 re-export,
以维持既有 import 与测试打桩 (patch) 路径不变。
"""
