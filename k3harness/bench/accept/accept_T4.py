#!/usr/bin/env python3
"""T4 验收：批量入库 dry-run。

用法: python accept_T4.py <workspace>

验收标准:
  workspace/import_plan.json 必须满足:
  1. 是 JSON 数组，长度恰为 10（对应 resumes/ 下 10 份简历）。
  2. 每项含 name(str)、phone(str)、action(str) 三个字段。
  3. action 只能为 "insert" 或 "skip_duplicate"。
  4. action=skip_duplicate 的手机号集合必须恰好等于与 existing.csv 重复的 3 个手机号:
     {13901012233, 13811224455, 13722334455}；其余 7 项为 insert。
  5. 每项的 name/phone 与 resumes/ 中对应简历的实际内容一致。
"""
import json
import re
import sys
from pathlib import Path

EXPECTED_SKIP = {"13901012233", "13811224455", "13722334455"}
ALLOWED_ACTIONS = {"insert", "skip_duplicate"}


def fail(msg: str) -> None:
    print(f"[T4 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python accept_T4.py <workspace>")
    ws = Path(sys.argv[1])
    plan_path = ws / "import_plan.json"
    if not plan_path.is_file():
        fail(f"缺少 {plan_path}")

    # 从 resumes/ 提取每份简历的真实 name/phone 作为事实依据
    resume_dir = ws / "resumes"
    resumes = sorted(resume_dir.glob("*.txt"))
    if len(resumes) != 10:
        fail(f"resumes/ 下应有 10 份 txt，实际 {len(resumes)}")
    truth = {}  # phone -> name
    for p in resumes:
        text = p.read_text(encoding="utf-8")
        m_phone = re.search(r"电话[:：]\s*(1\d{10})", text)
        if not m_phone:
            fail(f"{p.name} 中找不到「电话：1xxxxxxxxxx」行")
        m_name = re.search(r"^([一-龥]{2,4})\s*$", text.splitlines()[0].strip())
        if not m_name:
            fail(f"{p.name} 首行不是姓名")
        truth[m_phone.group(1)] = m_name.group(1)

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"import_plan.json 不是合法 JSON: {e}")

    if not isinstance(plan, list):
        fail("import_plan.json 顶层必须是数组")
    if len(plan) != 10:
        fail(f"计划应有 10 项，实际 {len(plan)}")

    skip_phones = set()
    insert_phones = set()
    seen = set()
    for i, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            fail(f"第 {i} 项不是对象")
        for field in ("name", "phone", "action"):
            if field not in item:
                fail(f"第 {i} 项缺少字段 {field}")
        name, phone, action = item["name"], str(item["phone"]), item["action"]
        if not isinstance(name, str) or not name.strip():
            fail(f"第 {i} 项 name 为空")
        if action not in ALLOWED_ACTIONS:
            fail(f"第 {i} 项 action={action!r} 非法，只能是 {sorted(ALLOWED_ACTIONS)}")
        if phone in seen:
            fail(f"第 {i} 项手机号 {phone} 重复出现")
        seen.add(phone)
        if phone not in truth:
            fail(f"第 {i} 项手机号 {phone} 在 resumes/ 中不存在")
        if truth[phone] != name:
            fail(f"第 {i} 项 name={name!r} 与简历实际姓名 {truth[phone]!r} 不符")
        if action == "skip_duplicate":
            skip_phones.add(phone)
        else:
            insert_phones.add(phone)

    missing = set(truth) - seen
    if missing:
        fail(f"计划遗漏了 {len(missing)} 份简历: {sorted(missing)}")

    if skip_phones != EXPECTED_SKIP:
        fail(f"skip_duplicate 集合错误: 期望 {sorted(EXPECTED_SKIP)}, 实际 {sorted(skip_phones)}")
    if len(insert_phones) != 7:
        fail(f"insert 应有 7 项，实际 {len(insert_phones)}")

    print("[T4 OK] import_plan.json 正确：insert 7 项，skip_duplicate 3 项且判重准确")


if __name__ == "__main__":
    main()
