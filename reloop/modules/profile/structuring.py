"""人才画像结构化: 标准格式 + LLM 增强 -> 统一人才画像库 (RDS MySQL)。

输入:
  - sync 模块归一化出的标准 dict (规则抽取, 必有)
  - LLM 增强抽取(可选: company_tier / tendency_score / 更完整的 skills)
输出:
  - talent_profiles 行: 补齐 value_score(人才价值静态分) + resume_embedding(向量)

设计: 规则优先、LLM 增强——LLM 不可用时整条流程仍可跑通。
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from reloop.db.models import TalentProfile
from reloop.modules.profile.llm import llm_service
from reloop.modules.scoring.factors import normalize_value, raw_value_score

logger = logging.getLogger(__name__)


class StructuringService:
    """标准格式 -> 增强提取 -> 计算派生分 -> 落库。"""

    def enrich_and_save(
        self,
        db: Session,
        owner_user_id: str,
        talent: dict,
        source_id: Optional[str] = None,
        commit: bool = True,
    ) -> TalentProfile:
        """talent: normalizer 输出的标准结构化 dict。

        commit=True: 单条落库场景, 立即提交并 refresh(拿到自增 id)。
        commit=False: 批量同步场景, 只 flush(同会话内可见、拿到 id),
                      由外层统一 commit, 避免逐条提交的性能损耗与事务边界混乱。
        """
        text = talent.get("summary") or ""

        # ---- 1. LLM 增强(可选): 抽取 company_tier / tendency / 补充技能 ----
        extra = llm_service.structure_talent(text) if text else {}
        company_tier = extra.get("company_tier") or "一般"
        skills = talent.get("skills") or []
        extra_skills = extra.get("skills") or []
        if isinstance(extra_skills, list):
            skills = list(dict.fromkeys(skills + [str(s) for s in extra_skills]))

        # ---- 2. 人才价值静态分 (公司等级+学历+稀缺技能 -> [0,1]) ----
        raw_val = raw_value_score(
            company_tier=str(company_tier),
            education=talent.get("education") or "本科",
            skills=skills,
        )
        value = normalize_value(raw_val)

        # ---- 3. 求职倾向 (LLM, 离线为 None -> 后续按中性 0.5 处理) ----
        tendency = extra.get("tendency_score")
        try:
            tendency = float(tendency) if tendency is not None else None
        except (TypeError, ValueError):
            tendency = None

        # ---- 4. 画像文本向量 (真实接口或本地哈希兜底) ----
        embedding = llm_service.embed(text)

        # ---- 5. 落库 (owner 隔离; source_id 去重 upsert) ----
        sid = source_id or talent.get("source_id") or None
        existing = None
        if sid:
            existing = (
                db.query(TalentProfile)
                .filter(
                    TalentProfile.owner_user_id == owner_user_id,
                    TalentProfile.source_id == sid,
                )
                .first()
            )

        fields = dict(
            name=talent.get("name") or "未知",
            base_location=talent.get("base_location"),
            company=talent.get("company"),
            position=talent.get("position"),
            work_years=talent.get("work_years"),
            education=talent.get("education"),
            skills=skills,
            resume_text=text,
            resume_embedding=embedding,
            value_score=value,
            tendency_score=tendency,
            last_active_at=talent.get("last_active_at"),
            tags=talent.get("tags") or [],
            source_payload=talent.get("raw"),
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            profile = existing
        else:
            profile = TalentProfile(owner_user_id=owner_user_id, source_id=sid, **fields)
            db.add(profile)

        db.commit()
        db.refresh(profile)
        logger.info("[structure] saved talent id=%s owner=%s", profile.id, owner_user_id)
        return profile


structuring_service = StructuringService()
