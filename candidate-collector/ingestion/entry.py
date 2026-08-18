"""统一写入口（DATA_GOVERNANCE §2 目标架构的唯一入口）。

所有来源（pipeline / 浏览器插件 gateway / MCP 手动 / app.py capture）的候选人
写入都收敛到这里：

    CandidateRecord → QualityGate（4 要素随行进库，R6）
                    → FingerprintService（唯一算法 sha256(fingerprint_input())，R5）
                    → CloudWriter（唯一写入口；失败抛出 + 告警，R7）

飞书投影不在此入口内：pipeline 由 DeliveryWorker 编排（已是云先飞书后），
其余来源暂不投飞书。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from cloud_sync.client import CloudSyncClient
from cloud_sync.transform import candidate_record_to_cloud
from quality import evaluate_quality

logger = logging.getLogger(__name__)


@dataclass
class EntryResult:
    """统一入口的返回契约。"""

    fingerprint: str
    quality_score: float
    missing_fields: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    cloud_record_id: int | None = None

    @property
    def action(self) -> str:
        return "created" if self.stats.get("inserted") else "updated"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "quality_score": self.quality_score,
            "missing_fields": self.missing_fields,
            "stats": self.stats,
            "cloud_record_id": self.cloud_record_id,
            "action": self.action,
        }


def ingest_record(
    record: Any,
    *,
    client: CloudSyncClient | None = None,
    actor_user_id: int | None = None,
    read_back: bool = True,
) -> EntryResult:
    """校验 → 质量打分 → 统一指纹 → 写云。

    Args:
        record: models.CandidateRecord（其余类型会在 transform 层被拒绝/降级）。
        client: 可注入的 CloudSyncClient（测试用）。
        actor_user_id: 插件采集时的首采人 id。
        read_back: 写后回读取 cloud_record_id（gateway 需要；批量场景可关）。

    Returns:
        EntryResult（fingerprint / quality_score / missing_fields / stats / cloud_record_id）

    Raises:
        cloud_sync.client.UpsertError: 任何写库失败（R7：不得静默吞）。
    """
    quality_score, missing_fields = evaluate_quality(record)

    row = candidate_record_to_cloud(record)
    row["quality_score"] = quality_score
    row["missing_fields"] = json.dumps(missing_fields, ensure_ascii=False)
    if actor_user_id is not None:
        row["first_collected_by_user_id"] = actor_user_id

    cloud = client or CloudSyncClient()
    stats = cloud.upsert_candidates([row])

    cloud_record_id: int | None = None
    if read_back:
        stored = cloud.get_candidate(row["fingerprint"])
        if not stored:
            raise RuntimeError("云数据库写入后未能回读记录")
        cloud_record_id = stored.get("id")

    return EntryResult(
        fingerprint=row["fingerprint"],
        quality_score=quality_score,
        missing_fields=missing_fields,
        stats=stats,
        cloud_record_id=cloud_record_id,
    )
