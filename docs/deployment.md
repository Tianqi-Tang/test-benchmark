# Deployment

## Test Environment

测试服务器：

```text
azureuser@20.2.81.240
```

部署目录：

```text
/home/azureuser/test-benchmark
```

公网访问路径：

```text
http://20.2.81.240/test-benchmark/
```

根路径 `http://20.2.81.240/` 已由其他项目使用，本项目不得占用根路径。

## GitHub Actions

`main` 分支 push 后应执行：

1. 使用 `uv` 安装后端依赖。
2. 运行后端测试。
3. 安装前端依赖并构建 Vue 3 前端。
4. 构建 Docker 镜像。
5. 通过 SSH 部署到测试服务器。
6. 将前后端容器接入 nginx 所在 Docker 网络。
7. 校验后端 health 和前端页面可访问。
8. 校验公网子路径 API：`/test-benchmark/api/health`。

仓库 secret：

| Secret | 用途 |
| --- | --- |
| `DEPLOY_SSH_KEY` | 连接测试服务器的 SSH 私钥 |
| `TEST_BENCHMARK_AUTH_PASSWORD` | 测试环境登录密码 |
| `TEST_BENCHMARK_AUTH_SECRET` | 后端会话 cookie 签名密钥 |

部署流水线会在测试服务器部署目录写入 `.env`，供 Docker Compose 注入鉴权配置。不要把真实密码或签名密钥提交到仓库。

## Nginx Route

nginx 应保留根路径给现有项目，并为 test-benchmark 增加子路径路由：

```nginx
location = /test-benchmark {
    return 301 /test-benchmark/;
}

location /test-benchmark/api/ {
    proxy_pass http://test-benchmark-backend:8000/api/;
}

location /test-benchmark/ {
    proxy_pass http://test-benchmark-frontend:80/;
}
```

实际配置需要保留通用 proxy headers：

- `Host`
- `X-Real-IP`
- `X-Forwarded-For`
- `X-Forwarded-Proto`

## Database and Storage

测试环境使用 PostgreSQL。数据库可以由本项目 Compose 管理，也可以接入服务器已有 PostgreSQL，但必须满足：

- 后端通过 `DATABASE_URL` 连接。
- 数据库数据持久化。
- 默认 Compose 服务名为 `postgres`，容器名为 `test-benchmark-postgres`。
- 宿主机调试端口默认为 `18112`。
- API key 只存数据库并脱敏展示。
- `storage/benchmark-assets/` 持久化，用于保存导入的图片资源。

## Deployment Constraints

- 不提交 `data/`、`storage/`、模型文件、评测输出。
- 前端测试环境构建使用 `/test-benchmark/` base path。
- 本地开发前端仍使用根路径 `/`。
- 数据库迁移、初始化和导入逻辑应可重复执行，不依赖手工改库。
