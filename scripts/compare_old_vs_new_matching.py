"""新旧匹配算法对比演示(离线, 无 LLM)。

旧 = 改造①前: _extract_keywords 原文分词 + skill_coverage(Jaccard) +
     正则扫 jd_text 抽年限/学历 + cosine 失配返回 0.0
新 = 改造①后: build_jd_features 解析特征直通 + skill_coverage_detail(覆盖率
     +命中清单) + 解析字段优先 + cosine 失配返回 None(缺失维)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os_env = __import__("os").environ
os_env.setdefault("BRAINX_DATABASE_URL", "sqlite:///./test_local.db")
os_env.setdefault("BRAINX_LLM_API_KEY", "")

import re

from reloop.core.jd_features import build_jd_features
from reloop.core.matching import (
    cosine_similarity, extract_edu_requirement, extract_years_requirement,
    match_score_structured_detail, skill_coverage,
)

POSITION = "高级后端开发工程师"
JD_TEXT = ("负责核心服务端研发, 保障高可用。要求: 精通 Python、熟悉 SQL 与 Kafka; "
           "本科及以上学历, 3-5年相关经验。有 K8s 经验者优先。")
JD_ANALYSIS = {
    "title": "高级后端开发工程师",
    "required_skills": ["Python", "SQL", "Kafka"],
    "preferred_skills": ["K8s"],
    "experience": "3-5年",
    "education": "本科及以上",
}

TALENTS = [
    ("A 后端开发·全命中",   "后端开发",   ["python开发", "mysql", "kafka"], 4.0, "本科"),
    ("B 数据分析师·部分命中", "数据分析师", ["sql", "excel"],                2.0, "本科"),
    ("C 运营专员·零命中",    "运营专员",   ["新媒体运营"],                  1.0, "大专"),
    ("D 后端·技能字段为空",  "后端开发",   [],                              5.0, "硕士"),
    ("E 算法工程师·跨界",    "算法工程师", ["python", "tensorflow"],        6.0, "博士"),
]


# ---------- 旧算法(改造①前) ----------

def old_extract_keywords(pos, jd):
    raw = f"{pos or ''} {jd or ''}"
    parts = re.split(r"[\s,，、/;；|]+", raw)
    kws, seen, out = [], set(), []
    if pos:
        kws.append(pos.strip())
    kws += [p.strip() for p in parts]
    for k in kws:
        if k and len(k) >= 2 and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:30]


def old_match(t_position, t_skills, t_years, t_edu, dim256=True):
    kws = old_extract_keywords(POSITION, JD_TEXT)
    subs = {
        "title": None,  # title 双侧同源, 对比中无差异, 略
        "skill": skill_coverage(kws, t_skills),
        "semantic": None,
        "years": None,
        "edu": None,
    }
    jy = extract_years_requirement(JD_TEXT)      # 正则会扫出 "5年"(取 3-5 的 5? 实际取首个 \d+年 -> 5)
    je = extract_edu_requirement(JD_TEXT)
    from reloop.core.matching import years_fit, edu_fit
    subs["years"] = years_fit(t_years, jy)
    subs["edu"] = edu_fit(t_edu, je)
    if dim256:
        # 双侧 256 哈希向量在场: 旧版语义维有效但为伪语义; 这里用固定占位值示意
        subs["semantic"] = 0.31
    total_w, total = 0.0, 0.0
    for dim, s in subs.items():
        if s is None:
            continue
        w = {"title": 0.25, "skill": 0.30, "semantic": 0.35, "years": 0.05, "edu": 0.05}[dim]
        total_w += w
        total += w * s
    return 0.3 + 0.7 * (total / total_w) if total_w else 0.5


# ---------- 运行对比 ----------

feats = build_jd_features(POSITION, JD_TEXT, JD_ANALYSIS)
old_kws = old_extract_keywords(POSITION, JD_TEXT)

print("=" * 78)
print("JD:", JD_TEXT[:50], "...")
print(f"\n[召回关键词] 旧(原文分词 {len(old_kws)} 个): {old_kws[:8]} ...")
print(f"[召回关键词] 新(规范化特征 {len(feats.recall_keywords)} 个): {feats.recall_keywords}")
print(f"[技能要求]   新: {feats.skill_list} | years_min={feats.years_min} edu_min={feats.edu_min}")

print("\n[年限/学历解析对比]")
print(f"  旧(正则扫原文): years={extract_years_requirement(JD_TEXT)}, edu={extract_edu_requirement(JD_TEXT)}")
print(f"  新(解析字段):   years={feats.years_min}, edu={feats.edu_min}")

print("\n" + "=" * 78)
print(f"{'候选人':<18}{'旧 skill':>9}{'新 skill':>9}{'旧 match':>10}{'新 match':>10}{'Δ':>8}  新命中清单")
rows = []
for name, t_pos, t_skills, t_years, t_edu in TALENTS:
    old_skill = skill_coverage(old_kws, t_skills)
    new_detail = match_score_structured_detail(
        POSITION, JD_TEXT, feats.recall_keywords,
        talent_position=t_pos, talent_skills=t_skills, talent_tags=[],
        talent_work_years=t_years, talent_education=t_edu,
        jd_skills=feats.skill_list, years_min=feats.years_min, edu_min=feats.edu_min,
    )
    old_m = old_match(t_pos, t_skills, t_years, t_edu)
    new_m = new_detail["score"]
    hits = ",".join(new_detail["skill_hits"]) or "-"
    rows.append((name, old_m, new_m))
    print(f"{name:<18}{old_skill:>9.3f}{new_detail['dims']['skill']:>9.3f}"
          f"{old_m:>10.3f}{new_m:>10.3f}{new_m - old_m:>+8.3f}  {hits}")

print("\n[排序变化] 旧算法名次 -> 新算法名次:")
old_rank = sorted(rows, key=lambda r: r[1], reverse=True)
new_rank = sorted(rows, key=lambda r: r[2], reverse=True)
for i, (name, *_ ) in enumerate(old_rank, 1):
    j = next(k for k, r in enumerate(new_rank, 1) if r[0] == name)
    mark = "  <-- 名次变化" if i != j else ""
    print(f"  {i}. {name}  =>  新名次 {j}{mark}")

print("\n[失配防护对比] 256 维 JD 向量 vs 2048 维简历向量:")
old_val = 0.0 if cosine_similarity([0.1] * 256, [0.1] * 2048) is None and False else "0.0(旧, 计入权重)"
new_val = cosine_similarity([0.1] * 256, [0.1] * 2048)
print(f"  旧: 语义维 = {old_val} -> 全员被静默拖低")
print(f"  新: 语义维 = {new_val} -> 缺失维, 权重归一跳过, 不误伤")

print("\n[LLM 精算 prompt] 新增【岗位技能要求】块:")
print("  旧: 只塞 jd_text[:2000] 原文")
print(f"  新: 追加逐项技能清单 {feats.skill_list}")
