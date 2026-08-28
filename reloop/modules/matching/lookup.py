"""撞库查询(v2.1): 外部候选人信息 → 匹配本库人才(TTC 同步数据), 用于信息补充。

分层匹配策略(按置信度降序):
  1. contact_exact  手机/邮箱精确命中                        conf 0.98
  2. name_match     姓名精确(+公司/职位加权 0.92 / 无加权 0.78) conf 0.78~0.92
  3. name_fuzzy     姓名子串互含                             conf 0.62
  4. semantic       粘贴文本 vs resume_embedding 余弦          conf 0.50+0.45*cos

输入支持任意粘贴文本(自动提取手机/邮箱/姓名) + 可选结构化字段覆盖(结构化优先)。
全程只读, 不写库。
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from reloop.core.matching import cosine_similarity
from reloop.db.models import InteractionRecord, TalentProfile
from reloop.modules.profile.llm import llm_service

PHONE_RX = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CN_NAME_RX = re.compile(r"[\u4e00-\u9fa5]{2,4}")

# 姓名启发式提取的停用词(常见开场白/称谓, 避免把"您好"当姓名)
_NAME_STOPWORDS = {
    "你好", "您好", "候选人", "简历", "推荐", "请问", "感谢", "麻烦", "联系",
    "电话", "微信", "邮箱", "公司", "职位", "目前", "当前", "情况", "信息",
    "关于", "这个", "一个", "我们", "他们", "自己", "现在", "最近", "人才",
}

# 语义匹配最低余弦阈值(低于则不视为命中, 避免噪音)
_SEMANTIC_MIN_COS = 0.35
# 粘贴文本参与语义匹配的最小长度(过短没有语义信号)
_SEMANTIC_MIN_TEXT_LEN = 30


def parse_lookup_input(
    text: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    company: Optional[str] = None,
) -> dict:
    """解析撞库输入: 结构化字段优先, 缺口由粘贴文本自动提取补齐。"""
    text = (text or "").strip()
    resolved_phone = (phone or "").strip() or None
    resolved_email = (email or "").strip() or None
    resolved_name = (name or "").strip() or None
    resolved_company = (company or "").strip() or None

    if text:
        if not resolved_phone:
            m = PHONE_RX.search(text)
            if m:
                resolved_phone = m.group(0)
        if not resolved_email:
            m = EMAIL_RX.search(text)
            if m:
                resolved_email = m.group(0)
        if not resolved_name:
            # 姓名: 前 60 字内第一个 2-4 字中文词(排除停用词)
            for m in CN_NAME_RX.finditer(text[:60]):
                w = m.group(0)
                if w in _NAME_STOPWORDS:
                    continue
                resolved_name = w
                break

    return {
        "name": resolved_name,
        "phone": resolved_phone,
        "email": resolved_email,
        "company": resolved_company,
        "text": text,
    }


def lookup_talents(db: Session, owner_user_id: str, parsed: dict, limit: int = 5) -> tuple[list[dict], int]:
    """执行撞库: 返回 (hits, scanned)。hits 按 confidence 降序, 每项含全部备注。"""
    talents = (
        db.query(TalentProfile)
        .filter(TalentProfile.owner_user_id == owner_user_id)
        .all()
    )
    by_id = {t.id: t for t in talents}
    hits: dict[int, tuple[float, str]] = {}

    # ---- 1. 联系方式精确命中 ----
    if parsed["phone"] or parsed["email"]:
        for t in talents:
            if parsed["phone"] and t.contact_phone and parsed["phone"] in t.contact_phone:
                hits[t.id] = (0.98, "contact_exact")
            elif parsed["email"] and t.contact_email and parsed["email"].lower() == t.contact_email.lower():
                hits[t.id] = (0.98, "contact_exact")

    # ---- 2. 姓名匹配(精确 + 公司加权 / 子串模糊) ----
    if parsed["name"]:
        for t in talents:
            if t.id in hits or not t.name:
                continue
            if t.name == parsed["name"]:
                conf = 0.78
                if parsed["company"] and t.company and (
                    parsed["company"] in t.company or t.company in parsed["company"]
                ):
                    conf = 0.92
                hits[t.id] = (conf, "name_match")
            elif parsed["name"] in t.name:
                hits.setdefault(t.id, (0.62, "name_fuzzy"))

    # ---- 3. 语义匹配(粘贴文本 vs 人才画像向量) ----
    if parsed["text"] and len(parsed["text"]) >= _SEMANTIC_MIN_TEXT_LEN:
        try:
            vec, _source = llm_service.embed_with_source(parsed["text"][:2000])
        except Exception:  # LLM 熔断/离线时 embed 自身会降级, 这里再兜一层
            vec = None
        if vec:
            for t in talents:
                if t.id in hits or not t.resume_embedding:
                    continue
                cos = cosine_similarity(vec, t.resume_embedding)
                if cos is not None and cos >= _SEMANTIC_MIN_COS:
                    conf = round(0.5 + 0.45 * cos, 4)
                    hits[t.id] = (conf, "semantic")

    # ---- 组装结果(按置信度降序) ----
    ordered = sorted(hits.items(), key=lambda kv: -kv[1][0])[:limit]
    result: list[dict] = []
    for talent_id, (conf, match_type) in ordered:
        t = by_id[talent_id]
        interactions = (
            db.query(InteractionRecord)
            .filter(
                InteractionRecord.owner_user_id == owner_user_id,
                InteractionRecord.talent_id == talent_id,
            )
            .order_by(InteractionRecord.occurred_at.desc())
            .limit(10)
            .all()
        )
        result.append(
            {
                "talent_id": t.id,
                "source_id": t.source_id,
                "name": t.name,
                "company": t.company,
                "position": t.position,
                "seek_status": t.seek_status,
                "contact_phone": t.contact_phone,
                "match_type": match_type,
                "confidence": conf,
                "notes": t.notes,
                "interactions": [
                    {
                        "interaction_type": i.interaction_type,
                        "summary": i.summary,
                        "occurred_at": i.occurred_at,
                    }
                    for i in interactions
                ],
            }
        )
    return result, len(talents)
