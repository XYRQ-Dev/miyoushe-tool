# 米游社自动签到 Web 平台

基于 `FastAPI + Vue 3 + SQLite + Playwright` 的米游社自动签到管理平台，支持扫码登录、手动/定时签到、签到日志查看、邮件通知和管理员后台配置。

## 功能概览

- 米游社账号扫码登录与 Cookie 保存
- 原神、星穹铁道等国服角色签到
- 手动立即签到与定时签到
- 手动签到与定时签到共用同一套邮件通知策略
- 签到日志分页、状态筛选、日期筛选与最近 7 天日历统计
- 日志接口与前端展示统一按东八区语义处理
- 用户个人通知邮箱、通知策略与深色模式设置
- 管理员系统 SMTP 配置与用户启停管理

## 目录结构

```text
.
├─ backend/   后端 FastAPI 服务
├─ frontend/  前端 Vue 3 管理界面
├─ data/      SQLite 数据目录
├─ .env.example
└─ docker-compose.yml
```

## 本地开发

### 1. 后端

建议使用 `backend/.venv313` 对应的 Python 3.13 环境。

```powershell
cd backend
python -m venv .venv313
.\.venv313\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

默认开发访问：

- 前端：[http://localhost:5173](http://localhost:5173)
- 后端健康检查：[http://localhost:8000/api/health](http://localhost:8000/api/health)

## Docker 部署

根目录提供了 `docker-compose.yml`，可直接启动前后端：

```powershell
docker compose up -d --build
```

默认端口：

- 前端：`80`
- 后端：`8000`

默认 Docker 配置会把后端容器时区固定为 `Asia/Shanghai`，因此 `docker logs miyoushe-backend`
里看到的业务日志和 Uvicorn 访问日志默认都是东八区时间；如果脱离 Docker 单独运行，则日志时间跟随该进程所在系统时区。

## 配置说明

项目当前有三类常用配置：

### 1. 邮件通知配置

- 系统 SMTP：管理员在后台“系统邮件配置”中维护，决定系统能否发信
- 用户通知邮箱：普通用户在个人设置里维护，决定邮件发给谁
- 通知策略：支持“每次都通知”和“仅失败时通知”

环境变量仍然保留作为系统 SMTP 的回退配置，见 [.env.example](/D:/UnityProject/MiHaYouTool/miyoushe-tool/.env.example) 与 [docker-compose.yml](/D:/UnityProject/MiHaYouTool/miyoushe-tool/docker-compose.yml)。

### 2. 时间与日志配置

- 应用层日期判断和日志接口展示按 `Asia/Shanghai` 处理
- Docker 部署下，后端容器默认也会固定为 `Asia/Shanghai`，因此 `docker logs` 中看到的业务日志和 Uvicorn 访问日志默认也是东八区
- 如果脱离 Docker 单独运行，控制台日志时间跟随运行进程所在系统时区

### 3. 外观配置

- 前端支持浅色 / 深色模式切换
- 深色模式仅保存在浏览器本地，不会写入服务端用户资料

## 常见问题

### 1. `/api/tasks/execute` 返回 500

如果是从旧版本直接升级，旧 SQLite 库里可能没有 `system_settings` 表。当前版本已经在后端做了自动补建兼容，但前提是服务进程已经更新到最新代码并完成重启。

### 2. 星穹铁道签到状态失败

当前签到链路已按 Starward 的国服移动端请求机制对齐，包含：

- `act_id / x-rpc-signgame`
- Hyperion 风格 `User-Agent`
- `DS`
- `x-rpc-device_id / x-rpc-device_fp`
- 查询后短延迟与角色间风控延迟

如果仍有失败，请优先查看签到日志中的上游错误信息，而不是只看状态标签。

### 3. 邮件通知不发送

请同时检查：

- 管理员是否已配置系统 SMTP
- 用户是否填写了接收邮箱
- 用户是否开启了邮件通知
- 通知策略是否为“仅失败时通知”
- 手动点击“立即签到”后是否已重启到最新后端代码；当前版本中，手动签到也会复用定时任务通知链路

如果日志里出现类似 `The "From" header is missing or invalid`，通常是 SMTP 发件人头格式问题；当前代码已经兼容中文发件人名称，前提是服务已更新到最新版本并重启。

### 4. Docker 日志时间看起来不对

当前项目的 `docker logs` 时间依赖后端容器系统时区，而不是接口里的 `APP_TIMEZONE` 配置。
默认 `docker-compose.yml` 已将后端容器固定为 `Asia/Shanghai`；若你改过镜像、运行参数或未重建容器，请重新执行：

```powershell
docker compose up -d --build backend
docker exec -it miyoushe-backend date
```

若 `date` 输出不是东八区时间，则说明当前运行中的容器没有吃到新的时区配置。

### 5. 签到日志时间与 Docker 日志时间对不上

这是两个不同层面的时间：

- 前端“签到日志”“今日状态”“最近 7 天日历”来自应用接口，按东八区语义换算与筛选
- `docker logs` 来自容器控制台输出，按容器系统时区显示

当前默认 Docker 配置已经把二者统一成东八区；若你修改过部署方式，请分别检查接口返回时间和容器 `date` 输出。

## 验证命令

后端：

```powershell
cd backend
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
.\.venv313\Scripts\python.exe -m compileall app
```

前端：

```powershell
cd frontend
npm run build
```

## 维护提示

- 本项目当前没有 Alembic 迁移，新增表结构时要特别注意旧 SQLite 库的兼容升级路径
- 签到链路不要随意删减设备参数、`DS` 或风控延迟，这些机制必须成套存在
- 管理员 SMTP 与用户通知邮箱是两层配置，排障时不要混淆
- 手动签到、定时签到、邮件通知与日志展示已经逐步统一语义；后续修改时不要让两条执行链路再次分叉
- 日志接口时间和 Docker 控制台日志虽然都默认是东八区，但来源不同；排障时要区分“接口换算问题”和“容器时区问题”
