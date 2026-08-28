import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { api, type Position } from "../lib/api";
import { Empty, Notice, PageHeading, errorMessage } from "../components/ui";

export function Positions() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [name, setName] = useState("");
  const [jd, setJd] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => setPositions(await api.listPositions());
  useEffect(() => { void load(); }, []);
  return <div><PageHeading title="岗位管理" /><div className="positions-layout"><section className="panel"><h2>已生效岗位</h2>{positions.length ? positions.map((position) => <article className="position-card" key={position.id}><div><strong>{position.position_name}</strong><p>{position.jd_text || "暂未填写 JD"}</p></div><button className="icon-button danger" aria-label={`删除 ${position.position_name}`} onClick={async () => { if (confirm(`删除「${position.position_name}」？`)) { await api.deletePosition(position.id); await load(); } }}><X size={16} /></button></article>) : <Empty text="还没有在招岗位。" />}</section>
    <form className="panel position-form" onSubmit={async (event) => { event.preventDefault(); if (!name.trim()) return; await api.setPosition({ position_name: name.trim(), jd_text: jd.trim() }); setName(""); setJd(""); setMessage("岗位已保存。"); await load(); }}><h2>新增或更新岗位</h2><label>岗位名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：商业分析师" required /></label><label>职位描述（JD）<textarea value={jd} onChange={(event) => setJd(event.target.value)} placeholder="填写职责、目标和关键能力" /></label><button className="primary-button"><Plus size={16} />保存岗位</button>{message && <Notice tone="success">{message}</Notice>}</form></div>
  </div>;
}
