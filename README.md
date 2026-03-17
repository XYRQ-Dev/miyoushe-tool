# 米游社自动签到 Web 平台

基于 `FastAPI + Vue 3 + SQLite + Playwright` 的米游社自动签到管理平台，支持扫码登录、登录态自动维护、手动/定时签到、签到日志查看、邮件通知和管理员后台配置。

## 功能概览

- 米游社账号扫码登录与 Cookie 保存
- 账号登录态自动校验、`stoken` 自动续期与失效重登提醒
- 原神、星穹铁道、崩坏3、绝区零的国服官服角色签到
- 手动立即签到与定时签到
- 手动签到与定时签到共用同一套邮件通知策略
- 签到日志分页、状态筛选、日期筛选与最近 7 天日历统计
- 日志接口与前端展示统一按东八区语义处理
- 用户个人通知邮箱、通知策略与深色模式设置
- 管理员系统 SMTP 配置与用户启停管理

## 当前支持范围

当前版本仅针对米游社国服官服签到做了适配，已验证接入的 `game_biz` 如下：

- `hk4e_cn` / `hk4e_bilibili`：原神
- `hkrpg_cn` / `hkrpg_bilibili`：崩坏：星穹铁道
- `bh3_cn`：崩坏3国服官服
- `nap_cn`：绝区零国服官服

暂不在本项目当前保证范围内的情况：

- 崩坏3 B 服等非 `bh3_cn` 角色
- 绝区零国际服或非 `nap_cn` 角色
- 其他虽然能通过账号导入拿到、但尚未完成签到链路验证的 `game_biz`

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

项目当前有四类常用配置：

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

### 4. 登录态维护

当前版本已经把“账号 Cookie 是否有效”从单纯检测升级为一条完整维护链路：

- 账号导入或重新扫码后，后端会尽量从 Cookie 中提取并保存自动续期所需的 `stoken / stuid / mid`
- 调度器每天会统一校验账号登录态；如果 Cookie 已过期，会优先尝试自动续期
- 手动签到、定时签到前，如果账号状态不是 `valid`，也会先尝试恢复登录态
- 若自动续期明确失败，账号会进入 `reauth_required`，并向用户发送“需要重新扫码”的专用邮件提醒

账号中心当前会显示：

- 当前登录态
- 最近一次校验 / 维护时间
- 最近一次维护结果摘要
- 当前账号是否支持自动续期

有两个容易误解的边界：

- `刷新 Cookie` 已明确表示“重新扫码登录”，不是自动续期接口
- 如果历史账号缺少 `stoken` 或 `mid`，当前实现不会隐式补救，而是直接提示“仅支持重新扫码”

### 5. 签到链路差异

当前签到实现不是所有游戏都完全共用同一组接口参数：

- 原神、星穹铁道继续使用通用 `https://api-takumi.mihoyo.com/event/luna/info|sign`
- 崩坏3当前也沿用通用 `event/luna` 链路，但活动号与请求头对齐参考实现：
  - `act_id = e202306201626331`
  - 不发送 `x-rpc-signgame=bh3`
  - 使用崩坏3活动页专用 `Referer`
- 绝区零使用独立的 `https://act-nap-api.mihoyo.com/event/luna/zzz/*` 链路：
  - `info = /event/luna/zzz/info`
  - `sign = /event/luna/zzz/sign`
  - 继续发送 `x-rpc-signgame=zzz`

这部分配置不要因为“看起来和其他游戏差不多”而被合并回统一常量；最常见的后果不是直接报参数错，而是上游返回维护态、未登录态或泛化失败，后续排障会非常困难。

## 常见问题

### 1. `/api/tasks/execute` 返回 500

如果是从旧版本直接升级，旧 SQLite 库里可能没有 `system_settings` 表。当前版本已经在后端做了自动补建兼容，但前提是服务进程已经更新到最新代码并完成重启。

### 2. 签到状态失败或提示维护中

当前签到链路已按 Starward 的国服移动端请求机制对齐，包含：

- `act_id / x-rpc-signgame`
- Hyperion 风格 `User-Agent`
- `DS`
- `x-rpc-device_id / x-rpc-device_fp`
- 查询后短延迟与角色间风控延迟

如果仍有失败，请优先查看签到日志中的上游错误信息，而不是只看状态标签。

补充说明：

- 崩坏3与绝区零并不是完全复用原神/星铁的同一组活动参数
- 如果崩坏3出现 `-500007` 一类维护态，优先确认服务是否已更新到包含新 `act_id=e202306201626331` 的版本
- 如果崩坏3或绝区零返回 `-100`，通常表示已经命中正确上游接口，但当前登录态无效或 Cookie 已失效

### 3. 邮件通知不发送

请同时检查：

- 管理员是否已配置系统 SMTP
- 用户是否填写了接收邮箱
- 用户是否开启了邮件通知
- 通知策略是否为“仅失败时通知”
- 手动点击“立即签到”后是否已重启到最新后端代码；当前版本中，手动签到也会复用定时任务通知链路

如果日志里出现类似 `The "From" header is missing or invalid`，通常是 SMTP 发件人头格式问题；当前代码已经兼容中文发件人名称，前提是服务已更新到最新版本并重启。

### 4. 登录态失效后为什么反复提示需要重新扫码

当账号进入 `reauth_required` 时，表示当前系统已经确认：

- Cookie 已无法直接使用
- 自动续期凭据也无法恢复登录态，或者账号本身缺少续期凭据

这时继续点“校验并续期”通常只会重复得到同一结论，正确处理方式是：

- 直接点击账号卡片里的“重新扫码登录”
- 扫码成功后，系统会覆盖更新原账号的 Cookie、续期凭据和角色列表

为了避免打扰，登录态失效邮件默认只会在账号首次进入 `reauth_required` 时发送一次；
如果账号恢复后再次失效，才会重新发送。

### 5. Docker 日志时间看起来不对

当前项目的 `docker logs` 时间依赖后端容器系统时区，而不是接口里的 `APP_TIMEZONE` 配置。
默认 `docker-compose.yml` 已将后端容器固定为 `Asia/Shanghai`；若你改过镜像、运行参数或未重建容器，请重新执行：

```powershell
docker compose up -d --build backend
docker exec -it miyoushe-backend date
```

若 `date` 输出不是东八区时间，则说明当前运行中的容器没有吃到新的时区配置。

### 6. 签到日志时间与 Docker 日志时间对不上

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

登录态维护相关回归测试当前也包含在后端总测试集中，重点覆盖：

- Cookie 校验与自动续期状态流转
- `reauth_required` 邮件通知去重
- 账号列表新字段与手动维护接口
- 旧 SQLite 库自动补列

前端：

```powershell
cd frontend
npm run build
```

非侵入式联通性排查时，可优先观察：

- 崩坏3 `home` 是否能对 `act_id=e202306201626331` 返回 `retcode=0`
- 崩坏3 `info` 在不带有效 Cookie 的情况下是否返回 `retcode=-100`
- 绝区零 `zzz/info` 在不带有效 Cookie 的情况下是否返回 `retcode=-100`

## 维护提示

- 本项目当前没有 Alembic 迁移，新增表结构时要特别注意旧 SQLite 库的兼容升级路径
- 登录态维护依赖 `stoken / stuid / mid`；后续若调整扫码登录或 Cookie 存储逻辑，必须同步验证自动续期是否还能成立
- 账号进入 `reauth_required` 后，通知和 UI 都要保持“明确但不过度惊扰”的语义，避免一边高频发信、一边在页面里堆原始错误文本
- 签到链路不要随意删减设备参数、`DS` 或风控延迟，这些机制必须成套存在
- 崩坏3与绝区零存在游戏专属活动参数与请求头差异，后续若要重构签到配置，请先保留“按游戏覆盖 URL / Referer / signgame”的能力
- 管理员 SMTP 与用户通知邮箱是两层配置，排障时不要混淆
- 手动签到、定时签到、邮件通知与日志展示已经逐步统一语义；后续修改时不要让两条执行链路再次分叉
- 日志接口时间和 Docker 控制台日志虽然都默认是东八区，但来源不同；排障时要区分“接口换算问题”和“容器时区问题”
