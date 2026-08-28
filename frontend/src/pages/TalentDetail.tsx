import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Interaction, type Talent } from "../lib/api";
import { Avatar, Empty, KeyValue, Loading, Notice, PageHeading, errorMessage } from "../components/ui";

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
      <section className="profile-card"><h2>互动记录</h2>{interactions.length ? interactions.map((item, index) => <div className="interaction-row" key={index}><i>{item.interaction_type}</i><span>{item.summary || "—"}</span><small>{new Date(item.occurred_at).toLocaleDateString()}</small></div>) : <Empty text="暂无互动记录" />}<form className="interaction-form" onSubmit={async (event) => { event.preventDefault(); if (!summary.trim()) return; await api.addInteraction(talent.id, { interaction_type: kind, summary }); setSummary(""); await load(); }}><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="call">电话</option><option value="message">消息</option><option value="interview">面试</option><option value="note">备注</option></select><input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="记录一次互动" /><button className="primary-button">保存</button></form></section></div>
  </div>;
}
