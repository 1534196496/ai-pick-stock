# Google Cloud Codex 续开发移交

> 移交日期：2026-08-24
> 当前分支：`feature/portfolio-watchlist-v2`
> 已完成实现基线：`7345385f3c9c608c7ac94c0ec60f944770702255`
> 当前任务：T15

## 1. 移交目标

在 Google Cloud 机器上的 Codex 继续完成个人股票与基金资产管理产品 V2。严格依据已确认的规格和任务清单，从 T15 连续推进，不重新讨论产品方向，不参考旧版界面重新设计，也不重写已验证的 T01–T14。

用户已确认采用推荐方案，希望 Codex 自主推进；只有出现以下真正阻塞时才停止并说明：

- 缺少无法安全生成的外部账号、SMTP 凭据或付费数据源授权。
- 实际服务器状态与本文或规格冲突，继续操作可能影响旧服务或数据。
- 需要切换域名、移除 Basic Auth、删除数据、合并分支等尚未授权的外部操作。
- 必须实施规格未覆盖的 Breaking Change。

其余实现细节应先查现有代码和文档，再按成熟、简单、可测试的方案执行，不频繁询问用户。

## 2. 开始前必须确认

在服务器项目目录执行只读检查：

```bash
git fetch origin
git switch feature/portfolio-watchlist-v2
git pull --ff-only
git branch --show-current
git log -2 --oneline
git status --short
```

成功标准：

- 当前分支为 `feature/portfolio-watchlist-v2`。
- 历史中包含实现基线 `7345385` 以及本移交文档提交。
- 工作区干净；如有服务器本地改动，先识别归属，不覆盖、不丢弃。
- 不从 `main` 重新开发，不手工重建已经提交的代码。

若远端分支尚不存在，不要猜测或复制零散文件，先确认本地已完成 push。

## 3. 必须阅读的上下文

按以下顺序阅读，选中的文件必须读完整：

1. 本文。
2. `docs/dev-workflow/portfolio-watchlist-v2/.state.json`。
3. `docs/dev-workflow/portfolio-watchlist-v2/任务清单.md`，从 T15 开始执行。
4. 当前任务涉及的 `docs/dev-workflow/portfolio-watchlist-v2/04-设计方案.md` 小节。
5. `docs/dev-workflow/portfolio-watchlist-v2/实施计划.md` 中对应阶段、验证门和外部操作边界。
6. 修改前阅读相关源文件、测试和同类实现，不凭记忆发明接口。

需求背景需要核对时再读取：

- `01-需求理解.md`
- `02-代码调研与影响分析.md`
- `03-交叉验证.md`

任务进度以 `.state.json` 和 `任务清单.md` 为准。每完成一项任务，应同步更新两者，记录真实验证结果；不能只改状态而未通过验收。

## 4. 产品边界

V2 是一个简洁的个人投资账本，一期只完成实用闭环：

- 用户通过邮箱和密码注册、登录、退出、重置密码。
- 管理多个投资账户。
- 管理 A 股和中国公募基金持仓。
- 管理股票与基金自选，支持多个分组。
- 登录后的一级业务菜单始终只有“持有”和“自选”。
- 不连接券商，不自动下单，不提供收益承诺或个性化投资建议。
- 后续可扩展其他市场，因此资产身份、市场、交易所和币种边界不能写死为六位代码。

旧 Streamlit 产品只用于保留历史代码和已验证的数据口径，不复用旧界面或旧业务实现。V2 使用独立目录、数据库、Compose、镜像、端口和数据卷。

## 5. 已冻结技术方案

- Web：React 19、TypeScript、Vite 8、React Router 7、TanStack Query 5、CSS Modules/原生 CSS。
- API：Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、psycopg 3。
- 数据库：PostgreSQL 17。
- 架构：模块化单体；模块内使用 models、schemas、repository、service、router 分层。
- 会话：服务端不透明令牌；数据库只保存 SHA-256 摘要。
- 密码：Argon2id，12–128 个字符。
- API：`/api/v1`、camelCase、UTC RFC 3339、UUID、财务十进制值使用字符串。
- 页面不直接访问外部行情；Worker 同步后写入本地 PostgreSQL，API 只读本地数据。
- 金额、份额、价格使用 `Decimal`/PostgreSQL `NUMERIC`，禁止 JavaScript `Number` 作为权威财务计算。

视觉系统已冻结：

- 主题是安静的“个人账本”，不模仿旧产品、行情终端或纸张。
- 不使用渐变、玻璃拟态、装饰性大图或外部字体。
- 设计令牌以 `apps/web/src/styles/tokens.css` 为准。
- 盈利用红色、亏损用绿色，同时必须显示正负号和文字，不能只靠颜色。
- 360px 无横向滚动；桌面与移动端均可完成核心流程。

## 6. 已完成范围：T01–T14

### 工程与开源底座

- Apache-2.0、README、贡献指南、行为准则、安全策略、变更记录。
- Issue/PR 模板、Dependabot 和基础 GitHub Actions。
- 根目录 Makefile、忽略规则、EditorConfig、Git 属性。
- 新旧系统并存，旧 `compose.yaml`、旧 Dockerfile、Streamlit 代码和旧数据卷未修改。

### V2 运行底座

- FastAPI、SQLAlchemy、Alembic、PostgreSQL 17。
- React、TypeScript、Vite、路由和初始“持有/自选”界面骨架。
- Web、API、Worker、migrate、PostgreSQL 的独立 `compose.v2.yaml`。
- V2 Web 默认 `127.0.0.1:18080`；API 默认 `127.0.0.1:18000`；PostgreSQL 不映射宿主机端口。
- 容器非 root、只读文件系统、移除 Linux capabilities、带健康检查。

### 认证与用户隔离基础

- `users`、`sessions`、`security_events` 迁移及数据库约束。
- 规范化邮箱唯一；所有时间使用 `TIMESTAMPTZ`；会话仅存 64 位小写 SHA-256 摘要。
- Argon2id 密码摘要、RFC 9106 参数、随机会话令牌和环境化 Cookie 策略。
- Repository 不向服务层泄露 ORM 实例。
- 注册 API：邮箱规范化、密码校验、重复邮箱冲突、安全事件。
- 登录/当前会话/退出 API：统一凭据失败、会话轮换、刷新保持、幂等退出、安全审计。
- 生产 Cookie 使用 `__Host-`、`Secure`、`HttpOnly`、`SameSite=Lax`、`Path=/`，不设置 Domain。

## 7. 当前验证证据

移交前已通过：

```text
make lint       通过
make typecheck  通过
make test       通过
make build      通过
```

- 后端标准测试：26 passed、7 skipped，总覆盖率 86.8%。
- 7 个 skipped 是需要显式测试库的 PostgreSQL 集成测试，不是失败。
- PostgreSQL 17 临时容器中已实际验证 T10–T14：空库升级、基线升级、降级/重升、Alembic 漂移、约束、Repository、真实注册、登录、会话轮换和退出均通过。
- 前端：2 tests passed，当前被测代码覆盖率 100%。
- V2 Compose 已真实启动；API/Web/PostgreSQL 健康，migrate 成功，Worker 运行。
- API、Worker、Web、PostgreSQL 的运行 UID 均为非 root。
- Nginx 安全头、HTML no-store、静态资源 immutable 缓存已验证。
- 临时测试容器已删除；本地 V2 PostgreSQL 命名卷保留，未执行 `down -v`。

不要把普通 `make test` 中的数据库跳过当成完整集成证据。涉及迁移、Repository、权限和财务约束时，必须启动隔离的 PostgreSQL 17 测试库，并确保测试数据库名称以 `_test` 结尾。

## 8. 下一步执行入口

从 T15 开始，严格按 `任务清单.md` 顺序推进：

1. T15：统一错误、请求 ID、Origin/CSRF 和认证限流接口。
2. T16–T19：OpenAPI Client、注册登录页面、受保护应用壳、认证 E2E，完成检查点 B。
3. T20–T25：密码重置与投资账户，完成检查点 C。
4. T26–T34：资产主数据、数据源实测、股票/基金 Provider、Worker、资产搜索与数据状态，完成检查点 D。
5. T35–T42：股票持仓与汇总、页面、表单、冲突恢复和 E2E，完成检查点 E。
6. T43–T48：基金快速/精确双录入、官方/估算净值口径、页面和 E2E，完成检查点 F。
7. T49–T54：自选多分组、备注、移动、添加到持有和 E2E，完成检查点 G。
8. T55–T63、T65–T66：响应式、性能、安全、迁移、文档、全量 E2E、备份恢复、生产配置、服务器并行部署、评审和提交方案。
9. T64 与 T67 受外部授权限制，只能准备和验证草案，不能实际执行域名切换或分支集成。

T15 尚未写入任何中间实现，直接从测试开始即可。不要依赖旧会话中的未提交思路。

## 9. 每项任务的工作方式

1. 先把该任务的验收条件改写为可执行成功标准。
2. 读取任务相关源码、测试、接口和迁移链。
3. 行为变更先写失败测试，再写最小实现，再重构。
4. 每个 class 和 method 必须有清晰、必要的中文职责注释；标识符保持英文。
5. 优先 CLI，搜索优先 `rg`/`rg --files`，文件修改使用 `apply_patch`。
6. 不猜测第三方字段；先用固定样本和边界 schema，再实现 Provider。
7. 涉及最新依赖、数据源、安全或部署事实时，查官方一手资料并记录日期与依据。
8. 不把外部 HTTP 放进页面请求；失败时保留旧有效值并显示陈旧/失败状态，不伪造数字。
9. 每完成一项任务，运行聚焦测试、lint、类型检查，并更新任务状态。
10. 每个检查点运行完整门禁，保留简短证据，不以口头判断代替结果。

必要依赖可在不改变冻结架构的前提下按成熟方案添加，但必须：

- 使用包管理器更新 lockfile。
- 说明用途、许可证和运行/体积影响。
- 优先活跃维护、官方或事实标准实现。
- 不引入付费服务、外部账号或密钥作为默认前提。

## 10. 强制工程规则

- 始终使用中文与用户交流；代码标识符使用英文。
- Commit message、PR 标题和正文使用中文 Conventional Commits。
- 不删除、覆盖或回滚用户已有改动。
- 不使用 `git reset --hard`、`git checkout --` 等破坏性命令。
- 不提交 `.env`、密钥、数据库、备份、日志、构建产物或 IDE 文件。
- 修改代码必须考虑向后兼容；Breaking Change 必须停止并获得明确确认。
- 未获得新的明确授权前，不执行后续 `git commit`、`git push`、merge、创建 `dev2.x` 或合并 `main`。
- 当前 push 授权仅用于把本移交文档和既有实现推到 feature 分支，不是后续 Git 操作的长期授权。
- 不删除 Docker 数据卷；停止服务默认只允许 `docker compose down`，不得使用 `down -v`。
- 不把示例密码用于生产；生产密钥在服务器本地生成，文件权限收紧，绝不输出到对话、日志或 Git。

## 11. 质量门

每个检查点至少运行：

```bash
make lint
make typecheck
make test
make build
```

发布候选运行：

```bash
make lint && make typecheck && make test && make build && make e2e
```

必须额外满足：

- 后端和前端整体覆盖率不低于 80%。
- 认证、权限和财务计算关键分支覆盖率不低于 90%。
- 空库升级、逐版本升级、Alembic 漂移和 PostgreSQL 约束通过。
- 两个用户的跨用户负向测试覆盖读取、创建、修改、移动和删除。
- OpenAPI 生成物无未提交漂移，前端 Client 与后端一致。
- 360px 与桌面浏览器完成核心流程，无横向滚动和控制台错误。
- 首屏 JS gzip 不超过 250KB；API 请求不触发外部行情 HTTP。
- 日志不含密码、Cookie、会话/重置令牌、完整邮箱和持仓金额。
- 无未处理的 Critical/High 代码审查或依赖安全问题。

## 12. Google Cloud 部署边界

已授权：功能完成并通过发布门禁后，在当前 Google Cloud 机器执行 V2 并行部署。

并行部署必须满足：

- 保留旧 Streamlit 服务、旧镜像、旧 SQLite、旧 Compose 和全部旧数据卷。
- 旧服务当前计划使用 8502；实际值必须先通过只读命令确认，不能按文档猜测。
- 新 Web/API 只绑定回环地址，默认 `127.0.0.1:18080` 和 `127.0.0.1:18000`。
- PostgreSQL 只在 Compose 内网，不映射公网。
- 使用生产 `.env.v2`，设置 `AIPICKSTOCK_ENVIRONMENT=production` 和强随机数据库密码；不得提交该文件。
- 先迁移、健康检查、日志检查、备份恢复冒烟，再运行服务器 E2E。
- 部署失败时停止新 V2 服务即可，不能删除卷，不能影响旧服务。

未授权：

- 不修改 DuckDNS 记录。
- 不切换 `aipickstock.duckdns.org` 到 V2。
- 不移除现有 Caddy Basic Auth。
- 不替换现有 Caddy/Nginx 生效配置。
- 不关闭或删除旧服务。
- 不开放 18000、18080 或 PostgreSQL 到公网。

环境事实需要重新核对：会话中提到服务器公网 IP `34.153.219.175`，但更早的 DuckDNS 截图显示过 `50.7.158.236`。这两项冲突，只能通过服务器和 DNS 的只读检查确认；在获得域名切换授权前，无论结果如何都不得改 DNS。

## 13. 受限任务处理

- T63 并行部署已经授权，可在全部前置门通过后执行并记录证据。
- T64 只能准备 Caddy 切换和回滚草案、运行静态校验；实际切换域名和回滚演练未授权。
- T65 可以执行完整多角色代码评审并修复问题。
- T66 可以生成提交方案和只读 Git 报告。
- T67 不得执行；创建 `dev2.x`、commit/merge/push 需要用户届时再次明确授权。
- 因 T64/T67 授权缺失而无法全量完成时，应完成所有其余安全可执行工作，然后准确报告“等待授权”，不能把它们伪装为已完成。

## 14. 给服务器 Codex 的直接指令

在项目根目录启动 Codex 后，输入：

```text
请完整阅读 docs/dev-workflow/portfolio-watchlist-v2/05-Google-Cloud-Codex-移交.md，
然后按文档先验证分支、提交和服务器现状，从 T15 开始连续完成所有仍获授权的任务。
不要重新规划产品，不要重做 T01–T14，不要频繁问我；按已经确认的推荐方案、任务清单和 TDD 推进。
每项任务必须以真实测试和运行证据为完成标准，并同步更新 .state.json 和任务清单。
功能完成后可在独立端口并行部署 V2，但不得切换域名、移除 Basic Auth、删除旧服务或数据卷，
也不得在没有新授权时 commit、push、merge 或创建 dev2.x。
如果发生真正阻塞，先完成其他不受阻的任务，再用证据说明阻塞点和所需授权。
```

## 15. 移交完成定义

服务器 Codex 完成当前授权范围时，应提交一份中文结果报告，至少包含：

- T15–T63、T65–T66 的逐项状态和未完成原因。
- 完整质量门、覆盖率、E2E、可访问性和性能证据。
- 真实 PostgreSQL 迁移矩阵、备份与临时库恢复证据。
- 数据源实测日期、首选/回退、延迟、限流和已知边界。
- 服务器新旧服务端口、容器健康、日志和回滚方式。
- 秘密扫描、依赖安全与多角色评审结论。
- 明确列出未执行的域名切换、Basic Auth 移除和 `dev2.x` 集成。
- 展示完整 Git diff 和建议提交切片，等待用户下一次明确授权。
