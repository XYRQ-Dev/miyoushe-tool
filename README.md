# 米游社自动签到

自托管的米游社账号管理与签到平台，在一个 Web 界面中完成账号绑定、手动签到、定时任务和邮件通知。

后端基于 FastAPI，前端基于 Vue 3，数据存储于 MySQL，支持 Docker Compose 部署。通过官方 Passport / HoyoPlay 二维码获取登录凭据，并在工作 Cookie 失效时尝试自动修复。

> [!NOTE]
> 本项目为非官方工具，当前适配米游社国服，具体游戏与渠道见下表。签到结果受上游接口、账号状态与风控影响。

## 目录

- [主要功能](#主要功能)
- [支持的游戏](#支持的游戏)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [使用指南](#使用指南)
- [本地开发](#本地开发)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [反馈与贡献](#反馈与贡献)
- [许可证](#许可证)

## 主要功能

- **账号管理**：扫码绑定多个米游社账号，同步游戏角色，校验登录态，升级旧登录凭据
- **自动签到**：支持手动执行与 Cron 定时任务，默认每天北京时间 `06:00` 签到，并随机错峰执行
- **登录态维护**：区分根凭据与工作 Cookie，优先自动修复 Cookie，无法恢复时提示重新登录
- **签到记录**：按游戏、状态、日期筛选日志，查看近期签到统计、当月奖励日历和今日奖励
- **邮件通知**：支持系统 SMTP、个人收件邮箱，以及每次通知或仅失败时通知的策略
- **后台管理**：用户启停与永久删除、注册邀请码、菜单显隐、公告邮件群发
- **界面主题**：支持浅色与深色模式，主题偏好保存在当前浏览器

## 支持的游戏

当前代码配置了以下签到渠道；表中列出的是适配范围，不代表上游接口始终可用。

| 游戏 | 渠道 | `game_biz` |
| --- | --- | --- |
| 原神 | 国服官服、B 服 | `hk4e_cn`、`hk4e_bilibili` |
| 崩坏：星穹铁道 | 国服官服、B 服 | `hkrpg_cn`、`hkrpg_bilibili` |
| 崩坏 3 | 国服官服 | `bh3_cn` |
| 绝区零 | 国服官服 | `nap_cn` |

其他渠道及国际服不在当前适配范围内。未适配角色会显示「签到未适配」，不会进入签到流程。

## 快速开始

### 环境要求

- Docker Engine 或 Docker Desktop，以及 Docker Compose v2
- 可用的宿主机端口：`80`、`8000`、`3306`
- 能够访问镜像源、依赖源和米哈游相关服务的网络

以下命令使用 PowerShell，在仓库根目录执行。请先克隆仓库或下载并解压源码。

### 1. 准备配置

```powershell
Copy-Item .env.example .env
```

编辑根目录 `.env`，至少替换以下配置中的占位值：

```dotenv
SECRET_KEY=<独立的强随机字符串>
ENCRYPTION_KEY=<另一个独立的强随机字符串>
MYSQL_DATABASE=miyoushe
MYSQL_USER=miyoushe
MYSQL_PASSWORD=<数据库用户密码>
MYSQL_ROOT_PASSWORD=<数据库管理员密码>
```

使用内置 MySQL 时，不需要设置 `DATABASE_URL`，Compose 会使用 `mysql:3306` 作为数据库地址。暂不使用邮件通知时，将示例中的 `SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD` 留空。

> [!IMPORTANT]
> 请长期保存 `ENCRYPTION_KEY`，并与数据库一同备份。更换或丢失该密钥会导致已有根凭据、Cookie 和 SMTP 密码无法解密。`SECRET_KEY` 用于 JWT 签名，更换后已有登录令牌会失效。

### 2. 构建并启动

```powershell
docker compose up -d --build
docker compose ps
```

Compose 会启动 MySQL、后端和 Nginx 前端。首次构建需要下载依赖与浏览器组件。

### 3. 打开平台

| 入口 | 默认地址或端口 |
| --- | --- |
| Web 界面 | [http://localhost](http://localhost) |
| 后端 API 文档 | [http://localhost:8000/docs](http://localhost:8000/docs) |
| 健康检查 | [http://localhost:8000/api/health](http://localhost:8000/api/health) |
| MySQL | 宿主机 `3306` 端口 |

注册平台账号后，在「账号管理」绑定米游社账号。**第一个注册用户自动成为管理员**，请在开放访问前完成首次注册。

当前 Compose 会向宿主机发布上述三个端口。公网部署时应配置 HTTPS，并按实际需要限制数据库和后端端口的访问范围。

### 常用维护命令

```powershell
# 查看后端日志
docker compose logs --tail 100 -f backend

# 停止服务，保留数据库卷
docker compose down

# 更新源码后，重新构建并启动
docker compose up -d --build
```

MySQL 数据保存在命名卷 `mysql-data` 中。升级前备份数据库与密钥；不要使用 `docker compose down -v` 停止需要保留数据的环境。

当前后端按**单进程、单实例**运行，扫码会话、调度和用户删除保护包含进程内状态，不应直接扩展为多 worker 或多后端副本。

## 配置说明

配置模板见 [.env.example](.env.example)，容器配置见 [docker-compose.yml](docker-compose.yml)。

| 配置项 | 用途 | 设置方式 |
| --- | --- | --- |
| `SECRET_KEY` | JWT 签名密钥 | 必须设置固定的强随机值 |
| `ENCRYPTION_KEY` | 敏感数据加密密钥 | 必须固定并妥善备份 |
| `MYSQL_DATABASE`、`MYSQL_USER` | Compose 内置数据库名称、用户 | 默认均为 `miyoushe` |
| `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD` | Compose 内置数据库密码 | 必须替换示例值 |
| `DATABASE_URL` | 后端数据库连接串 | 本地开发显式填写；Compose 默认自动组装 |
| `SMTP_HOST`、`SMTP_PORT` | SMTP 地址、端口 | 可选，默认端口为 `465` |
| `SMTP_USER`、`SMTP_PASSWORD` | SMTP 账号、密码 | 可选，也可在管理员页面配置 |
| `SMTP_USE_SSL` | SMTP 是否使用 SSL | 默认 `true` |
| `TEST_DATABASE_URL` | 后端自动化测试数据库 | 仅测试时使用，必须为独立测试库 |

### 数据库与配置文件位置

运行时与数据库测试均仅支持 MySQL。建议使用与容器配置一致的 MySQL 8.4，连接串统一使用：

```dotenv
DATABASE_URL=mysql+asyncmy://<用户名>:<URL编码后的密码>@<主机>:3306/<数据库名>?charset=utf8mb4
```

运行时兼容将 `mysql://`、`mysql+pymysql://` 转换为异步连接串；测试库必须显式使用 `mysql+asyncmy://`。

- **Docker Compose**：读取仓库根目录 `.env`，将编排中声明的变量传给后端
- **本地后端**：读取启动工作目录下的 `.env`；按下文从 `backend/` 启动时，应使用 `backend/.env`
- **外部 MySQL**：可通过 `DATABASE_URL` 指定连接，但现有 Compose 仍会启动并依赖内置 `mysql` 服务；完全移除内置数据库需要同时调整编排

`MYSQL_*` 是数据库容器的初始化参数，修改 `.env` 不会自动修改已有数据卷中的数据库账号或密码。

### 时间与邮件策略

业务日期、Cron 调度、接口时间和界面显示统一为 `Asia/Shanghai`（北京时间），不提供可选时区。数据库按 UTC 保存绝对时刻，接口输出带 `+08:00` 的时间。

系统 SMTP 决定如何发信；个人通知邮箱决定收件人；个人通知开关与策略决定何时发送签到邮件。管理员公告群发面向已绑定邮箱且启用的用户，不受个人签到通知开关限制。

## 使用指南

1. **注册并登录**：首个用户为管理员；管理员开启注册邀请码后，后续注册需填写正确邀请码
2. **绑定账号**：进入「账号管理」，使用官方 Passport 二维码完成授权；平台保存根凭据，并尝试补齐工作 Cookie 和游戏角色
3. **执行签到**：在仪表盘手动签到，查看结果与日志；遇到风控提示时，稍后重试或前往米游社处理
4. **设置定时任务**：在「系统设置 → 签到调度」开启或关闭自动签到，修改五段式 Cron；默认 `0 6 * * *`，触发后随机延迟 0–60 秒执行
5. **配置通知**：管理员配置 SMTP，用户填写收件邮箱并选择通知策略

调度器每天北京时间 `03:00` 巡检账号登录态。工作 Cookie 失效时会优先用根凭据修复；提示需要重新登录或升级登录时，请重新扫码。短信验证码接口仅校验根凭据，不直接绑定账号。

### 管理操作

| 入口 | 功能 |
| --- | --- |
| 用户信息列表 | 查看用户、启用或停用用户、永久删除其他用户 |
| 菜单与功能开关 | 分别控制普通用户和管理员的菜单可见性 |
| 系统设置 | 配置 SMTP、注册邀请码、公告邮件群发 |

删除米游社账号会同时删除其游戏角色和历史签到日志。管理员永久删除平台用户会清理该用户的关联账号、凭据、日志与任务等数据，不能删除当前登录用户。操作前请核对确认框中的范围；提示业务忙碌时稍后重试。

菜单显隐不替代服务端权限校验，管理员菜单管理入口会始终保留。

## 本地开发

### 技术栈与依赖

| 层级 | 技术 |
| --- | --- |
| 后端 | Python、FastAPI、SQLAlchemy Async、APScheduler、httpx、Playwright |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia |
| 数据库 | MySQL、asyncmy |
| 容器部署 | Docker Compose、Nginx、Uvicorn |

准备 Python 3.11+（本地建议 3.13）、Node.js 22.6+、npm，以及已创建数据库且授权可用的 MySQL 服务。前端容器使用 Node.js 20 构建；本地建议 Node.js 22.6+，以支持现有测试脚本使用的 `--experimental-strip-types` 参数。

### 启动后端

在仓库根目录执行：

```powershell
Set-Location backend
python -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install -r requirements.txt
.\.venv313\Scripts\python.exe -m playwright install chromium
```

新建 `backend/.env`，填写后端需要的配置，不要直接复制根目录模板中的 `MYSQL_*` 容器初始化变量：

```dotenv
SECRET_KEY=<固定的强随机字符串>
ENCRYPTION_KEY=<另一个固定的强随机字符串>
DATABASE_URL=mysql+asyncmy://<用户名>:<URL编码后的密码>@127.0.0.1:3306/<数据库名>?charset=utf8mb4
```

继续在 `backend/` 下执行：

```powershell
.\.venv313\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端启动会初始化数据库并启动调度器，请使用开发数据库。

### 启动前端

另开一个 PowerShell 窗口，在仓库根目录执行：

```powershell
Set-Location frontend
npm ci
npm run dev
```

访问 [http://localhost:3000](http://localhost:3000)。Vite 会将 `/api` 和 `/ws` 请求代理到本机后端 `8000` 端口。

### 静态检查与构建

在 `backend/` 下执行 Python 编译检查：

```powershell
.\.venv313\Scripts\python.exe -m compileall app
```

在 `frontend/` 下执行类型检查与生产构建：

```powershell
npm run build
```

构建脚本依次执行 `vue-tsc --noEmit` 和 Vite 构建。构建通过不代表登录、签到等实际流程已验收。

### 自动化测试

后端使用 `unittest`。数据库测试会建表、清空数据，部分用例会重建表结构；仅在确认可销毁的独立测试库中运行，禁止指向正式库或需要保留数据的开发库。

在 `backend/` 下执行：

```powershell
$env:TEST_DATABASE_URL="mysql+asyncmy://<测试用户>:<URL编码后的密码>@127.0.0.1:3306/miyoushe_test?charset=utf8mb4"
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
```

在 `frontend/` 下执行现有 TypeScript 回归脚本：

```powershell
npm test
```

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP 路由
│   │   ├── models/       # 数据模型
│   │   ├── schemas/      # 接口数据结构
│   │   ├── services/     # 登录、签到、调度、通知等业务逻辑
│   │   ├── utils/        # 加密、设备参数、时区等工具
│   │   ├── config.py     # 应用配置
│   │   ├── database.py   # 数据库连接与初始化
│   │   └── main.py       # 应用入口与扫码 WebSocket
│   ├── tests/            # 后端回归用例
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/          # 请求封装
│   │   ├── components/   # 共享组件
│   │   ├── views/        # 页面
│   │   ├── stores/       # 状态管理
│   │   ├── router/       # 路由
│   │   ├── styles/       # 样式
│   │   └── utils/        # 前端工具
│   ├── tests/            # 前端回归用例
│   ├── nginx.conf
│   └── Dockerfile
├── .env.example          # Compose 环境变量模板
├── docker-compose.yml
└── AGENTS.md             # 仓库协作约定
```

## 常见问题

| 问题 | 排查方向 |
| --- | --- |
| 本地启动未读到配置 | 确认启动目录为 `backend/`，配置位于 `backend/.env`，或已通过进程环境变量提供 |
| 数据库连接失败 | 核对服务状态、账号权限、数据库名和连接地址；容器内置库使用 `mysql:3306`，宿主机直连使用实际地址 |
| 二维码无法加载或持续断开 | 查看后端日志，确认反向代理同时转发 `/api/` 与 `/ws/`，并支持 WebSocket Upgrade |
| 账号提示需要升级登录 | 旧 Cookie-only 账号需要重新扫码，重复点击校验不会补齐高权限凭据 |
| 重启后已有凭据无法解密 | 检查 `ENCRYPTION_KEY` 是否与原部署一致，以及配置文件是否被正确读取 |
| 签到失败、风控或维护提示 | 查看日志中的具体上游错误；确认游戏渠道在适配范围内，必要时前往米游社处理 |
| 邮件没有收到 | 检查系统 SMTP、用户邮箱、个人通知开关和通知策略；管理员群发不采用个人签到通知策略 |
| 删除提示忙碌 | 等待该用户或账号正在执行的业务完成后重试 |

需要进一步定位时，可使用 `docker compose logs --tail 100 backend` 收集日志。提交问题前请移除 Cookie、令牌、密钥、邮箱及其他个人信息。

## 反馈与贡献

欢迎通过仓库 Issues 反馈问题或提出功能建议，通过 Pull Request 提交改进。

提交问题时请提供：

- 部署方式、代码版本、运行环境
- 复现步骤、预期结果与实际结果
- 脱敏日志；界面问题可附截图

贡献前请阅读 [AGENTS.md](AGENTS.md)。保持改动范围集中，遵循现有代码风格；涉及登录、调度或 API 行为时补充有意义的回归用例。提交信息采用 Conventional Commits，例如：

```text
feat(frontend): 增加签到日志筛选
fix(signin): 修正游戏活动参数
docs(readme): 更新部署说明
```

PR 请说明用户可见变化、实际完成的验证、未验证项，以及配置或数据库影响。界面变更请附截图或人工验收步骤，覆盖相关的桌面、平板、手机与深色模式。
