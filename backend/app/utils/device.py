"""
设备信息生成工具

米游社的签到接口不只看 Cookie，还会同时校验设备标识、设备指纹和移动端 UA。
如果这里仍沿用“每次都随机 device_fp / 固定 hk4e signgame”这类宽松实现，
就会出现原神偶尔可用、星穹铁道稳定失败的误导性症状。
"""

import json
import uuid
import random
import hashlib
import time

from app.config import settings


HYPERION_APP_VERSION = "2.90.1"
HYPERION_SIGN_SALT = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"
DEVICE_FP_URL = "https://public-data-api.mihoyo.com/device-fp/api/getFp"


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


def build_hyperion_user_agent(app_version: str = HYPERION_APP_VERSION) -> str:
    """对齐米游社移动端 WebView 的 UA 形式。"""
    return (
        "Mozilla/5.0 (Linux; Android 13; Pixel 5 Build/TQ3A.230901.001; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/118.0.0.0 "
        f"Mobile Safari/537.36 miHoYoBBS/{app_version}"
    )


def build_hyperion_headers(
    cookie: str,
    *,
    device_id: str,
    device_fp: str,
    ds: str = "",
    sign_game: str | None = None,
    app_version: str = HYPERION_APP_VERSION,
) -> dict:
    """
    构造对齐 Hyperion/Starward 的请求头。

    签到链路的几个核心字段必须一起出现：
    - app_version / client_type / device_id / device_fp
    - 移动端 WebView User-Agent
    - 对应游戏的 x-rpc-signgame

    若把这些字段拆散为多个“可选优化项”，后续维护时很容易删掉其中一个，
    结果就是只在部分游戏上出现隐蔽失败。
    """
    headers = {
        "User-Agent": build_hyperion_user_agent(app_version),
        "Referer": "https://act.mihoyo.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://act.mihoyo.com",
        "x-rpc-app_version": app_version,
        "x-rpc-client_type": "5",
        "x-rpc-device_id": device_id,
        "x-rpc-device_fp": device_fp,
    }

    if cookie:
        headers["Cookie"] = cookie

    if ds:
        headers["DS"] = ds
    if sign_game:
        headers["x-rpc-signgame"] = sign_game

    return headers


def build_genshin_authkey_headers(
    cookie: str,
    *,
    device_id: str,
    ds: str,
    app_version: str = HYPERION_APP_VERSION,
) -> dict[str, str]:
    """
    构造原神 authkey（LK2）请求头。

    这里必须强制带齐 DS、device_id 与 `Referer=https://app.mihoyo.com`。
    若误回退到“只带工作 Cookie 的旧 GET 习惯”，接口通常不会给出直观错误，排障会被噪音淹没。
    """
    return {
        "Accept": "application/json",
        "User-Agent": build_hyperion_user_agent(app_version),
        "Referer": "https://app.mihoyo.com",
        "x-rpc-app_version": app_version,
        "x-rpc-client_type": "5",
        "x-rpc-device_id": device_id,
        "DS": ds,
        "Cookie": cookie,
    }


def build_device_fp_payload(device_id: str, device_fp: str) -> dict:
    """
    构造设备指纹请求体。

    这里沿用 Starward 同类字段集，目的是让服务端看到一组稳定、像真实客户端的设备画像。
    如果随意删字段，短期内可能“偶尔还能用”，但会让后续风控问题极难排查。
    """
    product_name = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    seed_id = hashlib.md5(f"{uuid.uuid4()}-{random.random()}".encode("utf-8")).hexdigest()[:16]
    return {
        "device_id": seed_id,
        "seed_id": str(uuid.uuid4()),
        "seed_time": str(int(time.time() * 1000)),
        "platform": "2",
        "device_fp": device_fp,
        "app_name": "bbs_cn",
        "ext_fields": json.dumps({
            "proxyStatus": 0,
            "isRoot": 0,
            "romCapacity": "512",
            "deviceName": "Pixel5",
            "productName": product_name,
            "romRemain": "512",
            "hostname": "db1ba5f7c000000",
            "screenSize": "1080x2400",
            "isTablet": 0,
            "aaid": "",
            "model": "Pixel5",
            "brand": "google",
            "hardware": "windows_x86_64",
            "deviceType": "redfin",
            "devId": "REL",
            "serialNumber": "unknown",
            "sdCapacity": 125943,
            "buildTime": "1704316741000",
            "buildUser": "cloudtest",
            "simState": 0,
            "ramRemain": "124603",
            "appUpdateTimeDiff": 1716369357492,
            "deviceInfo": f"google/{product_name}/redfin:13/TQ3A.230901.001/2311.40000.5.0:user/release-keys",
            "vaid": "",
            "buildType": "user",
            "sdkVersion": "33",
            "ui_mode": "UI_MODE_TYPE_NORMAL",
            "isMockLocation": 0,
            "cpuType": "arm64-v8a",
            "isAirMode": 0,
            "ringMode": 2,
            "chargeStatus": 3,
            "manufacturer": "Google",
            "emulatorStatus": 0,
            "appMemory": "512",
            "osVersion": "13",
            "vendor": "unknown",
            "accelerometer": "",
            "sdRemain": 123276,
            "buildTags": "release-keys",
            "packageName": "com.mihoyo.hyperion",
            "networkType": "WiFi",
            "oaid": "",
            "debugStatus": 1,
            "ramCapacity": "125943",
            "magnetometer": "",
            "display": "TQ3A.230901.001",
            "appInstallTimeDiff": 1706444666737,
            "packageVersion": "2.20.2",
            "gyroscope": "",
            "batteryStatus": 85,
            "hasKeyboard": 10,
            "board": "windows",
        }, separators=(",", ":")),
        "bbs_device_id": device_id,
    }


def get_default_headers(cookie: str, device_id: str = "", ds: str = "") -> dict:
    """
    兼容旧调用入口。

    旧逻辑仍会为非签到链路生成一组可用的默认头，但签到流程必须显式调用
    `build_hyperion_headers` 传入稳定的 `device_fp` 和按游戏区分的 `sign_game`。
    """
    if not device_id:
        device_id = generate_device_id()

    return build_hyperion_headers(
        cookie,
        device_id=device_id,
        device_fp=generate_device_fp(),
        ds=ds,
        app_version=settings.MIHOYO_APP_VERSION,
    )
