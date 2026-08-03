#!/usr/bin/env python3
"""把 CSV / JSON / Excel 导入为 Source 公司人才库 JSON。

用法：
    python3 scripts/import_source_talent.py input.csv -o data/source-candidates.json
    python3 scripts/import_source_talent.py input.xlsx -o data/source-candidates.json
    python3 scripts/import_source_talent.py input.json -o data/source-candidates.json

Excel 需要 pandas：pip install pandas openpyxl
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _norm_skills(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    return [s.strip() for s in str(value).replace("；", ";").replace(",", ";").split(";") if s.strip()]


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v for k, v in row.items()})
    return rows


def _load_json(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("candidates", [])
    return data if isinstance(data, list) else []


def _load_excel(path: Path) -> List[Dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError:
        print("Excel 导入需要 pandas + openpyxl：pip install pandas openpyxl", file=sys.stderr)
        sys.exit(1)
    df = pd.read_excel(path)
    return [row for row in df.to_dict(orient="records") if any(row.values())]


def _map_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把原始行映射为统一候选人结构。"""
    return {
        "name": str(raw.get("name", raw.get("姓名", ""))).strip(),
        "phone": str(raw.get("phone", raw.get("手机号", ""))).strip(),
        "email": str(raw.get("email", raw.get("邮箱", ""))).strip(),
        "source_url": str(raw.get("source_url", raw.get("来源链接", ""))).strip(),
        "current_title": str(raw.get("current_title", raw.get("当前职位", raw.get("title", "")))).strip(),
        "current_company": str(raw.get("current_company", raw.get("当前公司", raw.get("company", "")))).strip(),
        "location": str(raw.get("location", raw.get("地点", ""))).strip(),
        "skills": _norm_skills(raw.get("skills", raw.get("技能", ""))),
        "experience_years": str(raw.get("experience_years", raw.get("工作年限", ""))).strip(),
        "summary": str(raw.get("summary", raw.get("简介", ""))).strip(),
        "evidence": raw.get("evidence", []),
    }


def main():
    parser = argparse.ArgumentParser(description="导入 Source 公司人才库")
    parser.add_argument("input", help="输入文件：csv / xlsx / json")
    parser.add_argument("-o", "--output", default="data/source-candidates.json", help="输出 JSON 路径")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        sys.exit(1)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _load_csv(path)
    elif suffix in {".json", ".jsonl"}:
        rows = _load_json(path)
    elif suffix in {".xlsx", ".xls"}:
        rows = _load_excel(path)
    else:
        print(f"不支持的格式：{suffix}", file=sys.stderr)
        sys.exit(1)

    candidates = [_map_row(r) for r in rows if any(r.values())]
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导入 {len(candidates)} 条候选人，输出到 {out_path}")


if __name__ == "__main__":
    main()
