// Toast 通知(对应 shadcn sonner/toaster; 容器在 index.html #toastContainer)
export function toast(msg) {
  const box = document.getElementById("toastContainer");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  box.appendChild(el);
  // 动画 2.3s 后淡出(toastOut forwards), 2.6s 移除节点
  setTimeout(() => el.remove(), 2600);
}
