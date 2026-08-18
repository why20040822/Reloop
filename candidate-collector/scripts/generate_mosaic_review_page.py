#!/usr/bin/env python3
"""Generate an HTML review page for the recovered mosaic phone numbers.

The page displays each resume PDF alongside the recovered phone, confidence, and
reasoning, so a human can quickly verify or correct each number. Verification
results can be exported as JSON directly from the browser.

Usage:
    cd candidate-collector
    python3 scripts/generate_mosaic_review_page.py \
        --report ../data/mosaic_recovery_report.json \
        --output ../data/mosaic_review.html
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>马赛克手机号恢复 · 人工复核</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f7; }
    h1 { font-size: 20px; margin-bottom: 8px; }
    .subtitle { color: #666; margin-bottom: 20px; font-size: 14px; }
    .summary { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .item { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .item-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
    .filename { font-weight: 600; font-size: 15px; word-break: break-all; }
    .phone { font-size: 24px; font-weight: 700; color: #d9534f; font-family: monospace; }
    .meta { color: #666; font-size: 13px; margin-top: 4px; }
    .pdf-container { width: 100%; height: 500px; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }
    .pdf-container iframe, .pdf-container object { width: 100%; height: 100%; border: 0; }
    .controls { margin-top: 12px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    .controls label { font-size: 14px; cursor: pointer; }
    .controls input[type="radio"] { margin-right: 4px; }
    .controls input[type="text"] { padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; width: 160px; }
    .actions { position: fixed; bottom: 20px; right: 20px; z-index: 100; }
    .btn { background: #007bff; color: #fff; border: 0; padding: 12px 20px; border-radius: 6px; font-size: 14px; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }
    .btn:hover { background: #0056b3; }
    .progress { font-size: 13px; color: #666; margin-left: 12px; }
  </style>
</head>
<body>
  <h1>马赛克手机号恢复 · 人工复核</h1>
  <p class="subtitle">请逐份核对 PDF 中的手机号，选择“正确”或填写正确号码。全部核对完成后点击右下角“导出复核结果”。</p>

  <div class="summary">
    <strong>统计：</strong>共 {{ total }} 份，已恢复 {{ recovered }} 份，待复核 {{ recovered }} 份。
  </div>

  <div id="items">
    {{ items }}
  </div>

  <div class="actions">
    <span class="progress" id="progress">已复核 0 / {{ recovered }}</span>
    <button class="btn" onclick="exportResults()">导出复核结果</button>
  </div>

  <script>
    const items = {{ items_json }};

    function updateProgress() {
      let done = 0;
      items.forEach((item, idx) => {
        const checked = document.querySelector(`input[name="verdict-${idx}"]:checked`);
        if (checked) done++;
      });
      document.getElementById('progress').textContent = `已复核 ${done} / ${items.length}`;
    }

    document.querySelectorAll('input[type="radio"]').forEach(el => {
      el.addEventListener('change', updateProgress);
    });

    function exportResults() {
      const results = items.map((item, idx) => {
        const verdict = document.querySelector(`input[name="verdict-${idx}"]:checked`);
        const corrected = document.getElementById(`correct-${idx}`).value.trim();
        return {
          file: item.file,
          recovered_phone: item.recovered_phone,
          verdict: verdict ? verdict.value : null,
          corrected_phone: corrected || null,
          confidence: item.confidence,
          reasoning: item.reasoning
        };
      });

      const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'mosaic_verification_results.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    updateProgress();
  </script>
</body>
</html>
"""


def _pdf_url(path: str) -> str:
    """Return a file:// URL for the PDF so the browser can render it."""
    abs_path = str(Path(path).resolve())
    return urllib.parse.urljoin("file://", urllib.parse.quote(abs_path))


def generate(report_path: Path, output_path: Path) -> None:
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    recovered = [r for r in report if r.get("recovered_phone")]
    items_html = []
    items_json = []

    for idx, r in enumerate(recovered):
        file_path = Path(r["file"])
        if not file_path.is_absolute():
            file_path = (report_path.parent.parent / file_path).resolve()
        pdf_url = _pdf_url(str(file_path))

        items_json.append({
            "file": str(file_path),
            "recovered_phone": r["recovered_phone"],
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
        })

        items_html.append(f"""
    <div class="item" data-idx="{idx}">
      <div class="item-header">
        <div class="filename">{file_path.name}</div>
        <div class="phone">{r['recovered_phone']}</div>
      </div>
      <div class="meta">置信度: {r['confidence']} | {r['reasoning']}</div>
      <div class="pdf-container">
        <object data="{pdf_url}" type="application/pdf">
          <p>无法渲染 PDF，请 <a href="{pdf_url}" target="_blank">直接打开</a>。</p>
        </object>
      </div>
      <div class="controls">
        <label><input type="radio" name="verdict-{idx}" value="correct"> 正确</label>
        <label><input type="radio" name="verdict-{idx}" value="incorrect"> 错误，正确号码：</label>
        <input type="text" id="correct-{idx}" placeholder="填写正确手机号">
      </div>
    </div>
        """)

    html = HTML_TEMPLATE.replace("{{ total }}", str(len(report)))
    html = html.replace("{{ recovered }}", str(len(recovered)))
    html = html.replace("{{ items }}", "\n".join(items_html))
    html = html.replace("{{ items_json }}", json.dumps(items_json, ensure_ascii=False))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated review page: {output_path}")
    print(f"Open it in a browser to verify {len(recovered)} recovered phones.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate HTML review page for recovered phones.")
    parser.add_argument("--report", type=Path, default=Path("../data/mosaic_recovery_report.json"),
                        help="Path to mosaic_recovery_report.json.")
    parser.add_argument("--output", type=Path, default=Path("../data/mosaic_review.html"),
                        help="Path to write the HTML review page.")
    args = parser.parse_args()

    if not args.report.is_file():
        print(f"Report not found: {args.report}")
        return 1

    generate(args.report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
