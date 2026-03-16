"""
DS 动态签名生成
米游社 API 需要在请求头中携带 DS 签名防止接口滥用
签名算法：MD5(salt={salt}&t={timestamp}&r={random}&b={body}&q={query})
"""

import hashlib
import random
import string
import time

from app.config import settings


def generate_ds(body: str = "", query: str = "") -> str:
    """
    生成 DS 动态签名
    - salt：硬编码在客户端中的固定盐值（随版本更新）
    - t：当前时间戳（秒）
    - r：6 位随机字符串
    - b：POST 请求体（GET 请求为空）
    - q：GET 请求的 query string（POST 请求为空）
    返回格式：{timestamp},{random},{md5_hash}
    """
    salt = settings.MIHOYO_SALT
    t = int(time.time())
    r = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    text = f"salt={salt}&t={t}&r={r}&b={body}&q={query}"
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{t},{r},{md5}"


def generate_ds_v2(body: str = "", query: str = "") -> str:
    """
    DS v2 签名（部分新接口使用）
    salt 不同，其余逻辑一致
    """
    salt = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
    t = int(time.time())
    r = str(random.randint(100001, 200000))
    text = f"salt={salt}&t={t}&r={r}&b={body}&q={query}"
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{t},{r},{md5}"
