import type { Recommendation, Talent } from "./api";

export type TalentFocusRow = {
  talent: Talent;
  score?: number | null;
  reason: string;
  signal: string;
  activeAt?: string | null;
};

function validActivityTime(value?: string | null) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

export function relativeActivity(value?: string | null) {
  const activityTime = validActivityTime(value);
  if (activityTime == null) return "近期";
  const minutes = Math.max(0, Math.round((Date.now() - activityTime) / 60000));
  if (minutes < 60) return `${Math.max(1, minutes)} 分钟前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`;
  return `${Math.floor(minutes / 1440)} 天前`;
}

export function buildActivityRows(talents: Talent[], windowDays = 7): TalentFocusRow[] {
  // 「近 N 天活跃」阀门: 只保留 last_active_at 在窗口内的人才。
  // 无活跃时间/时间非法 -> 不算活跃, 不再兜底显示(否则全库都被算作"活跃")。
  const cutoff = Date.now() - windowDays * 86400_000;
  return talents
    .map((talent, index) => ({ talent, index, activityTime: validActivityTime(talent.last_active_at) }))
    .filter((row): row is { talent: Talent; index: number; activityTime: number } =>
      row.activityTime != null && row.activityTime >= cutoff)
    .sort((left, right) => right.activityTime - left.activityTime || left.index - right.index)
    .map(({ talent }) => {
      const signal = `最近 ${relativeActivity(talent.last_active_at)} 有活跃信号`;
      return { talent, score: talent.value_score, signal, reason: signal, activeAt: talent.last_active_at };
    });
}

export function buildMatchRows(matches: Recommendation[], talents: Talent[]): TalentFocusRow[] {
  const talentsById = new Map(talents.map((talent) => [talent.id, talent]));
  return matches.map((match) => {
    const talent = talentsById.get(match.talent_id) || {
      id: match.talent_id,
      name: match.name,
      company: match.company,
      position: match.position,
      base_location: match.base_location,
      work_years: match.work_years,
      education: match.education,
    };
    const reason = match.contact_reason || "综合匹配稳定，建议结合近期动态推进。";
    return { talent, score: match.score, signal: reason, reason, activeAt: talent.last_active_at };
  });
}
