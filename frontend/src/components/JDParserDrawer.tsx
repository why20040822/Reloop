import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { X } from "lucide-react";
import { cycleFocus, restoreFocus } from "../lib/drawerFocus";
import { analysisToDraft, draftToAnalysis, type JDAnalysisDraft } from "../lib/jd";
import type { JDAnalysis } from "../lib/api";
import { canParseJd, mergeJdImages, readJdImage, removeJdImage, validateJdImageFiles, type JdImage } from "../lib/jdImages";

export type JDParserDrawerStatus = "input" | "parsing" | "review" | "saving";

type Props = {
  open: boolean;
  rawJd: string;
  images: JdImage[];
  status: JDParserDrawerStatus;
  analysis: JDAnalysis | null;
  error: string;
  onRawJdChange: (value: string) => void;
  onImagesChange: Dispatch<SetStateAction<JdImage[]>>;
  onParse: () => void;
  onConfirm: (analysis: JDAnalysis) => void;
  onReset: () => void;
  onClose: () => void;
  returnFocusTarget: HTMLElement | null;
  returnFocusFallback: HTMLElement | null;
};

const fields: Array<{ key: keyof JDAnalysis; label: string; multiline?: boolean }> = [
  { key: "company_name", label: "招聘公司" },
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

function focusableElements(container: HTMLElement | null) {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter((element) => !element.hasAttribute("hidden"));
}

export function JDParserDrawer({ open, rawJd, images, status, analysis, error, onRawJdChange, onImagesChange, onParse, onConfirm, onReset, onClose, returnFocusTarget, returnFocusFallback }: Props) {
  const drawerRef = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const [draft, setDraft] = useState<JDAnalysisDraft | null>(null);
  const [imageError, setImageError] = useState("");
  const busy = status === "parsing" || status === "saving";
  const reviewing = status === "review" || status === "saving";

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      queueMicrotask(() => {
        const initialFocus = drawerRef.current?.querySelector<HTMLElement>("[data-jd-initial-focus]:not([disabled])");
        (initialFocus || focusableElements(drawerRef.current)[0] || drawerRef.current)?.focus();
      });
    } else if (wasOpen.current) {
      wasOpen.current = false;
      restoreFocus(returnFocusTarget, returnFocusFallback);
    }
  }, [open, returnFocusFallback, returnFocusTarget, status]);

  useEffect(() => {
    if (analysis) setDraft(analysisToDraft(analysis));
  }, [analysis]);

  useEffect(() => { setImageError(""); }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) { onClose(); return; }
      if (event.key !== "Tab") return;
      const targets = focusableElements(drawerRef.current);
      if (!targets.length) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }
      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const isOutsideDrawer = !drawerRef.current?.contains(active);
      const isWrappingForward = !event.shiftKey && (isOutsideDrawer || active === targets[targets.length - 1]);
      const isWrappingBackward = event.shiftKey && (isOutsideDrawer || active === targets[0]);
      if (isWrappingForward || isWrappingBackward) {
        event.preventDefault();
        cycleFocus(targets, active, event.shiftKey);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open) return null;

  const updateDraft = (key: keyof JDAnalysis, value: string) => setDraft((current) => current ? { ...current, [key]: value } : current);
  const close = () => { if (!busy) onClose(); };
  const addFiles = async (files: File[]) => {
    const { accepted, errors } = validateJdImageFiles(files, images.length);
    setImageError(errors.join(" "));
    if (!accepted.length) return;
    try {
      const decodedImages = await Promise.all(accepted.map((file) => readJdImage(file as File)));
      onImagesChange((current) => mergeJdImages(current, decodedImages));
    } catch (reason) {
      setImageError(reason instanceof Error ? reason.message : "图片无法读取，请重试。");
    }
  };

  return <div className="jd-drawer-layer">
    <button className="jd-drawer-backdrop" type="button" aria-label="关闭 JD 解析" onClick={close} disabled={busy} />
    <aside className="jd-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="jd-drawer-title" tabIndex={-1}>
      <header className="jd-drawer-header"><div><p>岗位匹配</p><h2 id="jd-drawer-title">解析职位描述</h2></div><button className="icon-button" type="button" aria-label="关闭 JD 解析" onClick={close} disabled={busy}><X size={18} /></button></header>
      <div className="jd-drawer-body">
        {error && <p className="notice error" role="alert">{error}</p>}
        {!reviewing ? <div className="jd-input-stage">{images.length > 0 && <div className="jd-image-previews">{images.map((image) => <figure key={image.id} className="jd-image-preview"><img src={image.data_url} alt={image.filename} /><button className="icon-button" type="button" aria-label={`移除 ${image.filename}`} onClick={() => onImagesChange((current) => removeJdImage(current, image.id))}><X size={15} /></button><figcaption>{image.filename}</figcaption></figure>)}</div>}<label className="jd-raw-field">职位描述（JD）<textarea data-jd-initial-focus value={rawJd} disabled={busy} onChange={(event) => onRawJdChange(event.target.value)} onPaste={(event) => { const pasted = Array.from(event.clipboardData.files); if (pasted.length) { event.preventDefault(); void addFiles(pasted); } }} placeholder="粘贴完整的职责、任职资格、地点与团队信息" /><small>系统会生成可编辑的结构化岗位要求。</small></label><div className="jd-image-controls"><small>需要识别图片时，请直接将截图粘贴到上方输入框，最多 4 张，每张不超过 8 MiB。</small></div>{imageError && <p className="notice error" role="alert">{imageError}</p>}</div>
          : <><div className="jd-review-heading"><div><strong>核对解析结果</strong><small>列表字段每行一项，可直接修改。</small></div><button className="text-button" type="button" onClick={() => { setImageError(""); onReset(); }} disabled={busy}>解析新 JD</button></div>{draft && <div className="jd-field-grid">{fields.map(({ key, label, multiline }, index) => <label key={key}>{label}{multiline ? <textarea data-jd-initial-focus={index === 0 ? true : undefined} value={draft[key]} disabled={busy} onChange={(event) => updateDraft(key, event.target.value)} /> : <input data-jd-initial-focus={index === 0 ? true : undefined} value={draft[key]} disabled={busy} onChange={(event) => updateDraft(key, event.target.value)} />}</label>)}</div>}</>}
      </div>
      <footer className="jd-drawer-footer">{reviewing ? <><button className="secondary-button" type="button" onClick={close} disabled={busy}>取消</button><button className="primary-button" type="button" disabled={busy || !draft} onClick={() => draft && onConfirm(draftToAnalysis(draft))}>{status === "saving" ? "正在保存…" : "确认并开始匹配"}</button></> : <><button className="secondary-button" type="button" onClick={close} disabled={busy}>取消</button><button className="primary-button" type="button" disabled={busy || !canParseJd(rawJd, images)} onClick={onParse}>{status === "parsing" ? "正在解析…" : "解析 JD"}</button></>}</footer>
    </aside>
  </div>;
}
