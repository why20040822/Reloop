#!/usr/bin/env python3
"""改造②(2026-08-28): 全量向量真实化 —— 简历侧与岗位侧同批重算。

核心约束(复审点1 验收条件): JD 与简历两侧必须同批重算, 防止单侧 2048(real)
对 256(hash) 的维度失配 —— cosine 失配已改为返回 None(缺失维), 但重算的
目标是无 'hash' 残留。每条向量带 embedding_source='real', 单批失败该批
保持 hash 并跳过回填(不会误标)。

用法(服务器上):
  python scripts/recompute_embeddings.py --dry-run   # 只统计现状
  python scripts/recompute_embeddings.py             # 真执行(两侧全量)
  python scripts/recompute_embeddings.py --batch-size 32
前置: BRAINX_LLM_EMBED_BASE_URL/KEY 已指向真实 embedding 端点
      (BigModel open.bigmodel.cn/api/paas/v4, 模型 embedding-3)。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os  # noqa: E402

os.chdir(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from reloop.config import settings  # noqa: E402
from reloop.db.engine import SessionLocal  # noqa: E402
from reloop.modules.profile.llm import llm_service  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 行(调试)")
    args = ap.parse_args()

    if not llm_service._embed_online:
        raise SystemExit(
            "embed 通道不可用: 请先配置 BRAINX_LLM_EMBED_BASE_URL / "
            "BRAINX_LLM_EMBED_API_KEY (BigModel) 后重启再跑。当前只会产出哈希向量,"
            "拒绝重算(防把 hash 标成 real)。")

    db = SessionLocal()

    # ---- 现状统计 ----
    stats = db.execute(text(
        "SELECT 'talent_profiles' src, COALESCE(embedding_source,'(null)') s, "
        "COUNT(*) n, MIN(JSON_LENGTH(resume_embedding)) dim "
        "FROM talent_profiles GROUP BY s "
        "UNION ALL "
        "SELECT 'positions', COALESCE(embedding_source,'(null)'), COUNT(*), "
        "MIN(JSON_LENGTH(jd_embedding)) FROM positions GROUP BY s")).fetchall()
    print("== 重算前现状 ==")
    for src, s, n, dim in stats:
        print(f"  {src:<16} source={s:<6} rows={n:<6} min_dim={dim}")

    if args.dry_run:
        db.close()
        return

    # ---- 侧 1: talent_profiles(简历) ----
    rows = db.execute(text(
        "SELECT id, resume_text FROM talent_profiles "
        "WHERE COALESCE(embedding_source,'') != 'real' "
        "AND resume_text IS NOT NULL AND resume_text != ''"
        + (f" LIMIT {args.limit}" if args.limit else ""))).fetchall()
    _recompute(db, "talent_profiles", "resume_text", "resume_embedding", rows, args.batch_size)

    # ---- 侧 2: positions(岗位) ----
    rows = db.execute(text(
        "SELECT id, COALESCE(jd_text, position_name) AS body FROM positions "
        "WHERE COALESCE(embedding_source,'') != 'real' "
        "AND COALESCE(jd_text, position_name) IS NOT NULL "
        "AND COALESCE(jd_text, position_name) != ''"
        + (f" LIMIT {args.limit}" if args.limit else ""))).fetchall()
    _recompute(db, "positions", "body", "jd_embedding", rows, args.batch_size)

    # ---- 终态 ----
    stats = db.execute(text(
        "SELECT 'talent_profiles' src, COALESCE(embedding_source,'(null)') s, COUNT(*) n "
        "FROM talent_profiles GROUP BY s UNION ALL "
        "SELECT 'positions', COALESCE(embedding_source,'(null)'), COUNT(*) "
        "FROM positions GROUP BY s")).fetchall()
    print("== 重算后终态 ==")
    for src, s, n in stats:
        print(f"  {src:<16} source={s:<6} rows={n}")
    db.close()


def _recompute(db, table: str, body_col: str, vec_col: str, rows, batch_size: int):
    total = len(rows)
    print(f"\n[{table}] 待重算 {total} 行 (列 {vec_col})")
    done = 0
    for i in range(0, total, batch_size):
        chunk = rows[i:i + batch_size]
        vecs = llm_service.embed_batch_with_source(
            [r.body if hasattr(r, "body") else r[1] for r in chunk], batch_size)
        # 双侧重算安全阀: 仅回填 real 向量; hash 批保持原状(仍可被下轮重跑)
        pairs = [
            (row_id, vec)
            for (row_id, _body), (vec, src) in zip(chunk, vecs)
            if src == "real"
        ]
        hash_cnt = len(chunk) - len(pairs)
        if pairs:
            db.execute(text(
                f"UPDATE {table} SET {vec_col} = CAST(:vec AS JSON), "
                f"embedding_source = 'real' WHERE id = :id"),
                [{"id": rid, "vec": _to_json_str(vec)} for rid, vec in pairs])
            db.commit()
        done += len(chunk)
        print(f"  批 {i // batch_size + 1}: +{len(pairs)} real"
              + (f", {hash_cnt} hash 跳过" if hash_cnt else "")
              + f"  (进度 {done}/{total})")
    print(f"[{table}] 完成")


def _to_json_str(vec) -> str:
    import json
    return json.dumps([round(float(x), 6) for x in vec])


if __name__ == "__main__":
    main()
