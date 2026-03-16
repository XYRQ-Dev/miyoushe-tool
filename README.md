# 米游社自动签到 Web 平台

基于 `FastAPI + Vue 3 + SQLite + Playwright` 的米游社自动签到管理平台，支持扫码登录、手动/定时签到、签到日志查看和邮件通知。

## 功能概览

- 米游社账号扫码登录与 Cookie 保存
- 原神、星穹铁道等国服角色签到
- 手动立即签到与定时签到
- 签到日志查看与状态统计
- 用户个人通知邮箱设置
- 管理员系统 SMTP 配置

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

## 配置说明

项目支持两层邮件配置：

- 系统 SMTP：管理员在后台“系统邮件配置”中维护，决定系统能否发信
- 用户通知邮箱：普通用户在个人设置里维护，决定邮件发给谁

环境变量仍然保留作为系统 SMTP 的回退配置，见 [.env.example](/D:/UnityProject/MiHaYouTool/miyoushe-tool/.env.example) 与 [docker-compose.yml](/D:/UnityProject/MiHaYouTool/miyoushe-tool/docker-compose.yml)。

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
