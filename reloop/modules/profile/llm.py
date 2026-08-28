"""大模型服务 (OpenAI 兼容通用接口, httpx 直连, 不依赖厂商 SDK)。

能力:
  1. chat(prompt)          通用对话(结构化提取/理由生成/倾向分析)
  2. chat_json(prompt)     对话并解析 JSON
  3. embed(text)           文本向量 (岗位匹配度用)
  4. structure_talent()    标准结构化格式提取

切换厂商只需改 .env:
  BRAINX_LLM_BASE_URL / BRAINX_LLM_API_KEY / BRAINX_LLM_MODEL
(阿里云百炼兼容模式 / DeepSeek / OpenAI / 本地 vLLM 均可)

无 API Key 时全部降级: chat 返回空, embed 用本地确定性哈希向量兜底,
保证整条流程(含余弦匹配)离线也能跑通。
"""

import hashlib
import json
import logging
import math
import re
from collections import Counter
from typing import Optional

import httpx

from reloop.config import settings

logger = logging.getLogger(__name__)

# 标准结构化格式提取 Prompt (输出 key 与 sync/normalizer.STANDARD_KEYS 对齐)
STRUCTURE_PROMPT = (
    "你是人才画像抽取助手。从下面的人才原始文本中抽取结构化信息, 严格输出 JSON, 字段: "
    "name(姓名), base_location(base地点), company(公司), position(职位), "
    "work_years(经验年限, 数字, 单位年), education(学历: 博士/硕士/本科/大专/其他), "
    "skills(技能数组), company_tier(大厂/独角兽/上市公司/一般), "
    "tendency_score(换工作意愿0~1, 无信号填0.5), summary(一句话画像)。"
    "无法判断的字段填 null。\n\n文本:\n{text}"
)

REASON_PROMPT = (
    "你是猎头触达破冰语撰写助手。基于候选人背景与当前岗位, "
    "写一句 30 字以内的破冰联系理由, 直接输出文本, 不要解释。\n"
    "候选人: {talent}\n当前岗位: {position}\nJD摘要: {jd}"
)

BATCH_MATCH_PROMPT = (
    "你是招聘匹配评估专家。评估候选人简历与目标岗位的整体匹配度。\n\n"
    "【目标岗位】\n{position_name}\n\n"
    "【JD】\n{jd_text}\n\n"
    "【候选人列表】\n{candidates}\n\n"
    "评分规则(0~1浮点):\n"
    "- 0.9-1.0: 高度匹配, 核心能力/经验高度对齐, 可快速上手\n"
    "- 0.7-0.9: 强相关, 大部分要求满足, 少量适应期\n"
    "- 0.5-0.7: 部分匹配, 有相关背景但需培训/过渡\n"
    "- 0.3-0.5: 弱匹配, 核心技能有明显差距\n"
    "- 0.0-0.3: 基本不匹配\n\n"
    "注意: JD 长度不影响基准。短 JD 不代表全员高分, 长 JD 也不代表全员低分, "
    "只看候选人背景与岗位要求的实质匹配程度。\n\n"
    "严格只输出 JSON 数组:\n"
    '[{{"idx": 1, "score": 0.85}}, {{"idx": 2, "score": 0.62}}, ...]'
)


# ---------------------------------------------------------------------
# 离线兜底 embedding: 字符 bigram 哈希 -> 固定维向量 (确定性, 无需 API)
# 中文文本 bigram 能捕捉字级语义关联, 供开发/测试流程跑通用。
# ---------------------------------------------------------------------
_FALLBACK_DIM = 256


def _extract_first_json(raw: str) -> str:
    """从 LLM 输出中稳健提取【首个完整 JSON 值】(对象 {...} 或数组 [...]）。

    修复两类问题:
      - 原贪婪正则 \\{.*\\} 会从第一个 { 吃到最后一个 }(多块/尾随文本时抓错);
      - 原实现只认对象, 模型返回纯数组 [..] 时直接返回空, 导致 batch_match_scores 失效。
    做法: 先剥 markdown 代码围栏, 再取首个 { 或 [ 作为起点, 括号计数(跳过字符串内括号与转义)
    截取第一个平衡片段。
    """
    if not raw:
        return ""
    s = raw.strip()
    # 剥 ```json ... ``` / ``` ... ``` 围栏
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    cand = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not cand:
        return ""
    start = min(cand)
    open_ch, close_ch = ("{", "}") if s[start] == "{" else ("[", "]")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return ""  # 括号不平衡: 视为无有效 JSON


def _fallback_embed(text: str) -> list[float]:
    vec = [0.0] * _FALLBACK_DIM
    if not text:
        return vec
    cleaned = re.sub(r"\s+", "", text)
    grams = [cleaned[i : i + 2] for i in range(len(cleaned) - 1)] or [cleaned]
    for g, c in Counter(grams).items():
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        vec[h % _FALLBACK_DIM] += c
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-9:
        vec = [x / norm for x in vec]
    return vec


class LLMService:
    """OpenAI 兼容大模型封装。无 key 时走 stub 降级。

    熔断: 连续 _CIRCUIT_FAIL_LIMIT 次网络/接口失败后自动进入离线模式,
    后续调用直接走降级, 不再逐次网络往返——
    避免 LLM 服务不可用时拖慢同步/推荐(如 378 条人才每条都等一次超时)。

    chat 与 embed 使用【独立】熔断: embedding 接口不可用(如 step_plan 推理
    通道不支持 embeddings)只会影响向量维度降级, 不会拖垮 chat/匹配度计算。
    """

    _CIRCUIT_FAIL_LIMIT = 3

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.embed_model = settings.llm_embedding_model
        self._has_key = bool(self.api_key)
        # 独立熔断: chat(匹配/抽取) 与 embed(向量) 互不影响
        self._chat_fail_streak = 0
        self._chat_circuit_open = False
        self._embed_fail_streak = 0
        self._embed_circuit_open = False

    # ---------------- 熔断辅助 (chat) ----------------
    def _chat_note_failure(self) -> None:
        self._chat_fail_streak += 1
        if self._chat_fail_streak >= self._CIRCUIT_FAIL_LIMIT:
            self._chat_circuit_open = True
            logger.warning("[llm] chat 连续失败 %d 次, 熔断进入离线模式(后续用本地降级)", self._chat_fail_streak)

    def _chat_note_success(self) -> None:
        self._chat_fail_streak = 0

    @property
    def _chat_online(self) -> bool:
        return self._has_key and not self._chat_circuit_open

    # ---------------- 熔断辅助 (embed) ----------------
    def _embed_note_failure(self) -> None:
        self._embed_fail_streak += 1
        if self._embed_fail_streak >= self._CIRCUIT_FAIL_LIMIT:
            self._embed_circuit_open = True
            logger.warning("[llm] embed 连续失败 %d 次, 熔断改用本地哈希向量", self._embed_fail_streak)

    def _embed_note_success(self) -> None:
        self._embed_fail_streak = 0

    @property
    def _embed_online(self) -> bool:
        return self._has_key and not self._embed_circuit_open

    # ---------------- 通用对话 ----------------
    def chat(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._chat_online:
            return ""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0.2},
                timeout=settings.llm_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            self._chat_note_success()
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("[llm] chat error: %s", e)
            self._chat_note_failure()
            return ""

    def chat_json(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        if not raw:
            return {}
        block = _extract_first_json(raw)
        if not block:
            return {}
        try:
            data = json.loads(block)
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def chat_json_list(self, prompt: str) -> list:
        """同 chat_json, 但返回 JSON 数组(用于批量评分等返回 [..] 的提示)。"""
        raw = self.chat(prompt)
        if not raw:
            return []
        block = _extract_first_json(raw)
        if not block:
            return []
        try:
            data = json.loads(block)
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []

    # ---------------- 向量 ----------------
    def embed(self, text: str) -> list[float]:
        """优先真实 embedding 接口; 无 key/失败/通道不支持时哈希向量兜底(离线可跑)。

        注意: 部分厂商通道(如 stepfun step_plan 推理通道)不提供 embeddings,
        此时会快速 404 -> 熔断 -> 之后直接走本地哈希向量, 不再每次网络往返。
        """
        if not text:
            return []
        if self._embed_online:
            try:
                resp = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.embed_model, "input": text[:8000]},
                    timeout=settings.llm_timeout,
                )
                resp.raise_for_status()
                self._embed_note_success()
                return resp.json()["data"][0]["embedding"]
            except Exception as e:  # noqa: BLE001
                logger.warning("[llm] embed error(用本地兜底向量): %s", e)
                self._embed_note_failure()
        return _fallback_embed(text)

    # ---------------- 业务封装 ----------------
    def structure_talent(self, text: str) -> dict:
        """原始文本 -> 标准结构化字段(LLM)。离线时返回空 dict, 由调用方兜底。"""
        if not self._chat_online:
            return {}
        return self.chat_json(STRUCTURE_PROMPT.format(text=text[:4000]))

    def generate_contact_reason(self, talent: str, position: str,
                                jd: str = "") -> str:
        if not self._chat_online:
            return f"近期活跃且与{position}岗位匹配, 建议尽快联系。"
        out = self.chat(REASON_PROMPT.format(talent=talent, position=position, jd=jd[:500]))
        return out or f"近期活跃且与{position}岗位匹配, 建议尽快联系。"

    # ---------------- 岗位语义相似度(职位匹配 v2) ----------------
    def title_similarity(self, jd_position: str,
                         talent_positions: list[str],
                         batch_size: int = 40) -> dict[str, float]:
        """目标岗位 vs 一批候选人职位的语义相似度(0~1), 供匹配度 title 维度用。

        解决字面匹配失灵: "AI研发工程师" 与 "算法工程师" bigram 相似度≈0,
        但语义上是同族岗位, 应得 0.7+ —— 由 LLM 批量推理。
        - 去重后分批调用(每批 batch_size 个职位), 控制单次 prompt 长度
        - 进程内缓存 (jd_position, talent_position) -> score, 岗位不变时零重复调用
        - 无 key / 调用失败返回空 dict, 调用方降级到字面相似度
        """
        if not self._chat_online or not jd_position:
            return {}
        uniq = sorted({p.strip() for p in talent_positions if p and p.strip()})
        result: dict[str, float] = {}
        todo: list[str] = []
        for p in uniq:
            cached = _TITLE_SIM_CACHE.get((jd_position, p))
            if cached is not None:
                result[p] = cached
            else:
                todo.append(p)
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            prompt = (
                "你是招聘领域的岗位相似度评估专家。评估每个候选人当前职位与目标岗位的"
                "语义相关程度(考虑职责、技能栈、行业惯例, 允许跨词面匹配)。\n"
                f"目标岗位: {jd_position}\n"
                "评分标准: 1.0=同一岗位; 0.7~0.9=同族岗位(如 算法工程师 对 AI研发工程师, "
                "HRBP 对 组织发展专家); 0.4~0.6=部分相关(有技能交集或同大类职能); "
                "0.1~0.3=弱相关; 0=完全不相关。\n"
                "严格只输出一个 JSON 对象, key=候选人职位原文, value=0~1的小数(保留两位)。\n"
                f"候选人职位列表: {json.dumps(batch, ensure_ascii=False)}"
            )
            data = self.chat_json(prompt)
            if not isinstance(data, dict):
                logger.warning("[llm] title_similarity batch invalid, len=%d", len(batch))
                continue
            for p in batch:
                raw = data.get(p)
                try:
                    score = float(raw)
                except (TypeError, ValueError):
                    continue
                score = max(0.0, min(1.0, score))
                result[p] = score
                _TITLE_SIM_CACHE[(jd_position, p)] = score
        return result

    def batch_match_scores(self, position_name: str, jd_text: str,
                           candidates: list[dict], batch_size: int = 20) -> dict[int, float]:
        """批量 JD vs 简历匹配度评分(主通道)。

        candidates: [{"idx": 1, "name": "...", "position": "...", "company": "...",
                      "skills": [...], "work_years": N, "education": "..."}, ...]
        返回 {idx: score}。LLM 不可用时返回空 dict(调用方降级到结构化)。
        """
        if not self._chat_online or not candidates:
            return {}
        result: dict[int, float] = {}
        todo: list[dict] = []
        for c in candidates:
            cached = _MATCH_SCORE_CACHE.get((position_name, jd_text, c.get("idx")))
            if cached is not None:
                result[c["idx"]] = cached
            else:
                todo.append(c)
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            lines = []
            for j, c in enumerate(batch, start=1):
                skills = ", ".join(c.get("skills") or [])
                lines.append(
                    f"{j}. {c.get('name', '')}: {c.get('position', '')} @ {c.get('company', '')}, "
                    f"技能: {skills}, {c.get('work_years', '?')}年经验, {c.get('education', '?')}"
                )
            prompt = BATCH_MATCH_PROMPT.format(
                position_name=position_name,
                jd_text=jd_text[:2000] if jd_text else "",
                candidates="\n".join(lines),
            )
            data = self.chat_json_list(prompt)
            if not isinstance(data, list):
                logger.warning("[llm] batch_match invalid, len=%d", len(batch))
                continue
            for item in data:
                try:
                    idx = int(item.get("idx"))
                    score = float(item.get("score"))
                except (TypeError, ValueError):
                    continue
                score = max(0.0, min(1.0, score))
                result[idx] = score
                _MATCH_SCORE_CACHE[(position_name, jd_text, idx)] = score
        # M1(2026-08-28 审计采纳): 已删除"分位校准"(把本批分数线性映射到 [0.1,0.9])。
        # 那是批内相对归一化——同一候选人在强批次被压低、弱批次被抬高, 跨岗位/跨时间
        # 不可比, 与活跃度已废除的 min-max 同病。绝对评分锚定由 BATCH_MATCH_PROMPT
        # 内的 0.0~1.0 分档规则负责。
        return result


# 进程内批量匹配缓存: (position_name, jd_text, candidate_idx) -> score
_MATCH_SCORE_CACHE: dict[tuple[str, str, int], float] = {}


# 进程内岗位相似度缓存
# 岗位不变/人才库不变时, 二次推荐不再产生 LLM 调用
_TITLE_SIM_CACHE: dict[tuple[str, str], float] = {}


llm_service = LLMService()
