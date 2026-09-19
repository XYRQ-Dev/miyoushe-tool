# 米游社自动签到

自托管的米游社账号管理与签到平台。使用官方 `Passport / HoyoPlay` 高权限登录绑定账号，支持手动签到、定时签到、登录态校验与邮件通知。

> [!IMPORTANT]
> 本项目只适配**米游社国服官服**签到，不是米哈游官方产品。Cookie、根凭据等敏感数据加密后保存在你自己的 MySQL 中，请自行评估部署风险。

## 目录

- [功能](#功能)
- [技术栈](#技术栈)
- [支持范围](#支持范围)
- [快速开始](#快速开始)
- [配置](#配置)
- [使用说明](#使用说明)
- [项目结构](#项目结构)
- [本地开发](#本地开发)
- [测试](#测试)
- [故障排查](#故障排查)
- [贡献指南](#贡献指南)
- [相关文档](#相关文档)

## 功能

- **Passport 扫码登录**：通过官方二维码绑定或升级米游社账号；登录态走 WebSocket 推送
- **登录态自愈**：工作 Cookie 失效时优先用根凭据重建；根凭据也失效后才要求重新扫码
- **签到**：原神、崩坏：星穹铁道、崩坏 3、绝区零的国服官服角色；命中风控会单独标记，需稍后重试或前往米游社补签
- **调度**：默认每天东八区 `06:00` 自动签到；用户可在设置页改 Cron
- **日志**：分页查询，支持游戏、状态、日期筛选，以及最近 7 天日历统计
- **奖励日历**：仪表盘展示当月奖励和今日领取物品；漏签按本平台东八区记录标记
- **通知**：系统 SMTP + 用户通知邮箱两层配置；手动签到与定时签到共用同一套策略
- **后台**：用户启停、注册邀请码、菜单显隐、公告邮件群发
- **外观**：浅色 / 深色模式，仅保存在浏览器本地

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.11+（本机建议 3.13）、FastAPI、SQLAlchemy Async、APScheduler、Playwright |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia |
| 数据 | MySQL 8.4 |
| 部署 | Docker Compose（Nginx + Uvicorn + MySQL） |

## 支持范围

当前已验证的 `game_biz`：

| 游戏 | `game_biz` |
| --- | --- |
| 原神 | `hk4e_cn`、`hk4e_bilibili` |
| 崩坏：星穹铁道 | `hkrpg_cn`、`hkrpg_bilibili` |
| 崩坏 3 | `bh3_cn` |
| 绝区零 | `nap_cn` |

未适配的角色会在账号卡片上标记为「签到未适配」，不会进入签到流程。例如崩坏 3 B 服、绝区零国际服，以及其他尚未验证的 `game_biz`。

## 快速开始

### 使用 Docker Compose（推荐）

需要已安装 [Docker](https://docs.docker.com/get-docker/) 与 Docker Compose。

```powershell
copy .env.example .env
# 编辑 .env：至少修改 SECRET_KEY、ENCRYPTION_KEY、MySQL 密码
docker compose up -d --build
```

默认端口：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost |
| 后端 API | http://localhost:8000 |
| 健康检查 | http://localhost:8000/api/health |
| MySQL | `127.0.0.1:3306` |

首次打开页面后注册账号。**第一个注册用户自动成为管理员。**

> [!WARNING]
> `SECRET_KEY` 与 `ENCRYPTION_KEY` 必须写成固定值。若依赖运行期随机默认值，重启后历史根凭据、工作 Cookie 和 SMTP 密码都无法解密。

### 本机分别启动

前置条件：

- Python 3.13（或 3.11+）
- Node.js 20+
- 本机可连接的 MySQL 8，并已创建空库
- Playwright Chromium（扫码登录依赖浏览器子进程）

1. 复制并填写环境变量：

```powershell
copy .env.example .env
```

在 `.env` 中设置：

```env
DATABASE_URL=mysql+asyncmy://miyoushe:change_me_mysql_password@127.0.0.1:3306/miyoushe?charset=utf8mb4
SECRET_KEY=换成足够长的随机串
ENCRYPTION_KEY=换成另一个足够长的随机串
```

2. 启动后端：

```powershell
cd backend
python -m venv .venv313
.\.venv313\Scripts\activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

3. 启动前端：

```powershell
cd frontend
npm install
npm run dev
```

本机开发默认地址：

- 前端：http://localhost:3000（Vite 会把 `/api` 与 `/ws` 代理到 `8000`）
- 后端：http://localhost:8000

Windows 下后端会使用 `ProactorEventLoop`，否则 Playwright 扫码子进程无法启动。

## 配置

完整示例见 [.env.example](.env.example)。Docker 部署时，`docker-compose.yml` 会读取根目录 `.env`。

### 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 是 | JWT 签名密钥，生产环境必须改成强随机值 |
| `ENCRYPTION_KEY` | 是 | AES 加密密钥，用于根凭据、工作 Cookie、SMTP 密码等；**部署后不要更换** |
| `DATABASE_URL` | 本机直连时是 | 仅接受 `mysql+asyncmy://`。本机默认连 `127.0.0.1:3306`；Compose 默认连容器内 `mysql:3306` |
| `MYSQL_DATABASE` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` | Compose 时是 | 内置 MySQL 容器的初始化参数 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_USE_SSL` | 否 | 系统 SMTP 回退配置；管理员也可在后台覆盖 |
| `TEST_DATABASE_URL` | 跑测试时是 | 独立测试 schema，必须是 `mysql+asyncmy://`，禁止指向业务库 |

接外部 MySQL 时只需覆盖 `DATABASE_URL`，不必使用内置 MySQL 容器。`mysql://` 与 `mysql+pymysql://` 会在启动时改写成 `mysql+asyncmy://`；其它方言会直接失败。

当前运行时是 **MySQL-only**，不再支持 SQLite。

### 时区

业务日期、接口时间、调度 Cron、前端展示和容器日志全部固定为 `Asia/Shanghai`。

- 不提供 `APP_TIMEZONE` 或其它时区选项
- 数据库 `DateTime` 仍按 UTC 绝对时刻存储，接口输出带 `+08:00`
- JWT `exp` 继续使用 UTC（协议要求）

### 邮件

系统发信与用户收件是两层配置，排障时不要混在一起：

1. **系统 SMTP**：管理员在「系统设置」里维护，决定系统能不能发信
2. **用户通知邮箱**：普通用户在个人设置里填写，决定邮件发给谁
3. **通知策略**：`always`（每次都通知）或 `failure_only`（仅失败时通知）
4. **管理员群发**：发给「已绑定邮箱且账号启用」的用户，忽略个人通知开关

## 使用说明

### 注册与登录

- 打开前端，注册平台账号；首个用户为管理员
- 管理员可开启全站邀请码，之后的注册必须携带正确邀请码
- 登录后签发 JWT：访问令牌 24 小时，刷新令牌 30 天

### 绑定米游社账号

在「账号管理」中使用官方 Passport 二维码绑定。扫码成功后保存高权限根凭据，再由后续任务补齐工作 Cookie 和角色列表。

删除账号会同时永久删除其全部游戏角色和历史签到日志，确认框会列明范围；账号不存在或不属于当前用户时返回 404。删除在一个事务中完成，失败会回滚，不需要数据库结构迁移。

签到、登录态维护、扫码保存与删除使用按数据库和账号隔离的 MySQL 命名锁；账号忙时删除返回 409，请稍后重试。每个同时执行的账号操作额外占用一个数据库连接，锁跨业务提交保持有效。升级时所有后端进程需同步更新并连接同一 MySQL 服务端，旧版本进程不参与该协调协议。

短信验证码接口目前只校验 Passport 根凭据，**不会直接落库绑定账号**。

旧的网页登录 Cookie-only 账号会显示「需要升级登录」。对这类账号点「校验登录态」不会自动补齐高权限能力，需要重新扫码。


### 签到

- 仪表盘可立即签到，并查看今日成功 / 失败 / 待签数量
- 「系统设置 → 签到调度」可开关自动签到、修改 Cron
- 到达 Cron 时间后，系统会在 1 分钟内随机错峰执行
- 调度器每天东八区 `03:00` 巡检全部账号登录态
- 手动签到、定时签到前，若账号状态不是 `valid`，会先做一次登录态校验

### 管理员

| 页面 | 作用 |
| --- | --- |
| 用户信息列表 | 查看用户、启停账号 |
| 菜单与功能开关 | 控制各菜单对普通用户 / 管理员是否可见 |
| 系统设置 | SMTP、邀请码、公告邮件群发 |

`admin_menu_management` 是管理员保底入口，后台不允许把它隐藏掉。

## 项目结构

```text
.
├─ backend/
│  ├─ app/
│  │  ├─ api/          # FastAPI 路由：auth / accounts / tasks / logs / admin
│  │  ├─ models/       # SQLAlchemy 模型
│  │  ├─ schemas/      # Pydantic 响应模型
│  │  ├─ services/     # 登录、签到、调度、通知等业务逻辑
│  │  ├─ plugins/      # 签到插件入口
│  │  ├─ utils/        # 加密、DS、设备指纹、时区
│  │  ├─ config.py
│  │  ├─ database.py
│  │  └─ main.py       # 应用入口、生命周期、扫码 WebSocket
│  ├─ tests/           # unittest，依赖独立 MySQL 测试库
│  ├─ Dockerfile
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ components/
│  │  ├─ views/        # 仪表盘、账号、日志、设置、管理页
│  │  ├─ stores/
│  │  ├─ router/
│  │  └─ styles/
│  ├─ tests/
│  ├─ nginx.conf
│  └─ Dockerfile
├─ docs/maintenance/   # 登录凭据等长文维护说明
├─ docker-compose.yml
└─ .env.example
```

## 本地开发

后端：

```powershell
cd backend
.\.venv313\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

代码约定：

- Python 4 空格，Vue / TypeScript / CSS 2 空格
- Python 模块与函数用 `snake_case`；Vue 页面用 PascalCase，例如 `AdminUsers.vue`
- 业务规则、兼容约束或失败风险不明显时，保留中文维护注释
- 不要提交 `.env`、`frontend/dist/`、`.venv*`、`.playwright-cli/`、`output/` 或临时数据库文件

## 测试

后端测试使用 `unittest`，**必须**指向独立 MySQL schema。测试基座会在每个用例前建表并清空所有表，不要把 `TEST_DATABASE_URL` 指向正式业务库。

```powershell
cd backend
$env:TEST_DATABASE_URL="mysql+asyncmy://miyoushe:change_me_mysql_password@127.0.0.1:3306/miyoushe_test?charset=utf8mb4"
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
.\.venv313\Scripts\python.exe -m compileall app
```

前端：

```powershell
cd frontend
npm test
npm run build
```

`npm test` 跑 TypeScript 回归脚本；`npm run build` 会先 `vue-tsc --noEmit` 再打包。

涉及登录、调度或 API 行为变更时，请同步补充后端测试。UI 改动建议同时看桌面、平板、手机和深色模式。

## 故障排查

**签到失败或提示维护中**  
先看签到日志里的上游错误，不要只看状态标签。崩坏 3 与绝区零使用独立活动参数 / 接口路径，不能和原神、星铁的通用 `event/luna` 配置合并。

**邮件没发出去**  
同时检查：系统 SMTP 是否启用、用户是否填了接收邮箱、个人通知开关、通知策略是否为「仅失败时通知」。管理员群发不会走个人 `email_notify` / `notify_on`。

**反复提示需要重新扫码**  
账号进入 `reauth_required` 表示工作 Cookie 和根凭据都已无法自动修复。继续点「校验登录态」只会得到同一结论，应直接重新扫码。失效邮件默认只在首次进入该状态时发送一次。

**重启后全部账号无法解密**  
先确认 `ENCRYPTION_KEY` 是否固定，不要当成官方登录接口失效。

**Docker 日志时间不对**  
容器时区必须是 `Asia/Shanghai`。若 `docker exec -it miyoushe-backend date` 不是 CST/+08，重建后端镜像：

```powershell
docker compose up -d --build backend
```

不要把容器时区改成宿主时区。

## 贡献指南

提交信息使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```text
feat(frontend): 支持按游戏筛选签到日志
fix(signin): 修正崩坏3活动参数
docs(readme): 按当前源码重写说明
```

Pull Request 请写明：

- 用户可见的变化
- 验证命令（后端测试、前端 `npm test` / `npm run build`）
- 配置或数据库影响
- 前端改动附截图

仓库协作约定见 [AGENTS.md](AGENTS.md)。

## 相关文档

- [环境变量示例](.env.example)
- [Docker Compose](docker-compose.yml)
