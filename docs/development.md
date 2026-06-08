# Development

## Local Dev Stack

推荐使用 Docker Compose，并通过 `bin/local-dev.sh` 统一启动和停止本地服务。

```bash
bin/local-dev.sh start
bin/local-dev.sh status
bin/local-dev.sh logs
bin/local-dev.sh stop
```

默认本地地址：

- Web: `http://localhost:18110/`
- Backend health: `http://localhost:18111/health`
- PostgreSQL: `localhost:18112`
- 本地默认登录密码：`12345`

本地前端使用根路径 `/`。测试环境为了和同一台服务器上的其他项目共存，公网访问路径使用 `/test-benchmark/`。

## Database

项目数据库使用 PostgreSQL。后端运行时必须通过 `DATABASE_URL` 指向 PostgreSQL，不使用 SQLite 作为应用运行数据库。

本地 Docker Compose 应提供 PostgreSQL 服务，并通过 volume 持久化数据。建议默认连接信息：

```text
Host: postgres
Port: 5432
Database: test_benchmark
User: test_benchmark
Password: test_benchmark
```

本地如需从宿主机连接数据库，可通过 Compose 映射的宿主机端口访问。端口应避开现有项目，建议使用 `18112`。

## Manual Component Commands

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://test_benchmark:test_benchmark@localhost:18112/test_benchmark
export BENCHMARK_DATA_DIR=../data/benchmarks
export TEST_BENCHMARK_AUTH_PASSWORD=12345
export TEST_BENCHMARK_AUTH_SECRET=test-benchmark-local-secret
uvicorn app.main:app --reload --port 18111
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
pnpm build
```

手动启动时仍需要先提供 PostgreSQL，并设置 `DATABASE_URL`。

## Benchmark Data

原始题集资料位于：

```text
data/benchmarks/
```

这些资料不提交仓库。题集可在网页中通过 JSONL 文件手动导入。当前已验证格式来自：

```text
data/benchmarks/custom_medical_eval_sets/*.jsonl
```

已确认格式：

- `医疗文本推理`：`question`、`options`、`answer`、`cot`
- `医疗安全`：`question`、`answer`
- `医疗伦理`：`question`、`answer`

后续支持 MedBench LLM、Agent、VLM 时，应先更新需求文档和导入格式说明。

## File Storage

Vision 图片后续导入时需要复制到服务器管理目录，避免运行时依赖原始 `data/benchmarks/` 路径。

推荐目录：

```text
storage/benchmark-assets/{benchmarkSetId}/{importBatchId}/...
```

`storage/` 不提交仓库。清理策略应基于题集、导入批次或评测运行记录。

## Standard Verification

提交前根据变更范围执行：

```bash
.venv/bin/pytest -q
cd frontend && pnpm build
docker compose -p test-benchmark -f docker-compose.dev.yml config
docker compose -p test-benchmark -f docker-compose.yml config
```

如改动 Dockerfile 或 Compose，应额外验证镜像构建和 `bin/local-dev.sh restart`。
