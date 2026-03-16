"""
Cookie 加密工具
使用 AES-256-GCM 对称加密，确保 Cookie 在数据库中不明文存储
GCM 模式同时提供加密和完整性验证
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _get_key() -> bytes:
    """从配置中获取 AES 密钥，确保正好 32 字节"""
    raw = settings.ENCRYPTION_KEY.encode("utf-8")
    # 取前 32 字节，不足则用 SHA-256 派生
    if len(raw) >= 32:
        return raw[:32]
    import hashlib
    return hashlib.sha256(raw).digest()


def encrypt_cookie(plaintext: str) -> str:
    """
    加密 Cookie 字符串
    返回格式：base64(nonce + ciphertext)
    nonce 固定 12 字节，拼接在密文前方便解密时拆分
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_cookie(encrypted: str) -> str:
    """
    解密 Cookie 字符串
    拆分 nonce（前 12 字节）和密文
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted)
    nonce = raw[:12]
    ciphertext = raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
