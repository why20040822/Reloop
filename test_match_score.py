"""快速测试 match_score_structured 的分布情况。"""
import sys
sys.path.insert(0, "F:/ttc/Reloop")

from reloop.modules.scoring.factors import match_score_structured

# 模拟一个长 JD（用户提供的海外社区运营 JD）
jd = """负责海外用户社区的日常运营，包括 WhatsApp、Telegram、Instagram 等平台的用户互动、社区维护及氛围建设；
深入了解欧美用户需求和使用习惯，持续收集用户反馈，并推动产品体验及运营策略优化；
策划并产出社区运营内容，包括产品使用案例、UGC 内容、传播素材等，提升用户参与度及自然传播；
跟踪社区活跃、用户增长及内容传播等核心数据，持续优化运营策略；
配合产品迭代及新功能上线，完成用户教育、活动策划、种子用户运营等工作；
参与海外用户增长相关工作，探索社区裂变、用户推荐等增长方式。
任职要求：英语流利，能够熟练使用英语进行日常沟通及内容表达；
有海外社区运营、用户运营、增长运营或出海产品相关经验；
熟悉 WhatsApp、Telegram、Instagram 等海外主流社交平台，对欧美互联网用户及社区文化有一定理解；
用户感知能力强，能够从用户反馈中发现问题，并形成有效的运营或产品建议；
执行力强，能够独立推进工作，适应创业团队快节奏、多任务并行的工作方式；
对 AI/AIGC、消费级 AI 产品或海外互联网产品感兴趣。
加分项：有 AI/AIGC、海外工具类产品或消费级互联网产品运营经验；
有从 0 到 1 搭建或运营海外社区的经历；
有实际的社区增长、UGC 裂变或用户增长案例；
有早期创业公司或小团队工作经历。"""

# 模拟几个候选人
candidates = [
    {"name": "完美匹配", "position": "海外社区运营经理", "skills": ["WhatsApp", "Telegram", "Instagram", "UGC", "社区运营", "用户增长"], "work_years": 5, "education": "本科"},
    {"name": "部分匹配", "position": "用户运营", "skills": ["用户运营", "内容策划"], "work_years": 3, "education": "本科"},
    {"name": "弱匹配", "position": "产品经理", "skills": ["产品设计", "数据分析"], "work_years": 2, "education": "硕士"},
    {"name": "无关", "position": "会计", "skills": ["财务", "会计"], "work_years": 10, "education": "本科"},
]

# 提取关键词（和引擎一致的方式）
from reloop.modules.recommend.engine import RecommendEngine
engine = RecommendEngine()
pos = type("Pos", (), {"position_name": "海外社区运营", "jd_text": jd})()
keywords = engine._extract_keywords(pos)
print(f"JD 关键词数: {len(keywords)}")
print(f"前10个关键词: {keywords[:10]}")

print("\n=== 匹配度测试（改进后）===")
for c in candidates:
    score = match_score_structured(
        position_name="海外社区运营",
        jd_text=jd,
        jd_keywords=keywords,
        talent_position=c["position"],
        talent_skills=c["skills"],
        talent_tags=[],
        talent_work_years=c["work_years"],
        talent_education=c["education"],
    )
    print(f"{c['name']}: {score:.4f}")
