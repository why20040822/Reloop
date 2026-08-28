import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { api, type Talent } from "../lib/api";
import { Avatar, Empty, Notice, PageHeading, number, errorMessage } from "../components/ui";

export function TalentList() {
  const location = useLocation();
  const navigate = useNavigate();
  const followed = new URLSearchParams(location.search).get("filter") === "followed";
  const [keyword, setKeyword] = useState("");
  const [talents, setTalents] = useState<Talent[]>([]);
  const [error, setError] = useState("");
  const load = async (next = keyword) => { try { setError(""); setTalents(followed ? await api.listFollowed() : await api.listTalents(next)); } catch (reason) { setError(errorMessage(reason)); } };
  useEffect(() => { void load(""); }, [followed]);
  return <div><PageHeading title={followed ? "特别关注" : "人才库"} />{error && <Notice tone="error">{error}</Notice>}
    {!followed && <form className="search-field" onSubmit={(event) => { event.preventDefault(); void load(); }}><Search size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索人才、公司或职位" /><button className="primary-button">搜索</button></form>}
    <div className="talent-table"><div className="talent-table-head"><span>人才</span><span>当前经历</span><span>核心技能</span><span>价值分</span></div>{talents.map((talent) => <button type="button" className="talent-row" key={talent.id} onClick={() => navigate(`/talent/${talent.id}`)}><span className="person-cell"><Avatar person={talent} /><span><strong>{talent.name}</strong><small>{talent.base_location || "—"} · {talent.work_years || "—"} 年</small></span></span><span>{talent.company || "—"}<small>{talent.position || ""}</small></span><span className="tag-list">{(talent.skills || []).slice(0, 3).map((skill) => <i key={skill}>{skill}</i>)}</span><strong>{number(talent.value_score)}</strong></button>)}{!talents.length && <Empty text="没有找到符合条件的人才。" />}</div>
  </div>;
}
