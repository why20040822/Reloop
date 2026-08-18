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

TENDENCY_PROMPT = (
    "分析以下与某候选人的沟通记录/备注, 判断其换工作意愿。"
    "只输出 JSON: {{\"score\": 0~1浮点, \"reason\": \"一句话理由\"}}。"
    "无明确信号时 score=0.5。\n\n记录:\n{text}"
)


# ---------------------------------------------------------------------
# 离线兜底 embedding: 字符 bigram 哈希 -> 固定维向量 (确定性, 无需 API)
# 中文文本 bigram 能捕捉字级语义关联, 供开发/测试流程跑通用。
# ---------------------------------------------------------------------
_FALLBACK_DIM = 256


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
    """OpenAI 兼容大模型封装。无 key 时走 stub 降级。"""

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.embed_model = settings.llm_embedding_model
        self._available = bool(self.api_key)

    # ---------------- 通用对话 ----------------
    def chat(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._available:
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
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("[llm] chat error: %s", e)
            return ""

    def chat_json(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        if not raw:
            return {}
        block = _extract_first_json_object(raw)
        if not block:
            return {}
        try:
            data = json.loads(block)
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    # ---------------- 向量 ----------------
    def embed(self, text: str) -> list[float]:
        """优先真实 embedding 接口; 无 key/失败时哈希向量兜底(离线可跑)。"""
        if not text:
            return []
        if self._available:
            try:
                resp = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.embed_model, "input": text[:8000]},
                    timeout=settings.llm_timeout,
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
            except Exception as e:  # noqa: BLE001
                logger.warning("[llm] embed error(用本地兜底向量): %s", e)
        return _fallback_embed(text)

    # ---------------- 业务封装 ----------------
    def structure_talent(self, text: str) -> dict:
        """原始文本 -> 标准结构化字段(LLM)。离线时返回空 dict, 由调用方兜底。"""
        if not self._available:
            return {}
        return self.chat_json(STRUCTURE_PROMPT.format(text=text[:4000]))

    def generate_contact_reason(self, talent: str, position: str,
                                jd: str = "") -> str:
        if not self._available:
            return f"近期活跃且与{position}岗位匹配, 建议尽快联系。"
        out = self.chat(REASON_PROMPT.format(talent=talent, position=position, jd=jd[:500]))
        return out or f"近期活跃且与{position}岗位匹配, 建议尽快联系。"

    def analyze_tendency(self, records: str) -> tuple[Optional[float], str]:
        """返回 (0~1 分, 理由)。离线返回 (None, 说明)。"""
        if not self._available:
            return None, "无 LLM, 未分析"
        data = self.chat_json(TENDENCY_PROMPT.format(text=records[:2000] or "无记录"))
        if not data:
            return None, "LLM 未返回有效结果"
        try:
            return float(data.get("score")), str(data.get("reason", ""))
        except (TypeError, ValueError):
            return None, "LLM 返回格式异常"


llm_service = LLMService()
