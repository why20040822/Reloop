// 综合分环形指示器(SVG 圆环)
export const ring = (score) => {
  const off = Math.round(126 * (1 - Math.max(0, Math.min(1, score))));
  return `<span class="score"><svg viewBox="0 0 52 52"><circle class="track" cx="26" cy="26" r="20"/><circle class="meter" style="stroke-dashoffset:${off}" cx="26" cy="26" r="20"/></svg>${score.toFixed(2)}</span>`;
};
