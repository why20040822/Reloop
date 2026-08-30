import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, ChevronDown, ChevronRight } from "lucide-react";
import { DirectGlassSegment } from "../components/DirectGlassSegment";
import { JDParserDrawer, type JDParserDrawerStatus } from "../components/JDParserDrawer";
import { api, type JDAnalysis, type Position, type Recommendation, type Talent } from "../lib/api";
import { positionHasParsedJd } from "../lib/jd";
import { saveThenRefreshPosition } from "../lib/positionSave";
import { buildActivityRows, buildMatchRows, relativeActivity } from "../lib/dashboard";
import { Avatar, Empty, Loading, Notice, PageHeading, errorMessage } from "../components/ui";

type DashboardMode = "activity" | "match";

// 「近 N 天活跃」阀门: 服务器实测分布 近7天≈10人/近14天≈26人/近30天≈62人(383池),
// 7 天给出一份可执行的联系清单; 调宽请同步修改下方文案。
const ACTIVITY_WINDOW_DAYS = 7;
const ACTIVITY_LIST_CAP = 20;

export function Dashboard() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<DashboardMode>("activity");
  const [positions, setPositions] = useState<Position[]>([]);
  const [selectedPosition, setSelectedPosition] = useState("");
  const [talents, setTalents] = useState<Talent[]>([]);
  const [matches, setMatches] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerStatus, setDrawerStatus] = useState<JDParserDrawerStatus>("input");
  const [drawerRawJd, setDrawerRawJd] = useState("");
  const [drawerAnalysis, setDrawerAnalysis] = useState<JDAnalysis | null>(null);
  const [drawerError, setDrawerError] = useState("");
  const [refreshWarning, setRefreshWarning] = useState("");
  const matchSegmentRef = useRef<HTMLDivElement | null>(null);
  const drawerReturnTarget = useRef<HTMLElement | null>(null);
  const drawerReturnFallback = useRef<HTMLElement | null>(null);

  useEffect(() => { void (async () => { try { const [people, roles] = await Promise.all([api.listTalents(), api.listPositions()]); setTalents(people); setPositions(roles); setSelectedPosition((value) => value || roles[0]?.position_name || ""); } catch (reason) { setError(errorMessage(reason)); } finally { setLoading(false); } })(); }, []);
  useEffect(() => {
    if (mode !== "match" || !selectedPosition) return;
    let active = true;
    const load = async () => {
      setLoading(true); setError("");
      try {
        const first = await api.recommend(selectedPosition, "match");
        if (!active) return;
        setMatches(first.top_n || []);
        if (first.computing || first.phase === "preview") {
          const poll = async () => {
            const next = await api.recommendationResult(selectedPosition, "match");
            if (!active) return;
            if (next.status === "done") setMatches(next.top_n || []);
            else if (next.status === "running") setTimeout(() => void poll(), 1800);
          };
          setTimeout(() => void poll(), 1800);
        }
      } catch (reason) { if (active) setError(errorMessage(reason)); }
      finally { if (active) setLoading(false); }
    };
    void load();
    return () => { active = false; };
  }, [mode, selectedPosition]);

  const selected = positions.find((position) => position.position_name === selectedPosition);
  const openParser = (position?: Position, opener?: HTMLElement | null) => {
    drawerReturnTarget.current = opener || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    drawerReturnFallback.current = matchSegmentRef.current?.querySelector<HTMLElement>("[data-segment-value='match']") || null;
    setDrawerRawJd(position?.jd_text || "");
    setDrawerAnalysis(null);
    setDrawerError("");
    setRefreshWarning("");
    setDrawerStatus("input");
    setDrawerOpen(true);
  };
  const parseJd = async () => {
    setDrawerStatus("parsing");
    setDrawerError("");
    try {
      setDrawerAnalysis(await api.parseJd(drawerRawJd));
      setDrawerStatus("review");
    } catch (reason) {
      setDrawerError(errorMessage(reason));
      setDrawerStatus("input");
    }
  };
  const confirmJd = async (analysis: JDAnalysis) => {
    setDrawerStatus("saving");
    setDrawerError("");
    try {
      const result = await saveThenRefreshPosition(
        () => api.setPosition({ position_name: selected?.position_name || analysis.title, jd_text: drawerRawJd, jd_analysis: analysis }),
        () => api.listPositions(),
      );
      setPositions(result.positions || [result.position, ...positions.filter((position) => position.position_name !== result.position.position_name)]);
      setSelectedPosition(result.position.position_name);
      setRefreshWarning(result.refreshError ? "岗位已保存，但岗位列表未能刷新。已使用刚保存的岗位继续匹配。" : "");
      setDrawerOpen(false);
      setMode("match");
    } catch (reason) {
      setDrawerError(errorMessage(reason));
      setDrawerStatus("review");
    }
  };

  const rows = useMemo(() => mode === "match" ? buildMatchRows(matches, talents) : buildActivityRows(talents, ACTIVITY_WINDOW_DAYS), [matches, mode, talents]);

  return <><div className="dashboard-page">
    <PageHeading title="今天最该联系谁" action={<DirectGlassSegment containerRef={matchSegmentRef} value={mode} options={[{ value: "activity", label: "活跃优先" }, { value: "match", label: "岗位匹配" }]} onChange={(value) => { const nextMode = value as DashboardMode; if (nextMode === "match" && !positionHasParsedJd(selected)) { openParser(selected); return; } setMode(nextMode); }} ariaLabel="选择人才展示方式" />} />
    {mode === "match" && <div className="match-controls"><label className="position-picker">当前岗位<span className="position-select"><select value={selectedPosition} disabled={positions.length === 0} onChange={(event) => { const nextPosition = positions.find((position) => position.position_name === event.target.value); if (!positionHasParsedJd(nextPosition)) { openParser(nextPosition, event.currentTarget); setSelectedPosition(event.target.value); setMode("activity"); return; } setSelectedPosition(event.target.value); }}>{positions.length === 0 && <option value="">暂无岗位</option>}{positions.map((position) => <option key={position.id} value={position.position_name}>{position.position_name}</option>)}</select><ChevronDown size={15} aria-hidden="true" /></span></label><button className="secondary-button" type="button" onClick={(event) => openParser(selected, event.currentTarget)}>解析新 JD</button></div>}
    {error && <Notice tone="error">{error}</Notice>}
    {refreshWarning && <Notice tone="info">{refreshWarning}</Notice>}
    <button className="talent-summary" type="button" onClick={() => navigate("/talents")}><span><small>{mode === "match" ? "岗位匹配候选" : `近 ${ACTIVITY_WINDOW_DAYS} 天活跃人才`}</small><strong>{rows.length}</strong></span><span>前往人才库 <ArrowUpRight size={16} /></span></button>
    <section className="talent-focus"><div className="section-heading"><h2>{mode === "match" ? `${selectedPosition || "岗位"}匹配人才` : "最近活跃人才"}</h2><button className="text-button" onClick={() => navigate("/talents")}>查看全部 <ChevronRight size={15} /></button></div>
      {loading ? <Loading /> : rows.length === 0 ? <Empty text={mode === "match" ? "该岗位暂无匹配结果，可先解析 JD 或稍后再试。" : `近 ${ACTIVITY_WINDOW_DAYS} 天暂无活跃人才，可前往人才库查看全部。`} /> : <div className="focus-list">{rows.slice(0, ACTIVITY_LIST_CAP).map((row, index) => <button type="button" className="focus-row" key={row.talent.id} onClick={() => navigate(`/talent/${row.talent.id}`)}><span className="rank">{String(index + 1).padStart(2, "0")}</span><span className="focus-person"><Avatar person={row.talent} size="large" /><span><strong>{row.talent.name}</strong><small>{row.talent.base_location || "地点待补充"}</small></span></span><span className="focus-current"><small>当前经历</small><strong>{row.talent.company || "—"} · {row.talent.position || "—"}</strong></span><span className="focus-experience"><small>工作经历</small><strong>{row.talent.work_years ? `${row.talent.work_years} 年 · ${row.talent.company || "—"}` : "待补充"}</strong></span><span className="focus-education"><small>毕业院校</small><strong>{row.talent.education || "待补充"}</strong></span><span className="focus-signal"><small>最新动态</small><strong>{row.reason}</strong></span><span className="focus-score"><strong>{row.score == null ? "—" : Math.round(row.score * 100)}</strong><small>{mode === "match" ? "匹配分" : "价值分"}</small></span><span className="focus-activity"><small>最近活跃</small><strong>{relativeActivity(row.activeAt)}</strong></span><ChevronRight size={16} /></button>)}</div>}
    </section>
  </div><JDParserDrawer open={drawerOpen} rawJd={drawerRawJd} status={drawerStatus} analysis={drawerAnalysis} error={drawerError} returnFocusTarget={drawerReturnTarget.current} returnFocusFallback={drawerReturnFallback.current} onRawJdChange={(value) => { setDrawerRawJd(value); setDrawerError(""); }} onParse={() => void parseJd()} onConfirm={(analysis) => void confirmJd(analysis)} onReset={() => { setDrawerStatus("input"); setDrawerAnalysis(null); setDrawerError(""); }} onClose={() => setDrawerOpen(false)} /></>;
}
