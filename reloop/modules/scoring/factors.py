"""触达优先级五因子量化算法。

公式: 触达优先级 = 活跃度 × 岗位匹配度 × 人才价值 × 历史关系 × 求职可能性
每个因子归一化到 [0,1], 再进入加权乘法模型(见 priority.py)。

外部活跃信号(飞书在线/简历平台浏览等)已移除——
活跃度因子现在只来自两类站内可得信号:
  1. TTC 平台上人才的最近活跃/更新时间 (talent_profiles.last_active_at)
  2. 顾问在 Reloop 内与人才的互动记录 (interaction_records)

MVP v2 升级(2026-08):
  活跃度: 分事件半衰期冷却 + 绝对/相对混合归一化(单人池不退化, 死池不虚高)
  匹配度: 结构化多维(职位/技能/年限/学历) + 语义余弦加权融合, 离线可用
"""

import datetime as dt
import math
from typing import Iterable, Optional, Sequence

from reloop.config import settings


# =====================================================================
# 因子 1: 活跃度 —— 分事件半衰期的牛顿冷却 + 绝对/相对混合归一化 (v2)
#
#   原始分: Score = Σ( 事件权重 * e^(-λ_t * 距今天数) )
#     λ_t = ln2 / half_life_t, 每类事件有独立半衰期:
#       - "正在看机会"信号(平台活跃/档案更新)时效短 -> 半衰期小, 衰减快
#       - 关系维护信号(通话/消息/面试)时效长     -> 半衰期大, 衰减慢
#
#   归一化(v2): activity = α·绝对分 + (1-α)·相对分
#     绝对分 = 最近一次事件距今天数映射(0天=1, 180天+=floor), 衡量"到底活不活跃"
#     相对分 = 批内 min-max(冷却原始分), 保留同批次区分度
#     混合解决旧版两个失真: 单人池 min-max 退化; 全员死池被强行拉开区分度
# =====================================================================
EVENT_WEIGHTS = {
    "platform_active": 6.0,   # TTC 平台最近活跃
    "profile_update": 10.0,   # 档案/简历更新
    "interview": 8.0,         # 站内记录的面试互动
    "call": 5.0,              # 站内记录的通话互动
    "message": 2.0,           # 站内记录的消息互动
}

# 各事件类型的半衰期(天): 冷却到一半权重所需时间
EVENT_HALF_LIVES = {
    "platform_active": 14.0,  # 平台活跃是短期强信号
    "profile_update": 21.0,   # 档案更新热度中等
    "interview": 30.0,        # 面试关系信号较持久
    "call": 45.0,             # 通话维护的关系更持久
    "message": 45.0,          # 消息同上
}
DEFAULT_HALF_LIFE = 45.0      # 未知事件类型的默认半衰期

# 绝对活跃窗口: 最近一次事件距今超过该天数, 绝对分触底(floor)
ACTIVITY_ABS_WINDOW = 180.0

# 批量归一化因子的下限(活跃度/历史关系), 防止小样本下乘法模型误杀
FACTOR_FLOOR = 0.05


def activity_score(events: Iterable[dict], now: Optional[dt.datetime] = None,
                   decay: Optional[float] = None) -> float:
    """计算单人才的原始活跃度(冷却前)。

    events: [{"event_type": "profile_update", "weight": 10(可选),
              "occurred_at": datetime}, ...]
    返回原始分(未归一化); 调用方对一批人才做混合归一化。

    decay: 显式传入时沿用旧版统一衰减率(兼容); 缺省走分事件半衰期。
    """
    if now is None:
        # 统一时间基准为 UTC(naive), 与落库的 UTC 时间对齐, 消除本地/UTC 混用的 8 小时误差
        now = _utcnow_naive()
    else:
        now = _to_naive_utc(now)

    total = 0.0
    for ev in events:
        etype = ev.get("event_type", "")
        w = ev.get("weight") or EVENT_WEIGHTS.get(etype, 1.0)
        occurred = ev.get("occurred_at")
        if occurred is None:
            continue
        if isinstance(occurred, str):
            occurred = dt.datetime.fromisoformat(occurred)
        occurred = _to_naive_utc(occurred)
        days = max((now - occurred).total_seconds() / 86400.0, 0.0)
        if decay is not None:
            lam = decay
        else:
            lam = math.log(2.0) / EVENT_HALF_LIVES.get(etype, DEFAULT_HALF_LIFE)
        total += w * math.exp(-lam * days)
    return total


def days_since_latest_event(events: Iterable[dict],
                            now: Optional[dt.datetime] = None) -> Optional[float]:
    """最近一次事件距今几天; 无任何事件返回 None(绝对分触底)。"""
    if now is None:
        now = _utcnow_naive()
    else:
        now = _to_naive_utc(now)
    latest: Optional[dt.datetime] = None
    for ev in events:
        occurred = ev.get("occurred_at")
        if occurred is None:
            continue
        if isinstance(occurred, str):
            occurred = dt.datetime.fromisoformat(occurred)
        occurred = _to_naive_utc(occurred)
        if latest is None or occurred > latest:
            latest = occurred
    if latest is None:
        return None
    return max((now - latest).total_seconds() / 86400.0, 0.0)


def absolute_activity(days_since_latest: Optional[float],
                      window: float = ACTIVITY_ABS_WINDOW) -> float:
    """绝对活跃分 ∈ [FACTOR_FLOOR,1]: 只看最近一次事件有多新。

    0 天前=1.0, 超过 window 天=FACTOR_FLOOR, 中间线性衰减。
    与批次内其他人无关 —— 单人池/全员不活跃时依然给出真实水平。
    """
    if days_since_latest is None:
        return FACTOR_FLOOR
    return max(FACTOR_FLOOR, min(1.0, 1.0 - days_since_latest / window))


def hybrid_activity_normalize(raws: Sequence[float],
                              latest_days: Sequence[Optional[float]],
                              alpha: Optional[float] = None) -> list[float]:
    """活跃度 v2 归一化: α·绝对分 + (1-α)·相对分。

    raws:        每人冷却原始分(activity_score 输出)
    latest_days: 每人最近事件距今天数(days_since_latest_event 输出)
    alpha:       绝对分占比; 缺省取 settings.activity_absolute_weight
    """
    if alpha is None:
        alpha = settings.activity_absolute_weight
    absolutes = [absolute_activity(d) for d in latest_days]
    relatives = min_max_normalize(list(raws))
    return [
        max(FACTOR_FLOOR, min(1.0, alpha * a + (1.0 - alpha) * r))
        for a, r in zip(absolutes, relatives)
    ]


def _utcnow_naive() -> dt.datetime:
    """当前 UTC 时间(naive), 与 models._now 落库的时间同基准。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: dt.datetime) -> dt.datetime:
    """把可能带时区的 datetime 规整为 naive-UTC, 保证相减不混用 aware/naive。"""
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value  # 已是 naive: 视为 UTC(落库时即 UTC)


def build_activity_events(last_active_at=None,
                          interactions: Iterable[dict] = ()) -> list[dict]:
    """把画像的活跃来源拼成事件列表。

    last_active_at: TTC 平台最近活跃时间 -> platform_active 事件
    interactions:   [{"interaction_type": "call", "occurred_at": date/datetime}, ...]
    """
    events = []
    if last_active_at is not None:
        events.append(
            {"event_type": "platform_active", "occurred_at": last_active_at}
        )
    for it in interactions:
        occ = it.get("occurred_at")
        if occ is None:
            continue
        if isinstance(occ, dt.date) and not isinstance(occ, dt.datetime):
            occ = dt.datetime.combine(occ, dt.time())
        events.append(
            {"event_type": it.get("interaction_type", "note"), "occurred_at": occ}
        )
    return events


def min_max_normalize(values: Sequence[float]) -> list[float]:
    """Min-Max 归一化到 [FACTOR_FLOOR,1]。

    边界处理(修复冷启动白送分):
      - 全部为 0(真的没有活跃/没有关系, 冷启动最常见): 返回全 FACTOR_FLOOR,
        不再当成"中等 0.5"给所有人白送分, 保留区分度。
      - 全部相等但非 0(都有相同强度的信号): 返回全 0.5(中性)。
      - 其余: 正常 min-max, 且下限抬到 FACTOR_FLOOR 避免乘法模型误杀。
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        # 全相等: 区分"全为 0"与"全为相同非零值"
        if hi < 1e-9:
            return [FACTOR_FLOOR] * len(values)  # 全 0 -> 不白送分
        return [0.5] * len(values)               # 全相等非 0 -> 中性
    return [max(FACTOR_FLOOR, (v - lo) / (hi - lo)) for v in values]


# =====================================================================
# 因子 2: 岗位匹配度 —— 结构化多维 + 语义余弦加权融合 (v2)
#
#   match = Σ( 维度权重_i × 子分_i ) / Σ(维度权重_i)   # 缺失维度自动重归一
#   五个子维度:
#     title    职位名相似度: 字符 bigram Dice 系数(中文友好, 无分词依赖)
#     skill    技能覆盖率:   JD 关键词被人才技能/标签覆盖的比例(子串容错)
#     semantic 语义相似度:   max(0, cosine(JD向量, 简历向量)), 离线为哈希向量
#     years    年限达标度:   JD 抽取"X年"要求, 实际/要求 线性衰减
#     edu      学历达标度:   JD 抽取学历要求, 差级衰减(不硬杀)
#
#   v1 只有 semantic 一维; 离线(无 LLM Key)时退化为字符哈希向量,
#   职位/技能/年限/学历等结构化信息完全没用上 —— v2 让离线也有真实区分度。
# =====================================================================
MATCH_WEIGHTS = {
    "title": 0.25,
    "skill": 0.30,
    "semantic": 0.35,
    "years": 0.05,
    "edu": 0.05,
}

# 学历等级序(用于达标度衰减)
_EDU_LEVELS = ["大专", "本科", "硕士", "博士"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def match_score(jd_embedding: Sequence[float],
                resume_embedding: Sequence[float]) -> float:
    """纯语义匹配度 ∈ [0,1](v1 保留, 供降级/单测使用)。

    改用 max(0, cos) 而非线性 (cos+1)/2 ——
      - 离线哈希向量非负, cos∈[0,1]: 无共同词 -> cos≈0 -> match≈0(不匹配就该低分),
        有共同词 -> match 随重叠度上升, 区分度真实。
      - 真实 embedding cos∈[-1,1]: 负相关(不相关)截断为 0, 语义上也正确。
    """
    cos = cosine_similarity(jd_embedding, resume_embedding)
    return max(0.0, min(1.0, cos))


def bigram_dice_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """职位名等短文本相似度: bigram Dice = 2|A∩B| / (|A|+|B|)。

    中文按相邻两字切分; 不足 2 字符时退化为整串相等判断。
    任一方为空返回 None(维度缺失, 权重重归一)。
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return None
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    sa = {a[i:i + 2] for i in range(len(a) - 1)}
    sb = {b[i:i + 2] for i in range(len(b) - 1)}
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return 2.0 * inter / (len(sa) + len(sb))


def skill_coverage(jd_keywords: Sequence[str],
                   talent_keywords: Sequence[str]) -> Optional[float]:
    """JD 关键词被人才技能/标签覆盖的比例(子串容错, 大小写不敏感)。

    "hrbp" 能命中 "资深HRBP", "python" 能命中 "Python开发"。
    JD 无有效关键词返回 None(维度缺失); 人才无任何技能返回 0.0。
    """
    jd_set = {k.strip().lower() for k in jd_keywords if k and len(k.strip()) >= 2}
    if not jd_set:
        return None
    talent_set = {k.strip().lower() for k in talent_keywords if k and k.strip()}
    if not talent_set:
        return 0.0
    covered = sum(
        1 for k in jd_set
        if any(k in t or t in k for t in talent_set)
    )
    return covered / len(jd_set)


def extract_years_requirement(jd_text: Optional[str]) -> Optional[float]:
    """从 JD 文本抽取工作年限要求, 如 '3年以上经验' -> 3.0; 无则 None。"""
    import re

    if not jd_text:
        return None
    m = re.search(r"(\d+)\s*年(?:以上)?", jd_text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_edu_requirement(jd_text: Optional[str]) -> Optional[str]:
    """从 JD 文本抽取学历要求; 无则 None。"""
    if not jd_text:
        return None
    for edu in _EDU_LEVELS:
        if edu in jd_text:
            return edu
    return None


def years_fit(talent_work_years: Optional[float],
              jd_years: Optional[float]) -> Optional[float]:
    """年限达标度 ∈ [0.2,1]; JD 无要求返回 None(维度缺失)。"""
    if jd_years is None or jd_years <= 0:
        return None
    if talent_work_years is None:
        return 0.9  # 未知不惩罚过重
    if talent_work_years >= jd_years:
        return 1.0
    return max(0.2, min(0.9, talent_work_years / jd_years))


def edu_fit(talent_education: Optional[str],
            jd_edu: Optional[str]) -> Optional[float]:
    """学历达标度: 达标=1, 每差一级 ×0.8; JD 无要求返回 None(维度缺失)。"""
    if jd_edu is None:
        return None
    if jd_edu not in _EDU_LEVELS:
        return None
    if not talent_education:
        return 0.9  # 未知不惩罚过重
    # 人才学历文本里找等级(容错 "硕士研究生" 命中 "硕士")
    talent_lvl = None
    for i, edu in enumerate(_EDU_LEVELS):
        if edu in talent_education:
            talent_lvl = i
            break
    if talent_lvl is None:
        return 0.9
    gap = _EDU_LEVELS.index(jd_edu) - talent_lvl
    if gap <= 0:
        return 1.0
    return max(0.4, 1.0 - 0.2 * gap)


def match_score_v2(
    position_name: Optional[str],
    jd_text: Optional[str],
    jd_keywords: Optional[Sequence[str]],
    talent_position: Optional[str],
    talent_skills: Optional[Sequence[str]],
    talent_tags: Optional[Sequence[str]],
    talent_work_years: Optional[float],
    talent_education: Optional[str],
    jd_embedding: Optional[Sequence[float]] = None,
    resume_embedding: Optional[Sequence[float]] = None,
    title_semantic: Optional[float] = None,
) -> float:
    """岗位匹配度 v2 ∈ [0,1]: 结构化多维 + 语义余弦加权融合。

    title 维度优先用 LLM 语义相似度(title_semantic, 见 llm.title_similarity):
    "AI研发工程师" 与 "算法工程师" 这类同族岗位能得 0.7+, 字面 bigram 只作离线降级。
    缺失维度(返回 None 的子分)权重自动重归一到其余维度,
    所以 JD 只填岗位名也能算, 离线(无向量/无 LLM)时靠结构化维度撑区分度。
    """
    # title: LLM 语义相似度优先; 离线降级 bigram dice
    if title_semantic is not None:
        title_sub = max(0.0, min(1.0, title_semantic))
    else:
        title_sub = bigram_dice_similarity(position_name, talent_position)

    subs: dict[str, Optional[float]] = {
        "title": title_sub,
        "skill": skill_coverage(
            jd_keywords or [], list(talent_skills or []) + list(talent_tags or [])
        ),
        "semantic": None,
        "years": years_fit(talent_work_years, extract_years_requirement(jd_text)),
        "edu": edu_fit(talent_education, extract_edu_requirement(jd_text)),
    }
    if jd_embedding and resume_embedding:
        subs["semantic"] = max(0.0, min(
            1.0, cosine_similarity(jd_embedding, resume_embedding)))

    total_w, total = 0.0, 0.0
    for dim, sub in subs.items():
        if sub is None:
            continue
        w = MATCH_WEIGHTS.get(dim, 0.0)
        total_w += w
        total += w * sub
    if total_w <= 1e-9:
        return 0.5  # 一个可用维度都没有: 中性
    return max(0.0, min(1.0, total / total_w))


# =====================================================================
# 因子 3: 人才价值 —— 静态分(公司等级 + 学历 + 稀缺技能) -> 归一化到 [0,1]
# =====================================================================
COMPANY_TIER = {
    "大厂": 10.0,
    "独角兽": 8.0,
    "上市公司": 7.0,
    "一般": 5.0,
}
EDUCATION_TIER = {
    "博士": 10.0,
    "硕士": 8.0,
    "本科": 6.0,
    "大专": 4.0,
}
# 稀缺技能加分(可按行业扩展)
SCARCE_SKILLS = {"AI训练师": 2.0, "大模型": 2.0, "量化": 1.5, "算法": 1.0}


def raw_value_score(company_tier: str = "一般", education: str = "本科",
                    skills: Optional[Sequence[str]] = None) -> float:
    """原始人才价值分(0~22 区间); 调用方做归一化。"""
    base = COMPANY_TIER.get(company_tier, 5.0)
    base += EDUCATION_TIER.get(education, 6.0)
    if skills:
        base += sum(SCARCE_SKILLS.get(s, 0.0) for s in skills)
    return base


def normalize_value(raw: float, lo: float = 0.0, hi: float = 22.0) -> float:
    return max(0.0, min(1.0, (raw - lo) / (hi - lo)))


# =====================================================================
# 因子 4: 历史关系 —— 近 3 个月互动频次加权后批量 Min-Max 归一化
#   频次 = 面试次数×3 + 通话次数×2 + 消息条数×0.5
# =====================================================================
INTERACTION_WEIGHTS = {"interview": 3.0, "call": 2.0, "message": 0.5, "note": 0.0}


def raw_relationship_score(interactions: Iterable[dict]) -> float:
    total = 0.0
    for it in interactions:
        w = INTERACTION_WEIGHTS.get(it.get("interaction_type", ""), 0.0)
        total += w * (it.get("count") or 0)
    return total


# =====================================================================
# 因子 5: 求职可能性 —— LLM 文本分析输出 [0,1]; 无记录默认 0.5 中性
# =====================================================================
def tendency_score(llm_score: Optional[float]) -> float:
    if llm_score is None:
        return 0.5
    return max(0.0, min(1.0, float(llm_score)))
