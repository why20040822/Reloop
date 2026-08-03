FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（Playwright Chromium 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium
RUN python3 -m playwright install chromium

# 复制代码
COPY . .

# 数据持久化目录
RUN mkdir -p /data
ENV TTC_DATA_DIR=/data

EXPOSE 8766

CMD ["python3", "-m", "ttc_daemon.main"]
