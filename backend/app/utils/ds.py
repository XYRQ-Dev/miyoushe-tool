"""
DS 动态签名生成

当前保留两种签名：
1. generate_ds：旧版通用实现，供现有非签到链路继续使用
2. generate_cn_dynamic_secret：对齐 Starward 的 Hyperion / 米游社国服签到实现

两者虽然都叫 DS，但随机串规则和盐值并不完全相同。签到链路若误用旧实现，
最容易出现的现象就是“参数看起来齐全，但星穹铁道查询状态始终失败”。
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


def generate_cn_dynamic_secret(salt: str) -> str:
    """
    生成与 Starward `CreateSecret()` 等价的国服签到 DS。

    这里不能复用旧的 `generate_ds`，因为 Starward 使用的是：
    - 6 位小写字母/数字随机串
    - 仅参与 `salt/t/r`
    - 不拼接 body/query

    对签到接口来说，这个差异会直接影响服务端校验结果。
    """
    t = int(time.time())
    seeded = random.Random(t)
    chars = []
    for _ in range(6):
        value = seeded.randint(0, 32767) % 26
        chars.append(chr(value + (48 if value < 10 else 87)))
    r = "".join(chars)
    text = f"salt={salt}&t={t}&r={r}"
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
