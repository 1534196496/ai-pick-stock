# 知衡

知衡是一款面向个人投资者的股票与基金资产管理工具。它把日常最常用的两件事做好：管理真实持仓，以及分组整理仍在观察的标的。

V2 正在独立开发，保留原有 Streamlit 代码和部署方式，不复用旧产品的信息架构。

## 第一期范围

- 账户注册、登录、退出和安全的会话管理。
- 管理 A 股与中国公募基金持仓，包括数量、成本和持仓分组。
- 管理股票与基金自选，支持建立多个分组和排序。
- 展示持仓市值、盈亏、占比以及明确的数据更新时间。
- 为后续扩展其他市场、交易流水、收益分析和提醒能力保留稳定边界。

知衡不连接券商、不自动下单，也不提供收益承诺或个性化投资建议。

## 技术架构

- Web：React 19、TypeScript、Vite、React Router、TanStack Query。
- API：Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic。
- 数据库：PostgreSQL 17。
- 运行方式：Nginx 静态站点、API、Worker 和 PostgreSQL 独立容器。

V2 采用模块化单体架构。账户、资产目录、持仓、自选和行情数据各自保持清晰边界，先控制运维复杂度，再按实际规模演进。

## 本地启动 V2

需要 Docker Engine 与 Docker Compose 插件。

```bash
cp .env.v2.example .env.v2
```

编辑 `.env.v2`，为 `POSTGRES_PASSWORD` 设置足够长的随机密码，并把同一个密码写入 `AIPICKSTOCK_DATABASE_URL`。然后启动：

```bash
V2_ENV_FILE=.env.v2 docker compose -f compose.v2.yaml up -d --build
docker compose -f compose.v2.yaml ps
```

默认地址：

- Web：`http://127.0.0.1:18080`
- API 存活检查：`http://127.0.0.1:18000/api/v1/health/live`
- API 就绪检查：`http://127.0.0.1:18000/api/v1/health/ready`

PostgreSQL 不映射宿主机端口。停止服务时不会删除数据库卷：

```bash
docker compose -f compose.v2.yaml down
```

## 本地开发

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 以及 Node.js 24。

```bash
make bootstrap
make lint
make typecheck
make test
make build
```

所有可用命令可通过 `make help` 查看。

## 旧版应用

旧版研究工具仍保留在仓库根目录，继续使用原有 `compose.yaml` 和 Streamlit 数据卷。V2 使用独立的 `compose.v2.yaml`、镜像、网络、端口和 PostgreSQL 卷，两套服务可以并行运行。

## 参与贡献

请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 和 [SECURITY.md](SECURITY.md)。架构与实施记录位于 `docs/dev-workflow/portfolio-watchlist-v2/`。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
