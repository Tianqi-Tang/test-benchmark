# test-benchmark

项目目标：评测以下医疗文本模型和多模态模型在医疗场景题集上的表现。

## 候选模型

### 通用文本模型

| 模型 | 类型 | 备注 |
| --- | --- | --- |
| `AntAngelMed`（安诊儿） | 医疗文本模型 | 面向医疗问答、健康咨询等文本任务。 |
| `DeepSeek-v4-pro` | 通用文本模型 | 面向医疗文本理解与生成任务。 |
| `qwen3.7-plus` | 通用文本模型 | 面向医疗文本理解与生成任务。 |
| `gpt-5.5` | 通用文本模型 | 面向医疗文本理解与生成任务。 |
| `Gemini-3.5-flash` | 通用文本模型 | 面向医疗文本理解与生成任务。 |

### 多模态模型

| 模型 | 类型 | 备注 |
| --- | --- | --- |
| `qwen3.7-plus` | 多模态模型 | 面向医学图像、报告图片、OCR 与视觉问答任务。 |
| `gpt-5.5` | 多模态模型 | 面向医学图像、报告图片、OCR 与视觉问答任务。 |
| `Gemini-3.5-flash` | 多模态模型 | 面向医学图像、报告图片、OCR 与视觉问答任务。 |

## 题集资料

本地题集资料放在：

```text
data/benchmarks/
```

当前目录包括：

| 目录 | 内容 |
| --- | --- |
| `data/benchmarks/MedBench_LLM/` | 文本医疗基准题集。 |
| `data/benchmarks/MedBench_Agent/` | Agent 类医疗基准题集。 |
| `data/benchmarks/MedBench_VLM/` | 多模态医疗基准题集及图片资源。 |
| `data/benchmarks/custom_medical_eval_sets/` | 自定义或上传的医疗评测题集。 |

题集、图片、模型权重、评测输出等本地资产不提交到代码仓库。

## 当前阶段

当前先搭建项目框架和流水线，不实现具体评测功能。

已包含：

- Python Web 服务骨架。
- 最小 Web 首页。
- `/health` 健康检查接口。
- Docker / Docker Compose 本地运行配置。
- GitHub Actions 测试、构建和测试环境部署流水线。

## 本地运行

Python 版本对齐为 `3.11`。本地宿主机端口使用 `18110`，容器内服务端口使用 `8000`。

本地调试使用 `docker-compose.dev.yml`，通过 `bin/local-dev.sh` 统一启动和停止服务。该模式挂载 `backend/` 目录并启用 `uvicorn --reload`，日常启动不会构建项目镜像。

```bash
bin/local-dev.sh start
```

访问：

```text
http://localhost:18110
http://localhost:18110/health
```

停止服务：

```bash
bin/local-dev.sh stop
```

查看状态和日志：

```bash
bin/local-dev.sh status
bin/local-dev.sh logs
```

## 本地测试

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pytest -q backend/tests
```

## 测试环境部署

GitHub Actions 会在 `main` 分支 push 后执行：

1. 安装 Python 依赖。
2. 运行测试。
3. 构建 Docker 镜像。
4. 通过 SSH 部署到测试服务器。

测试环境部署使用 `docker-compose.yml` 和 `Dockerfile` 构建运行镜像。

测试服务器：

```text
azureuser@20.2.81.240
```

部署目录：

```text
/home/azureuser/test-benchmark
```

需要在 GitHub 仓库配置 secret：

| Secret | 用途 |
| --- | --- |
| `DEPLOY_SSH_KEY` | 连接测试服务器的 SSH 私钥。 |

测试环境容器使用宿主机端口 `18110`，公网通过 nginx 路由访问：

```text
http://20.2.81.240/test-benchmark/
```
