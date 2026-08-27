# RE:LOOP Local Ranking Demo Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed ten deterministic fictional talents and one parsed AI product position into the local guest pool, then demonstrate and record the distinct activity and match orders in the existing frontend.

**Architecture:** A one-off transactional Python command uses the existing SQLAlchemy models and local SQLite engine. Talent records are idempotently upserted by the `demo-ranking-v1-` source prefix, the exact demo position is updated or created, and only recommendation caches for that exact position are invalidated. Verification uses the live same-origin API and the current in-app browser; no product source or external service changes are required.

**Tech Stack:** Python 3, SQLAlchemy 2, SQLite, FastAPI, React/Vite, existing recommendation engine, in-app browser.

## Global Constraints

- Write only to `/Users/shishen/Downloads/RE-LOOP-source 3/reloop.local.db`.
- Preserve all non-demo talents, positions, interactions, recommendations, and users.
- Every seeded talent uses owner `guest_shared`, a `source_id` beginning `demo-ranking-v1-`, and `source_payload.demo_dataset == "ranking-v1"`.
- The exact demo position name is `AI 产品经理（演示）`.
- Use fictional data with null phone and email fields.
- Do not call DeepSeek, the generic LLM API, TTC, or any production service.
- Do not modify frontend or backend source code.

---

### Task 1: Transactionally Seed The Demo Pool

**Files:**
- Modify local state only: `/Users/shishen/Downloads/RE-LOOP-source 3/reloop.local.db`
- Preserve source: `reloop/db/models.py`

**Interfaces:**
- Consumes: `SessionLocal`, `User`, `TalentProfile`, `Position`, `Recommendation`, `RecommendRun`, and `_fallback_embed(text)`.
- Produces: ten `TalentProfile` rows with source IDs `demo-ranking-v1-01` through `demo-ranking-v1-10`, plus one active parsed position named `AI 产品经理（演示）`.

- [ ] **Step 1: Record the pre-seed isolation counts**

Run:

```bash
python - <<'PY'
from reloop.db.engine import SessionLocal
from reloop.db.models import Position, TalentProfile
from sqlalchemy import or_

with SessionLocal() as db:
    non_demo = db.query(TalentProfile).filter(
        TalentProfile.owner_user_id == "guest_shared",
        or_(
            TalentProfile.source_id.is_(None),
            ~TalentProfile.source_id.like("demo-ranking-v1-%"),
        ),
    ).count()
    demo = db.query(TalentProfile).filter(
        TalentProfile.owner_user_id == "guest_shared",
        TalentProfile.source_id.like("demo-ranking-v1-%"),
    ).count()
    positions = db.query(Position).filter(
        Position.owner_user_id == "guest_shared",
        Position.position_name != "AI 产品经理（演示）",
    ).count()
    print({"non_demo_talents": non_demo, "demo_talents": demo, "non_demo_positions": positions})
PY
```

Expected: prints the exact baseline counts without changing the database.

- [ ] **Step 2: Execute the idempotent seed transaction**

Run this exact command from `/Users/shishen/Downloads/RE-LOOP-source 3`:

```bash
python - <<'PY'
import datetime as dt

from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import Position, Recommendation, RecommendRun, TalentProfile, User
from reloop.modules.profile.llm import _fallback_embed

OWNER = "guest_shared"
POSITION = "AI 产品经理（演示）"
now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

rows = [
    ("01", "陈浩", "上海", "星海科技", "销售总监", 9, "本科", ["企业销售", "渠道管理", "客户关系"], 0.58, 20, ["销售", "活跃演示"]),
    ("02", "周宁", "杭州", "云帆网络", "产品运营经理", 5, "本科", ["用户运营", "需求分析", "数据分析"], 0.70, 60, ["产品运营", "活跃演示"]),
    ("03", "李澄", "北京", "远望咨询", "HRBP", 7, "硕士", ["组织发展", "招聘", "人才盘点"], 0.62, 180, ["HRBP", "已关注"]),
    ("04", "王晨", "深圳", "数澜智能", "高级数据分析师", 6, "硕士", ["SQL", "数据分析", "指标体系", "Python"], 0.78, 480, ["数据分析", "AI"]),
    ("05", "苏然", "上海", "智构科技", "高级 AI 产品经理", 7, "硕士", ["AI 产品", "大模型", "产品规划", "用户研究", "SQL"], 0.92, 1440, ["AI 产品经理", "B2B SaaS"]),
    ("06", "许墨", "北京", "矩阵软件", "解决方案产品经理", 8, "本科", ["B2B SaaS", "解决方案", "跨部门交付", "需求分析"], 0.84, 2880, ["产品经理", "SaaS"]),
    ("07", "赵可", "杭州", "知行云", "B2B SaaS 产品经理", 6, "本科", ["B2B SaaS", "产品规划", "SQL", "数据分析"], 0.88, 5760, ["产品经理", "B2B SaaS"]),
    ("08", "林悦", "上海", "灵犀智能", "AI 产品负责人", 10, "硕士", ["AI 产品", "大模型", "B2B SaaS", "产品规划", "SQL", "跨部门交付"], 0.96, 8640, ["AI 产品经理", "B2B SaaS", "已关注"]),
    ("09", "梁雪", "广州", "启明研究", "战略研究经理", 8, "硕士", ["行业研究", "商业分析", "战略规划"], 0.73, None, ["战略"]),
    ("10", "方哲", "深圳", "原点科技", "前端开发工程师", 4, "本科", ["React", "TypeScript", "前端工程"], 0.66, None, ["技术"]),
]

jd_text = """AI 产品经理 B2B SaaS 大模型 SQL 数据分析 用户研究 产品规划 跨部门交付。
要求 5 年以上产品经验，本科及以上学历；负责企业级 AI 产品从需求洞察、方案设计到上线复盘。"""
jd_analysis = {
    "title": "AI 产品经理",
    "summary": "负责企业级 AI 产品规划与交付",
    "responsibilities": ["需求洞察", "产品规划", "跨部门交付", "上线复盘"],
    "required_skills": ["AI 产品", "B2B SaaS", "SQL", "数据分析", "用户研究"],
    "preferred_skills": ["大模型", "企业服务"],
    "experience": "5 年以上产品经验",
    "education": "本科及以上",
    "location": "上海/北京/杭州/深圳",
    "industry_keywords": ["人工智能", "企业服务", "SaaS"],
    "salary_range": "面议",
    "team_size": "跨职能团队",
    "reporting_line": "产品负责人",
    "language_requirements": ["中文"],
}

init_db()
with SessionLocal() as db:
    try:
        user = db.query(User).filter(User.user_id == OWNER).one_or_none()
        if user is None:
            db.add(User(user_id=OWNER, display_name="访客"))

        for suffix, name, location, company, title, years, education, skills, value, minutes, tags in rows:
            source_id = f"demo-ranking-v1-{suffix}"
            talent = db.query(TalentProfile).filter(
                TalentProfile.owner_user_id == OWNER,
                TalentProfile.source_id == source_id,
            ).one_or_none()
            if talent is None:
                talent = TalentProfile(owner_user_id=OWNER, source_id=source_id, name=name)
                db.add(talent)
            talent.name = name
            talent.base_location = location
            talent.company = company
            talent.position = title
            talent.contact_phone = None
            talent.contact_email = None
            talent.seek_status = "在职看机会"
            talent.work_years = years
            talent.education = education
            talent.skills = skills
            talent.tags = tags
            talent.value_score = value
            talent.last_active_at = now - dt.timedelta(minutes=minutes) if minutes is not None else None
            talent.resume_updated_at = talent.last_active_at
            talent.resume_text = f"{title}，{years} 年经验，技能：{'、'.join(skills)}"
            talent.resume_embedding = _fallback_embed(talent.resume_text)
            talent.notes = "RE:LOOP 排序演示数据"
            talent.source_payload = {"demo_dataset": "ranking-v1", "fictional": True}

        positions = db.query(Position).filter(
            Position.owner_user_id == OWNER,
            Position.position_name == POSITION,
        ).order_by(Position.created_at.desc()).all()
        position = positions[0] if positions else Position(owner_user_id=OWNER, position_name=POSITION)
        if not positions:
            db.add(position)
        for duplicate in positions[1:]:
            duplicate.is_active = 0
        position.jd_text = jd_text
        position.jd_analysis = jd_analysis
        position.jd_analysis_version = "deepseek-v1"
        position.jd_embedding = _fallback_embed(jd_text)
        position.is_active = 1

        db.query(Recommendation).filter(
            Recommendation.owner_user_id == OWNER,
            Recommendation.focus_position == POSITION,
        ).delete(synchronize_session=False)
        db.query(RecommendRun).filter(
            RecommendRun.owner_user_id == OWNER,
            RecommendRun.position_name == POSITION,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise

print({"owner": OWNER, "talents": len(rows), "position": POSITION})
PY
```

Expected: `{'owner': 'guest_shared', 'talents': 10, 'position': 'AI 产品经理（演示）'}`.

- [ ] **Step 3: Verify isolation and uniqueness**

Run the Step 1 count command again, then query the demo rows and active position:

```bash
python - <<'PY'
from reloop.db.engine import SessionLocal
from reloop.db.models import Position, TalentProfile

with SessionLocal() as db:
    demos = db.query(TalentProfile).filter(
        TalentProfile.owner_user_id == "guest_shared",
        TalentProfile.source_id.like("demo-ranking-v1-%"),
    ).all()
    positions = db.query(Position).filter(
        Position.owner_user_id == "guest_shared",
        Position.position_name == "AI 产品经理（演示）",
        Position.is_active == 1,
    ).count()
    print({"demo_count": len(demos), "unique_sources": len({row.source_id for row in demos}), "active_demo_positions": positions})
PY
```

Expected: `demo_count == 10`, `unique_sources == 10`, `active_demo_positions == 1`, and Step 1's non-demo counts are unchanged. The upsert query in Step 2 makes subsequent runs update these same ten source IDs.

---

### Task 2: Exercise The Real Ranking Pipeline And Present It

**Files:**
- Read live API: `http://127.0.0.1:8000`
- Read browser UI: `http://127.0.0.1:8000/#/`

**Interfaces:**
- Consumes: `GET /auth/me`, `GET /talents`, `GET /positions`, `POST /recommend/compute`, and `GET /recommend/result`.
- Produces: the actual top-five activity order and actual top-five match order shown in the current frontend.

- [ ] **Step 1: Verify the live API sees the seeded pool**

Run:

```bash
curl -fsS http://127.0.0.1:8000/auth/me
curl -fsS http://127.0.0.1:8000/talents
curl -fsS http://127.0.0.1:8000/positions
```

Expected: `/auth/me` reports `pool_count >= 10`, exactly ten talent records have a `demo-ranking-v1-` source ID, and the active demo position includes non-null `jd_analysis`.

- [ ] **Step 2: Compute the deterministic match result**

Run:

```bash
curl -fsS -X POST 'http://127.0.0.1:8000/recommend/compute?position_name=AI%20%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86%EF%BC%88%E6%BC%94%E7%A4%BA%EF%BC%89&sort_by=match'
```

If the response has `computing: true`, poll:

```bash
curl -fsS 'http://127.0.0.1:8000/recommend/result?position_name=AI%20%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86%EF%BC%88%E6%BC%94%E7%A4%BA%EF%BC%89&sort_by=match'
```

Expected: final `status == "done"` or an immediate final/cache response, with non-empty `top_n` sorted by descending `score`.

- [ ] **Step 3: Verify activity and match orders in the browser**

Reload the existing in-app browser tab. Record the first five `.focus-row` names and visible activity labels in activity mode. Select `岗位匹配`, confirm the selected position is `AI 产品经理（演示）`, wait until computation completes, then record the first five names and match scores.

Expected:

- Activity mode starts with `陈浩`, `周宁`, `李澄`, `王晨`, `苏然`.
- Match mode's first five differs from the activity order and is descending by the backend score.
- The frontend does not re-sort the backend match array.
- The page has no horizontal overflow and the console has no new warnings or errors.

- [ ] **Step 4: Report the visible demonstration**

Report both top-five orders in Chinese, explain why the leading candidate differs between the two modes, leave the browser on match mode, and state that all demo records can later be removed by the `demo-ranking-v1-` source prefix without affecting real data.
