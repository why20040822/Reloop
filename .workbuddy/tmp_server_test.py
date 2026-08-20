import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
HDR = {"X-Owner-User-Id": "ou_ff894386d0ca340dcc2f7bdc53c57a81"}


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


# 1. 缓存命中岗位(商业分析师)
t0 = time.time()
d = call("/recommend/compute?position_name=%E5%95%86%E4%B8%9A%E5%88%86%E6%9E%90%E5%B8%88", "POST")
print("[cache-hit] %.2fs phase=%s cached=%s top1=%s" % (time.time() - t0, d.get("phase"), d.get("cached"), d["top3"][0]["name"] if d.get("top3") else None))

# 2. 未缓存岗位(AI研发工程师): 应秒回 preview, 然后轮询到 final
t0 = time.time()
d = call("/recommend/compute?position_name=AI%E7%A0%94%E5%8F%91%E5%B7%A5%E7%A8%8B%E5%B8%88", "POST")
print("[preview]   %.2fs phase=%s computing=%s shortlisted=%s top1=%s" % (
    time.time() - t0, d.get("phase"), d.get("computing"), d.get("shortlisted"),
    d["top3"][0]["name"] if d.get("top3") else None))
t0 = time.time()
for i in range(150):
    time.sleep(3)
    r = call("/recommend/result?position_name=AI%E7%A0%94%E5%8F%91%E5%B7%A5%E7%A8%8B%E5%B8%88")
    if r.get("status") == "done":
        print("[refined]   %.1fs top3=%s" % (time.time() - t0, [(x["name"], x["score"]) for x in r["top3"]]))
        break
    if r.get("status") == "failed":
        print("FAILED:", r.get("message"))
        break

# 3. 再次点击: 缓存命中
t0 = time.time()
d = call("/recommend/compute?position_name=AI%E7%A0%94%E5%8F%91%E5%B7%A5%E7%A8%8B%E5%B8%88", "POST")
print("[re-click]  %.2fs phase=%s cached=%s top1=%s" % (time.time() - t0, d.get("phase"), d.get("cached"), d["top3"][0]["name"] if d.get("top3") else None))
