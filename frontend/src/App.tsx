import { Navigate, Route, Routes } from "react-router-dom";
import Workbench from "./components/Workbench";
import { AuthCallback, TtcCallback, TtcConnect } from "./pages/AuthFlows";

// 蓝图 R2(2026-08-28): 页面组件已拆至 pages/，布局壳在 components/Workbench.tsx，
// 本文件只保留路由(<80 行)。
function App() {
  return <Routes>
    <Route path="/auth/callback" element={<AuthCallback />} />
    <Route path="/ttc/connect" element={<TtcConnect />} />
    <Route path="/ttc/callback" element={<TtcCallback />} />
    <Route path="*" element={<Workbench />} />
  </Routes>;
}

export default App;
