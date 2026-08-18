# candidate-collector 云同步模块

把本地 SQLite 中的候选人和历史对话数据同步到阿里云 RDS PostgreSQL，作为长期统一的真相源。

## 前置条件

1. 在阿里云创建 RDS PostgreSQL 实例（建议 16 核 64G 以上如果数据量大）。
2. 创建数据库 `ttc_talent` 和用户。
3. 安装 pgvector 插件（用于后续语义检索）：
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
4. 撤销任何泄露的 AccessKey，创建新的 RAM 用户并授予最小权限（RDS 只读/写入）。

## 配置

复制 `.env.example` 为 `.env`，填写：

```bash
RDS_HOST=your-rds-host.rds.aliyuncs.com
RDS_PORT=5432
RDS_DB=ttc_talent
RDS_USER=your-db-user
RDS_PASSWORD=your-db-password
RDS_SSLMODE=require
```

**注意**：`.env` 已在 `.gitignore` 中，不会提交到 git。

## 安装依赖

```bash
cd candidate-collector
pip install -r requirements.txt
```

## 创建云端表

```bash
cd /Users/ashley/Downloads/ttc的交易系统
psql $RDS_DSN -f candidate-collector/cloud_sync/schema.sql
```

或者在第一次同步时加 `--ensure-schema`：

```bash
python -m candidate-collector.cloud_sync.sync_candidates --ensure-schema
```

## 同步候选人

```bash
# 预览（不写入）
python -m candidate-collector.cloud_sync.sync_candidates --dry-run

# 全量同步
python -m candidate-collector.cloud_sync.sync_candidates

# 只同步前 100 条测试
python -m candidate-collector.cloud_sync.sync_candidates --limit 100
```

## 同步历史对话/记忆

假设历史对话文件放在 `/path/to/conversations`，每个文件是一段对话：

```bash
python -m candidate-collector.cloud_sync.sync_memories \
    --project ttc \
    --source-dir /path/to/conversations \
    --source claude \
    --ensure-schema
```

支持的文件格式：
- `.txt` / `.md`：整个文件作为一条记忆
- `.json`：单条记录或记录数组

## 验证

```bash
psql $RDS_DSN -c "SELECT COUNT(*) FROM cloud_candidates;"
psql $RDS_DSN -c "SELECT COUNT(*) FROM memories;"
```

## 后续集成

- 在 `candidate-collector/app.py` 的 `save_candidate()` 成功后，可调用 `CloudSyncClient().upsert_candidates([row])` 实现近实时同步。
- `ttc_daemon` 可通过同一个 RDS 读取候选人，替代本地 SQLite / 飞书查询的部分场景。
