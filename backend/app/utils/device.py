"""
设备信息生成工具
米游社 API 检查设备信息以防止自动化，需要模拟真实设备
"""

import uuid
import random
import hashlib


def generate_device_id() -> str:
    """生成随机设备 UUID"""
    return str(uuid.uuid4())


def generate_device_fp() -> str:
    """
    生成设备指纹
    格式：10 位十六进制字符串
    实际客户端通过采集硬件信息生成，这里用随机值模拟
    """
    seed = str(uuid.uuid4()) + str(random.random())
    return hashlib.md5(seed.encode()).hexdigest()[:10]


def get_default_headers(cookie: str, device_id: str = "", ds: str = "") -> dict:
    """
    构造米游社 API 请求所需的完整请求头
    这些字段缺一不可，否则会被服务端拒绝
    """
    from app.config import settings

    if not device_id:
        device_id = generate_device_id()

    headers = {
        "User-Agent": (
            f"Mozilla/5.0 (Linux; Android 12; SM-G9880) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/107.0.0.0 Mobile Safari/537.36 "
            f"miHoYoBBS/{settings.MIHOYO_APP_VERSION}"
        ),
        "Referer": "https://act.mihoyo.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://act.mihoyo.com",
        "x-rpc-app_version": settings.MIHOYO_APP_VERSION,
        "x-rpc-client_type": settings.MIHOYO_CLIENT_TYPE,
        "x-rpc-device_id": device_id,
        "x-rpc-device_fp": generate_device_fp(),
        "x-rpc-signgame": "hk4e",
        "Cookie": cookie,
    }

    if ds:
        headers["DS"] = ds

    return headers
