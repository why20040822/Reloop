#!/usr/bin/env node
/**
 * Reloop 前端预览服务器 (零依赖, 仅用 Node 内置模块)。
 * 伺服 webapp/ 目录, 供 Eazo 预览体系拉起。
 *   npm run dev   ->  node server.js   (默认端口 3000, 可用 PORT 覆盖)
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "webapp");
const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || "0.0.0.0";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

const server = http.createServer((req, res) => {
  try {
    let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    if (urlPath === "/") urlPath = "/index.html";
    // 防目录穿越
    const filePath = path.normalize(path.join(ROOT, urlPath));
    if (!filePath.startsWith(ROOT)) {
      res.writeHead(403).end("Forbidden");
      return;
    }
    fs.readFile(filePath, (err, data) => {
      if (err) {
        // SPA 兜底: 未命中文件时回首页 (hash 路由)
        fs.readFile(path.join(ROOT, "index.html"), (e2, home) => {
          if (e2) { res.writeHead(404).end("Not found"); return; }
          res.writeHead(200, { "Content-Type": MIME[".html"] }).end(home);
        });
        return;
      }
      const ext = path.extname(filePath).toLowerCase();
      res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" }).end(data);
    });
  } catch (e) {
    res.writeHead(500).end("Server error");
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Reloop 前端预览: http://${HOST}:${PORT}  (伺服 ${ROOT})`);
});
