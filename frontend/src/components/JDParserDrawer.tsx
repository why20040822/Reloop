import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { analysisToDraft, draftToAnalysis, type JDAnalysisDraft } from "../lib/jd";
import type { JDAnalysis } from "../lib/api";

export type JDParserDrawerStatus = "input" | "parsing" | "review" | "saving";

type Props = {
  open: boolean;
  rawJd: string;
  status: JDParserDrawerStatus;
  analysis: JDAnalysis | null;
  error: string;
  onRawJdChange: (value: string) => void;
  onParse: () => void;
  onConfirm: (analysis: JDAnalysis) => void;
  onReset: () => void;
  onClose: () => void;
};

const fields: Array<{ key: keyof JDAnalysis; label: string; multiline?: boolean }> = [
  { key: "title", label: "岗位名称" },
  { key: "summary", label: "岗位概述", multiline: true },
  { key: "responsibilities", label: "工作职责", multiline: true },
  { key: "required_skills", label: "必备技能", multiline: true },
  { key: "preferred_skills", label: "加分技能", multiline: true },
  { key: "experience", label: "经验要求" },
  { key: "education", label: "学历要求" },
  { key: "location", label: "工作地点" },
  { key: "industry_keywords", label: "行业关键词", multiline: true },
  { key: "salary_range", label: "薪资范围" },
  { key: "team_size", label: "团队规模" },
  { key: "reporting_line", label: "汇报对象" },
  { key: "language_requirements", label: "语言要求", multiline: true },
];

export function JDParserDrawer({ open, rawJd, status, analysis, error, onRawJdChange, onParse, onConfirm, onReset, onClose }: Props) {
  const previousFocus = useRef<HTMLElement | null>(null);
  const [draft, setDraft] = useState<JDAnalysisDraft | null>(null);
  const busy = status === "parsing" || status === "saving";
  const reviewing = status === "review" || status === "saving";

  useEffect(() => {
    if (open) previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    else previousFocus.current?.focus();
  }, [open]);

  useEffect(() => {
    if (analysis) setDraft(analysisToDraft(analysis));
  }, [analysis]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open) return null;

  const updateDraft = (key: keyof JDAnalysis, value: string) => setDraft((current) => current ? { ...current, [key]: value } : current);
  const close = () => { if (!busy) onClose(); };

  return <div className="jd-drawer-layer">
    <button className="jd-drawer-backdrop" type="button" aria-label="关闭 JD 解析" onClick={close} disabled={busy} />
    <aside className="jd-drawer" role="dialog" aria-modal="true" aria-labelledby="jd-drawer-title">
      <header className="jd-drawer-header"><div><p>岗位匹配</p><h2 id="jd-drawer-title">解析职位描述</h2></div><button className="icon-button" type="button" aria-label="关闭 JD 解析" onClick={close} disabled={busy}><X size={18} /></button></header>
      <div className="jd-drawer-body">
        {error && <p className="notice error" role="alert">{error}</p>}
        {!reviewing ? <label className="jd-raw-field">职位描述（JD）<textarea value={rawJd} disabled={busy} onChange={(event) => onRawJdChange(event.target.value)} placeholder="粘贴完整的职责、任职资格、地点与团队信息" autoFocus /><small>系统会生成可编辑的结构化岗位要求。</small></label>
          : <><div className="jd-review-heading"><div><strong>核对解析结果</strong><small>列表字段每行一项，可直接修改。</small></div><button className="text-button" type="button" onClick={onReset} disabled={busy}>解析新 JD</button></div>{draft && <div className="jd-field-grid">{fields.map(({ key, label, multiline }) => <label key={key}>{label}{multiline ? <textarea value={draft[key]} disabled={busy} onChange={(event) => updateDraft(key, event.target.value)} /> : <input value={draft[key]} disabled={busy} onChange={(event) => updateDraft(key, event.target.value)} />}</label>)}</div>}</>}
      </div>
      <footer className="jd-drawer-footer">{reviewing ? <><button className="secondary-button" type="button" onClick={close} disabled={busy}>取消</button><button className="primary-button" type="button" disabled={busy || !draft} onClick={() => draft && onConfirm(draftToAnalysis(draft))}>{status === "saving" ? "正在保存…" : "确认并开始匹配"}</button></> : <><button className="secondary-button" type="button" onClick={close} disabled={busy}>取消</button><button className="primary-button" type="button" disabled={busy || !rawJd.trim()} onClick={onParse}>{status === "parsing" ? "正在解析…" : "解析 JD"}</button></>}</footer>
    </aside>
  </div>;
}
