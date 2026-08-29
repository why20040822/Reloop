import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type CompanySupplement, type Interaction, type Talent } from "../lib/api";
import { Avatar, Empty, KeyValue, Loading, Notice, PageHeading, errorMessage } from "../components/ui";

function ResumeTextCard({ text }: { text?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!text || !text.trim()) return null;
  return (
    <section className="profile-card">
      <h2>
        简历文本
        <button className="secondary-button" style={{ marginLeft: 10, fontSize: 11, padding: "2px 10px" }} onClick={() => setExpanded(!expanded)}>
          {expanded ? "收起" : "展开全文"}
        </button>
      </h2>
      <div style={{
        whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.7, color: "#17233d",
        background: "#f6f8fc", borderRadius: 8, padding: 12,
        maxHeight: expanded ? "none" : 220, overflow: expanded ? "visible" : "hidden",
        position: "relative",
      }}>
        {text}
      </div>
      {!expanded && <div style={{ fontSize: 11, color: "#9aa4b5", marginTop: 6 }}>内容较长，点「展开全文」查看完整内容</div>}
    </section>
  );
}

const SUPPLEMENT_LABELS: Record<string, string> = {
  notes: "备注",
  seek_status: "求职状态",
  contact_status: "联系状态",
  company: "公司",
  position: "职位",
  current_salary: "当前薪资",
  expected_salary: "期望薪资",
  base_location: "Base 地点",
  skills: "核心技能",
  last_active_at: "最近活跃",
  resume_updated_at: "简历更新时间",
  work_years: "工作年限",
  education: "学历",
};
const DIFF_LABELS: Record<string, string> = {
  notes: "备注",
  seek_status: "求职状态",
  contact_status: "联系状态",
  company: "公司",
  position: "职位",
  current_salary: "当前薪资",
  expected_salary: "期望薪资",
};

function CompanySupplementCard() {
  const { id } = useParams();
  const [data, setData] = useState<CompanySupplement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async (force = false) => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      setData(await api.getCompanySupplement(Number(id), force));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, [id]);

  if (loading && !data) return <section className="profile-card"><h2>公司人才库补充</h2><Loading /></section>;
  return (
    <section className="profile-card">
      <h2>公司人才库补充</h2>
      {error && <Notice tone="error">{error}</Notice>}
      {!data && <Empty text="暂无数据" />}
      {data && !data.found && <Empty text={data.message || "公司库中暂无此人的补充信息"} />}
      {data?.found && data.supplement && (
        <>
          {data.diff && data.diff.length > 0 && (
            <div className="interaction-row" style={{ display: "block", background: "#f0f4ff", borderRadius: 8, padding: 8, marginBottom: 10 }}>
              <b style={{ fontSize: 12 }}>公司库有更新的信息（{data.diff.length} 项）：</b>
              {data.diff.map((d) => (
                <div key={d.field} style={{ fontSize: 12, marginTop: 4 }}>
                  <i>{DIFF_LABELS[d.field] || d.field}</i>
                  <div style={{ color: "#86909c" }}>本地：{d.local || "—"}</div>
                  <div style={{ color: "#1ea06f" }}>公司库：{d.company || "—"}</div>
                </div>
              ))}
            </div>
          )}
          {data.diff && data.diff.length === 0 && (
            <div style={{ fontSize: 12, color: "#1ea06f", marginBottom: 8 }}>✓ 本地信息与公司库一致</div>
          )}
          {Object.entries(SUPPLEMENT_LABELS).map(([field, label]) => {
            const value = data.supplement?.[field];
            if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) return null;
            return <KeyValue key={field} label={label} value={Array.isArray(value) ? value.join("、") : String(value)} />;
          })}
          <div style={{ fontSize: 11, color: "#9aa4b5", marginTop: 8 }}>
            公司库共 {data.pool_total ?? "—"} 人 · 快照时间 {data.fetched_at ? new Date(data.fetched_at).toLocaleString() : "—"}
            <button className="secondary-button" style={{ marginLeft: 8, fontSize: 11, padding: "2px 8px" }} disabled={loading} onClick={() => void load(true)}>
              {loading ? "刷新中…" : "强制刷新"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export function TalentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [talent, setTalent] = useState<Talent | null>(null);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [summary, setSummary] = useState("");
  const [kind, setKind] = useState("call");
  const [error, setError] = useState("");
  const load = async () => { if (!id) return; try { const person = await api.getTalent(Number(id)); setTalent(person); setInteractions(await api.getInteractions(Number(id))); } catch (reason) { setError(errorMessage(reason)); } };
  useEffect(() => { void load(); }, [id]);
  if (!talent) return <Loading />;
  const isFollowed = talent.tags?.includes("已关注");
  return <div><button className="back-button" onClick={() => navigate("/talents")}>← 返回人才库</button><PageHeading title={talent.name} description={`${talent.company || "—"} · ${talent.position || "—"}`} action={<button className="secondary-button" onClick={async () => { await api.followTalent(talent.id); await load(); }}>{isFollowed ? "取消关注" : "特别关注"}</button>} />{error && <Notice tone="error">{error}</Notice>}
    <div className="detail-layout"><section className="profile-card"><div className="profile-header"><Avatar person={talent} size="xl" /><div><h2>{talent.name}</h2><p>{talent.base_location || "地点待补充"}</p></div></div><KeyValue label="工作年限" value={talent.work_years ? `${talent.work_years} 年` : "—"} /><KeyValue label="学历" value={talent.education} /><KeyValue label="核心技能" value={(talent.skills || []).join("、")} /><KeyValue label="备注" value={talent.notes} /></section>
      <section className="profile-card"><h2>互动记录</h2>{interactions.length ? interactions.map((item, index) => <div className="interaction-row" key={index}><i>{item.interaction_type}</i><span>{item.summary || "—"}</span><small>{new Date(item.occurred_at).toLocaleDateString()}</small></div>) : <Empty text="暂无互动记录" />}<form className="interaction-form" onSubmit={async (event) => { event.preventDefault(); if (!summary.trim()) return; await api.addInteraction(talent.id, { interaction_type: kind, summary }); setSummary(""); await load(); }}><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="call">电话</option><option value="message">消息</option><option value="interview">面试</option><option value="note">备注</option></select><input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="记录一次互动" /><button className="primary-button">保存</button></form></section>
      <CompanySupplementCard />
      <ResumeTextCard text={talent.resume_text} /></div>
  </div>;
}
