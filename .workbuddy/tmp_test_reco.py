import json
import httpx

BASE = "http://127.0.0.1:8000"
H = {"X-Owner-User-Id": "guest_shared", "Content-Type": "application/json"}
POSITION = "海外社区运营 / 用户运营"
JD = """- **岗位职责**：
  - 负责海外用户社区的日常运营，包括 WhatsApp、Telegram、Instagram 等平台的用户互动、社区维护及氛围建设；
  - 深入了解欧美用户需求和使用习惯，持续收集用户反馈，并推动产品体验及运营策略优化；
  - 策划并产出社区运营内容，包括产品使用案例、UGC 内容、传播素材等，提升用户参与度及自然传播；
  - 跟踪社区活跃、用户增长及内容传播等核心数据，持续优化运营策略；
  - 配合产品迭代及新功能上线，完成用户教育、活动策划、种子用户运营等工作；
  - 参与海外用户增长相关工作，探索社区裂变、用户推荐等增长方式。
- **任职要求**：
  - 英语流利，能够熟练使用英语进行日常沟通及内容表达；
  - 有海外社区运营、用户运营、增长运营或出海产品相关经验；
  - 熟悉 WhatsApp、Telegram、Instagram 等海外主流社交平台，对欧美互联网用户及社区文化有一定理解；
  - 用户感知能力强，能够从用户反馈中发现问题，并形成有效的运营或产品建议；
  - 执行力强，能够独立推进工作，适应创业团队快节奏、多任务并行的工作方式；
  - 对 AI/AIGC、消费级 AI 产品或海外互联网产品感兴趣。
- **加分项**：
  - 有 AI/AIGC、海外工具类产品或消费级互联网产品运营经验；
  - 有从 0 到 1 搭建或运营海外社区的经历；
  - 有实际的社区增长、UGC 裂变或用户增长案例；
  - 有早期创业公司或小团队工作经历。"""

# 1. 设岗
r = httpx.post(f"{BASE}/positions", json={"position_name": POSITION, "jd_text": JD}, headers=H, timeout=30)
print("set position:", r.status_code, r.json().get("position_name") if r.status_code == 200 else r.text[:100])

# 2. 触发推荐
r = httpx.post(f"{BASE}/recommend/compute?position_name={POSITION}", headers=H, timeout=30)
print("compute:", r.status_code)
d = r.json()
print("  phase:", d.get("phase"), "| computing:", d.get("computing"), "| shortlisted:", d.get("shortlisted"), "| total_pool:", d.get("total_pool"))

# 3. 轮询结果
import time
for i in range(8):
    time.sleep(2)
    r = httpx.get(f"{BASE}/recommend/result?position_name={POSITION}", headers=H, timeout=30)
    d = r.json()
    st = d.get("status", d.get("phase"))
    print(f"  poll {i+1}: status={st}")
    if d.get("status") == "done" or d.get("phase") == "final":
        break

# 4. 输出 Top3
items = d.get("top3") or d.get("top_n") or []
print(f"Top{len(items)}:")
for it in items[:3]:
    bd = it.get("score_breakdown") or {}
    print(f"  #{it['rank']} {it['name']} | {it.get('company')} | {it.get('position')} | match={bd.get('match')} act={bd.get('activity')}")
    print(f"      reason: {str(it.get('contact_reason'))[:80]}")
