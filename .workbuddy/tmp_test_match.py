import os, sys
os.chdir("F:/ttc/Reloop"); sys.path.insert(0, "F:/ttc/Reloop")
import logging; logging.basicConfig(level=logging.ERROR)
from reloop.modules.profile.llm import llm_service

# title_similarity: 应返回真实语义分(非空 dict)
print("[title_similarity] 海外社区运营 vs [用户运营, 算法工程师, 销售]")
ts = llm_service.title_similarity("海外社区运营", ["用户运营", "算法工程师", "销售"])
print("   ->", ts)

# batch_match_scores: 应返回真实匹配分(非空 dict)
cands = [
    {"idx":1,"name":"A","position":"海外用户运营","company":"某出海公司","skills":["社群","增长"],"work_years":4,"education":"本科"},
    {"idx":2,"name":"B","position":"算法工程师","company":"某大厂","skills":["Python","ML"],"work_years":5,"education":"硕士"},
]
print("[batch_match_scores] 海外社区运营/用户运营 岗位")
bs = llm_service.batch_match_scores("海外社区运营/用户运营", "负责海外用户社区运营, 英语流利, 熟悉 WhatsApp/Telegram/Instagram", cands)
print("   ->", bs)

assert isinstance(ts, dict) and ts, "title_similarity 未用上 LLM"
assert isinstance(bs, dict) and bs, "batch_match_scores 未用上 LLM"
print("\nLLM 匹配通道已激活 ✅")
