"""当月签到奖励目录。

按活动号 + 东八区月份缓存 `luna/home` 奖池，全站共用，不跟角色走。
打开仪表盘只读这张表，避免把展示流量打进签到风控。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.database import Base
from app.utils.timezone import utc_now_naive


class CheckinRewardCatalog(Base):
    __tablename__ = "checkin_reward_catalogs"
    __table_args__ = (
        UniqueConstraint("act_id", "month", name="uq_checkin_reward_catalog_act_month"),
    )

    id = Column(Integer, primary_key=True, index=True)
    act_id = Column(String(64), nullable=False)
    game_family = Column(String(16), nullable=False)
    # 东八区 YYYY-MM，和签到“今天”使用同一套月份边界
    month = Column(String(7), nullable=False)
    awards_json = Column(Text, nullable=False)
    fetched_at = Column(DateTime, default=utc_now_naive, nullable=False)
