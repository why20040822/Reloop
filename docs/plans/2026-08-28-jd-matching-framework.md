# JD 解析 → 算法匹配 · 断链诊断与目标框架（2026-08-28）

> 现象：AI 自动解析 JD 成功落库后，推荐算法"没有真正的自动匹配"——分数主要靠字面重合与伪语义，解析出的结构化字段没人用。
> 证据：代码链路逐点追踪 + 生产 guest_shared 池（539 人）实测。

---

## 一、断链诊断（4 个断点，按严重度）

### 断点 1（主因）：解析产物与匹配引擎之间是"断桥"

`positions.jd_analysis`（JDAnalysis 13 字段，AI 解析的核心产物）**落库后全链路零消费**——grep 全仓，只有写入（api/positions.py），没有任何读取。匹配引擎仍在从原始 `jd_text` 重新抽特征：

| 匹配维度（权重） | 引擎实际做法 | 应该用解析字段 | 后果 |
|---|---|---|---|
| skill（0.30） | `_extract_keywords`：对原文按空白/标点切分 | `required_skills` + `preferred_skills` | **中文无空格 → 整句短语当"关键词"**，与人才 skills（61% 覆盖）的 Jaccard 几乎打不中（注：召回层是子串匹配+零召回退全量兜底，尚能工作；**真正死的是排序的 skill 维**） |
| years（0.05） | 正则 `(\d+)年` 扫原文 | `experience` | AI 已解析却弃用，双份解析逻辑漂移 |
| edu（0.05） | 子串匹配扫原文 | `education` | 同上 |
| title（0.25） | 岗位名 bigram / LLM 语义 | `title`（规范岗位名） | 轻微 |

一句话：**AI 花钱解析出来的东西，算法一眼都没看。**

### 断点 2：semantic 维（最大权重 0.35）是"伪语义"

- 生产实测：guest_shared 池 539 人的 `resume_embedding` **全部是 256 维离线哈希向量**（真语义模型 embedding-3 是 2048 维；哈希降级 = BigModel 通道不可用时的兜底）。
- `jd_embedding` 同样经常落为哈希。
- 哈希向量余弦 ≈ 字面 n-gram 重合，无语义泛化："Python 开发"与"Python 工程师"在哈希空间里可能很远。
- **权重最大的维度实际上是字面相似度，还占着语义的名字。**

### 断点 3：LLM 主通道不稳定，降级链自身带病

最终匹配分 = `0.6×LLM精算 + 0.4×结构化降级`。LLM chat（BigModel glm-4-flash / stepfun）一旦熔断，全量退回结构化链——而结构化链正是断点 1/2 所在。降级不是"低配"，是"错配"。

### 断点 4（轻）：无结果可解释性

FactorScores 有分维度值但前端不展示 per-dim 依据；`score_source`（LLM/降级、embedding 真伪）没有任何标记，用户无法判断分数可信度。

数据面佐证：skills 覆盖 61%、work_years 99%、education 91%、position 88%——**人才侧数据够用，问题全在 JD 侧特征没有接进来。**

---

## 二、目标框架（七层匹配链路）

```
JD 原文
  │
  ▼
[1] JD 解析层（已有 ✅）        stepfun → JDAnalysis 13 字段（title/skills/experience/education/...）
  │                              产物落库 positions.jd_analysis + jd_analysis_version
  ▼
[2] 特征规范化层【新增 · 断桥修复点】
  │   jd_analysis ──▶ MatchingFeatures（纯 core，零 IO）：
  │     · required_skills ∪ preferred_skills ─▶ skill_set（小写/去噪/别名归一）
  │     · experience ─▶ years_min；education ─▶ edu_min
  │     · industry_keywords ─▶ 加权词表；title ─▶ 规范岗位名
  │     ▼ 解析版本变化时匹配特征重算（驱动 recommend_runs 缓存失效）
  ▼
[3] 召回层（已有，改输入源）    L1 关键词召回（改用 [2] 的 skill_set，弃原文分词）
  │                             ∪ L2 向量召回（[4] 的真语义向量 topK）
  │                             无召回兜底全量（现状保留）
  ▼
[4] 语义向量层【修复点】
  │   真语义 embedding 统一供给：JD 与简历同源同维（BigModel embedding-3 / 备选厂商）
  │   服务器/本地配好 key → 存量 256 维哈希向量用 embed_batch 批量重算
  │   每条向量带 embed_source 标记（real | hash）；哈希仅作最后兜底
  ▼
[5] 结构化评分层（core/matching，五维骨架已有 ✅，输入改接 [2]/[4]）
  │   title / skill / semantic / years / edu → 权重自动归一 → 0.3+0.7×weighted
  ▼
[6] LLM 精算层（已有 ✅，增强可观测）
  │   Top30 批量精算；熔断降级时明确打标 score_source=struct_fallback
  ▼
[7] 排名与解释层（已有 ✅，补前端输出）
      priority 加权乘法（活跃度×匹配度）+ per-dim 分数 + score_source 展示
      前端：每条推荐可见"为什么是他"（技能命中了哪几项、语义来源是真模型还是哈希）
```

## 三、改造清单（按 ROI 排序）

| # | 改造 | 工作量 | 收益 |
|---|---|---|---|
| 1 | **特征规范化层 + 引擎消费 jd_analysis**（skill 维改用解析 skills，edu/years 改用解析字段，删除原文重抽逻辑） | ~1 天 | 断桥直接修复；纯 core 改造零新依赖；分数立刻变得"有依据" |
| 2 | **语义向量真实化**：配 BigModel embedding key → 存量哈希向量批量重算（embed_batch 已有）+ 新增/更新走真模型 + embed_source 字段 | ~1 天 | 0.35 权重维从伪语义变真语义 |
| 3 | **可解释性输出**：FactorScores 带 score_source 与 per-dim 明细 → 前端推荐卡展示 | ~0.5 天 | 用户信任 + 调试效率 |
| 4 | **缓存联动**：jd_analysis_version / embedding 重算后使 recommend_runs 失效（sha256 键里加版本） | ~0.5 天 | 防止旧分数长期漂白 |
| 5 | LLM 主通道稳定性（已由熔断+双厂商缓解，观察即可） | 0 | — |

验收口径建议：同一 JD，人工选出的 Top5 候选应出现在算法 Top10 内；skill 维命中项可列举；全链路无哈希语义参与时 `embed_source=hash` 占比应 < 10%。

---

## 四、复审补充（2026-08-28 23:00，用户逐条代码复核确认，4 点全部合入）

1. **【最大执行风险·并入改造②验收】维度失配静默清零**：`cosine_similarity` 原实现在 `len(a) != len(b)` 时返回 **0.0 而非缺失**——改造②若只重算一侧（简历 2048 真 + JD 仍 256 哈希，或反之），semantic 维不是降级而是**全员归零**，权重归一机制还会静默拖低所有人。验收条件：**JD/简历两侧必须同批重算** + cosine 失配返回 None（缺失维）+ `embed_source` 校验后再进余弦。
2. **【并入改造①】skill 维从 Jaccard 改"JD 覆盖率 + 命中清单"**：`命中数/要求项数` 分数更合理，且天然产出"命中 4/6 项：Python、SQL…"（正是验收口径）；Jaccard 防"长 JD 惩罚"的前提在有解析短清单后消失。人才侧 skills 同步做别名归一（"python开发" vs "Python"）。
3. **【并入改造①】LLM 精算层同样没吃 jd_analysis**：`batch_match_scores` prompt 只塞 `jd_text[:2000]` 原文——断点 1 不止影响结构化链，精算主通道也没接解析产物。改造①应把 required/preferred_skills 结构化喂进 prompt：省 token、与结构化链对齐、分数更稳。
4. **【评估项】`base=0.3` 保底分压缩区分度**：`0.3 + 0.7×weighted` 零匹配也有 0.3，经 0.4 权重混入后全员兜底 +0.12。已提取为常量 `MATCH_BASE_SCORE` 并注明，暂保持 0.3（避免与旧缓存分数断裂），覆盖率维度落地后复测区分度再定是否调低至 0.1~0.15。

## 五、开工记录

**改造①（断桥修复）已完成**（本地 commit，53 Python + 28 Node 全绿）：

| 改动 | 文件 | 内容 |
|---|---|---|
| 特征规范化层（新） | `core/jd_features.py` | `build_jd_features`：解析 skills 归一（别名/后缀/占位符剔除）、experience→years_min、education→edu_min、召回词表；原文正则仅兜底 |
| skill 维换覆盖率+命中清单 | `core/matching.py` | `skill_coverage_detail`（hits/要求项数）、`normalize_skill(s)` 别名归一、`match_score_structured_detail` 返回 dims+skill_hits、新增 `jd_skills/years_min/edu_min` 直通参数 |
| cosine 失配防护（复审点 1 代码级） | `core/matching.py` | 维度失配返回 None（缺失维）而非 0.0——单侧重算不再静默清零 |
| 引擎接线 | `services/recommend_service.py` | `_shortlist`/`_rank` 改用规范化特征；LLM 精算传入结构化 skills；`FactorScores.match_detail`（source/dims/skill_hits）随 breakdown 落库+返回前端 |
| LLM 精算吃解析产物（复审点 3） | `modules/profile/llm.py` | `batch_match_scores(jd_skills=...)` → prompt 注入【岗位技能要求】块；缓存键含 skills 指纹 |
| 测试（新） | `tests/test_jd_matching.py` | 10 个用例：特征规范化/覆盖率/解析直通/失配防护/prompt 注入 |

**⚠️ 部署检查单**：① 改动改变了匹配分数语义——**上线后须清一次 `recommend_runs` 缓存**（同 R4）；② 旧缓存键不含技能指纹，清缓存前旧结果不反映新算法；③ 灰度观察 `score_breakdown.match_detail.skill_hits` 是否合理。

## 六、算法护栏 + 上线记录（2026-08-28 23:19-23:35，用户决策：新算法跑 + AI 自检后不对则回退旧算法）

**护栏结构**（commit `1b9b7ec`）：
- `BRAINX_MATCH_ALGO_V2` 开关（默认 True）：出问题 **.env 一键切回旧算法**，无需回滚代码
- `_rank` 调度器：v2 出结果后跑 `_self_check_v2`（零成本结构校验：match/activity 分值越界、结果数≠人才数、维度明细非法 → 判失败）；**v2 抛异常或自检不过 → 自动回退 `_rank_v1`（旧算法逐行为还原：原文分词+Jaccard+正则）** 并留日志
- v1 兜底输出无 `match_detail`，前端可据此区分分数来源
- 顺带修复幂等测试时序缺陷（mock 瞬间返回赌毫秒窗口 → Event 阻塞到第二次触发后，断言一字未动）

**生产上线验证**（23:35）：部署 active / health 200 → `match_algo_v2=True` 确认 → **清 recommend_runs 8 行 + recommendations**（检查单①）→ 冒烟：guest 池 539 人 compute 成功，top3/top10 正常，`match_detail.source=struct_fallback`（LLM 离线时正确走结构化降级并打标）、自检零触发回退。

**遗留观察**：生产 LLM chat 404（stepfun base 用了 `/v1` 而非 Plus Plan `/step_plan/v1`，服务器 .env 未同步）→ chat 通道熔断，精算走 `struct_fallback`。LLM 通道恢复后自动升回 `llm_struct_mix`，不影响算法护栏。老岗位（无 jd_analysis）hits 为空属预期——parse-jd 新建的岗位才有解析产物。
