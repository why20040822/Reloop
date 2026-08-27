// 全局搜索遮罩(对应 shadcn sidebar/command: Cmd+K 唤起, ↑↓ 选择, ↵ 打开, esc 关闭)
// DOM 已在 index.html(#searchOverlay); 数据走 provider(后端支持 姓名/公司/职位 关键词)
import { api } from "../../data/provider.js";
import { t } from "../state.js";
import { esc } from "../utils/dom.js";

let _sel = 0;
let _results = [];
let _debounce = null;

function overlay() { return document.getElementById("searchOverlay"); }
function input() { return document.getElementById("searchInput"); }
function resultsBox() { return document.getElementById("searchResults"); }

export function openSearch() {
  overlay()?.classList.add("open");
  _sel = 0;
  if (input()) { input().value = ""; input().focus(); }
  renderResults([]);
}

export function closeSearch() { overlay()?.classList.remove("open"); }

function renderResults(list) {
  _results = list;
  _sel = Math.min(_sel, Math.max(0, list.length - 1));
  const box = resultsBox();
  if (!box) return;
  box.innerHTML = list.length
    ? list.map((tp, i) => `
      <button class="search-result-item ${i === _sel ? "selected" : ""}" data-id="${tp.id}">
        <span><strong>${esc(tp.name)}</strong><small class="hint">${esc(tp.company || "")} · ${esc(tp.position || "")}</small></span>
      </button>`).join("")
    : `<div class="hint" style="padding:12px">${t("search_ph")}</div>`;
  box.querySelectorAll(".search-result-item").forEach((el) => el.addEventListener("click", () => openResult(Number(el.dataset.id))));
}

function openResult(id) {
  closeSearch();
  location.hash = `#/talent/${id}`;
}

async function doSearch(kw) {
  if (!kw) { renderResults([]); return; }
  const list = await api.listTalents(kw).catch(() => []);
  renderResults((list || []).slice(0, 8));
}

export function initSearch() {
  document.getElementById("searchBackdrop")?.addEventListener("click", closeSearch);
  document.getElementById("searchCloseBtn")?.addEventListener("click", closeSearch);

  input()?.addEventListener("input", (e) => {
    clearTimeout(_debounce);
    const kw = e.target.value.trim();
    _debounce = setTimeout(() => doSearch(kw), 250);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      overlay()?.classList.contains("open") ? closeSearch() : openSearch();
      return;
    }
    if (!overlay()?.classList.contains("open")) return;
    if (e.key === "Escape") closeSearch();
    else if (e.key === "ArrowDown") { e.preventDefault(); _sel = Math.min(_sel + 1, _results.length - 1); renderResults(_results); }
    else if (e.key === "ArrowUp") { e.preventDefault(); _sel = Math.max(_sel - 1, 0); renderResults(_results); }
    else if (e.key === "Enter" && _results[_sel]) openResult(Number(_results[_sel].id));
  });
}
