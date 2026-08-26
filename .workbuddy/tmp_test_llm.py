import os, sys
os.chdir("F:/ttc/Reloop")
sys.path.insert(0, "F:/ttc/Reloop")
import logging
logging.basicConfig(level=logging.ERROR)

from reloop.config import settings
from reloop.modules.profile.llm import llm_service, _fallback_embed

print("BASE_URL:", settings.llm_base_url)
print("MODEL:", settings.llm_model)
print("EMBED_MODEL:", settings.llm_embedding_model)
print("TIMEOUT:", settings.llm_timeout)

# 1) chat 应真正可用 (step-3.7-flash)
print("\n[1] chat test ...")
r = llm_service.chat("用一句中文介绍你自己, 不超过20字。")
print("    chat ->", repr(r[:60]))
print("    chat_online after:", llm_service._chat_online, "| chat_fail_streak:", llm_service._chat_fail_streak)

# 2) embed 连续失败应只熔断 embed, 不拖垮 chat
print("\n[2] embed (step_plan 无 embeddings, 预期快速降级) ...")
v1 = llm_service.embed("海外社区运营 用户增长")
v2 = llm_service.embed("海外社区运营 用户增长")
print("    embed dim:", len(v1), "| is_hash_fallback:", v1 == _fallback_embed("海外社区运营 用户增长"))
print("    embed_circuit_open:", llm_service._embed_circuit_open)
print("    chat_online STILL:", llm_service._chat_online, "(必须 True, 不能因 embed 失败被拖垮)")

# 3) 再次 chat, 确认仍在线
print("\n[3] chat again after embed failures ...")
r2 = llm_service.chat("回复两个字: 正常")
print("    chat ->", repr(r2[:40]), "| chat_online:", llm_service._chat_online)

assert llm_service._chat_online is True, "BUG: chat 被 embed 失败拖垮!"
assert len(v1) == 256, "embed 降级维度异常"
print("\nALL CHECKS PASSED")
