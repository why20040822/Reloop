"""两阶段推荐引擎入口(转发壳, 蓝图 R1 2026-08-28)。

实现已原样搬迁至 `reloop/services/recommend_service.py`(纯搬运, 行为不变);
本文件仅为兼容旧 import 路径保留转发。新代码请直接 import services 层。
"""

from reloop.services.recommend_service import (  # noqa: F401
    DEFAULT_TOP_SIZES,
    RecommendEngine,
    recommend_engine,
)

__all__ = ["DEFAULT_TOP_SIZES", "RecommendEngine", "recommend_engine"]
