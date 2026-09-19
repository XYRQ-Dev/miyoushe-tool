"""
签到响应里的极验 / 风控识别。

只负责从 luna/sign 响应判断“这次是不是风控”，不求解验证码，也不改请求头。
识别规则必须收口在这里：若继续散落在 `_do_sign()` 的 if 里，上游一换字段就会重新变成泛化失败。
"""

from dataclasses import dataclass
from typing import Any, Literal

# genshin.py 把这组码视为极验。签到主路径通常仍是 retcode=0 加 data 字段，
# 这里只作兜底，避免 1034 一类码再被打成普通失败。
# 不含 5003：那是战绩接口的极验码，且不能和签到已签到的 -5003 混淆。
GEETEST_RETCODES = {1034, 10035, 10041}

GEETEST_RISK_MESSAGE = "命中风控验证，请稍后重试或前往米游社补签"
GENERIC_RISK_MESSAGE = "命中风控，但未返回验证参数"


@dataclass(frozen=True)
class CheckinRiskInfo:
    kind: Literal["geetest", "risk"]
    has_gt: bool
    has_challenge: bool
    risk_code: int | None
    retcode: int

    @property
    def message(self) -> str:
        if self.kind == "geetest":
            return GEETEST_RISK_MESSAGE
        return GENERIC_RISK_MESSAGE


def _has_token(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def _parse_retcode(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("retcode", -1))
    except (TypeError, ValueError):
        return -1


def _parse_risk_code(data: dict[str, Any]) -> int | None:
    raw = data.get("risk_code")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def parse_checkin_risk(payload: dict[str, Any] | None) -> CheckinRiskInfo | None:
    """
    从签到响应抽出风控结论。

    判定顺序：
    1. -5003 仍是今日已签到，即使 data 里带着风控痕迹也不当极验
    2. 非空 gt / challenge → 极验
    3. is_risk / success==1 / risk_code 非 0，但没有极验参数 → 不可解风控
    4. 顶层 retcode 落在已知极验码 → 极验兜底
    """
    if not isinstance(payload, dict):
        return None

    retcode = _parse_retcode(payload)
    if retcode == -5003:
        return None

    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    has_gt = _has_token(data.get("gt"))
    has_challenge = _has_token(data.get("challenge"))
    risk_code = _parse_risk_code(data)

    if has_gt or has_challenge:
        return CheckinRiskInfo(
            kind="geetest",
            has_gt=has_gt,
            has_challenge=has_challenge,
            risk_code=risk_code,
            retcode=retcode,
        )

    is_risk = bool(data.get("is_risk"))
    # MihoyoBBSTools：success==1 表示要验证码，success==0 才是签到成功。
    if is_risk or data.get("success") == 1 or (risk_code is not None and risk_code != 0):
        return CheckinRiskInfo(
            kind="risk",
            has_gt=False,
            has_challenge=False,
            risk_code=risk_code,
            retcode=retcode,
        )

    if retcode in GEETEST_RETCODES:
        return CheckinRiskInfo(
            kind="geetest",
            has_gt=False,
            has_challenge=False,
            risk_code=risk_code,
            retcode=retcode,
        )

    return None
