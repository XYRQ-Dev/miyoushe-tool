# 米游社自动签到 Web 平台

基于 `FastAPI + Vue 3 + MySQL 8` 的米游社账号资产管理平台，当前正式登录底座为米游社官方 `Passport/HoyoPlay` 高权限登录，支持高权限账号绑定、登录态校验与自动修复、手动/定时签到、角色资产总览、抽卡记录归档、兑换码中心、账号健康中心、邮件通知和管理员后台配置。

## 功能概览

- 米游社官方 Passport 高权限登录，支持二维码登录与短信验证码根凭据校验
- 账号登录态校验、工作 Cookie 自动修复与旧网页登录账号升级提示
- 原神、星穹铁道、崩坏3、绝区零的国服官服角色签到
- 手动立即签到与定时签到
- 手动签到与定时签到共用同一套邮件通知策略
- 签到日志分页、状态筛选、日期筛选与最近 7 天日历统计
- 日志接口与前端展示统一按东八区语义处理
- 角色资产总览，按账号聚合角色、抽卡与兑换入口
- 账号健康中心，聚合登录态、签到结果与重登风险
- 抽卡记录中心（HuTao 风格）：
  - 支持链接导入、原神账号自动导入、UIGF v4.2 导入导出
  - 自动扫描：星穹铁道支持基础 URL 自动扫描所有卡池
  - 深度统计：实时计算保底进度（Pity）、平均出金抽数、分池数据分析
  - 可视化展示：五星出金历史时间轴、欧非程度高亮、垫抽进度条
  - 档案隔离：按 `账号 + 游戏 + 角色 UID` 严格隔离与重置
- 兑换码中心，支持按游戏筛选账号、批量执行与历史批次回看
- 用户个人通知邮箱、通知策略与深色模式设置
- 管理员系统 SMTP 配置、通知邮件群发、菜单与功能开关管理、用户启停管理

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
# 本机已安装 MySQL 时，先创建空库并在 .env 中配置 DATABASE_URL；
# 例如：mysql+asyncmy://miyoushe:change_me_mysql_password@127.0.0.1:3306/miyoushe?charset=utf8mb4
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

根目录提供了 `docker-compose.yml`，默认按 `MySQL 8 + 后端 + 前端` 一起启动：

```powershell
docker compose up -d --build
```

默认端口：

- MySQL：`3306`
- 前端：`80`
- 后端：`8000`

默认 Docker 配置会把后端容器时区固定为 `Asia/Shanghai`，因此 `docker logs miyoushe-backend`
里看到的业务日志和 Uvicorn 访问日志默认都是东八区时间；如果脱离 Docker 单独运行，则日志时间跟随该进程所在系统时区。

### 当前数据库约束

当前项目已经正式收口为 `MySQL-only`：

- 运行时只接受 `mysql+asyncmy://` 连接串
- 不再支持 SQLite 运行时、SQLite 补列、SQLite 迁移脚本或 SQLite 测试路径
- 如你手里仍有旧 SQLite 备份，请把它视为历史备份文件，而不是当前版本可直接接入的正式数据库

## 配置说明

项目当前有六类常用配置：

### 1. 邮件通知配置

- 系统 SMTP：管理员在后台“系统邮件配置”中维护，决定系统能否发信
- 用户通知邮箱：普通用户在个人设置里维护，决定邮件发给谁
- 通知策略：支持“每次都通知”和“仅失败时通知”
- 管理员群发通知：管理员可向“已绑定邮箱且账号启用”的用户批量发送公告邮件；这条链路忽略个人邮件通知开关，避免把系统公告误伤成个人偏好

环境变量仍然保留作为系统 SMTP 的回退配置，见 [.env.example](.env.example) 与 [docker-compose.yml](docker-compose.yml)。

### 2. 数据库配置

- 当前生产默认使用 `MySQL 8`
- 后端读取单一 `DATABASE_URL`
- Docker Compose 通过 `MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD` 启动 MySQL 服务
- 本机直接启动后端时，默认连接目标是 `127.0.0.1:3306`
- 若你要接外部 MySQL，只需覆盖 `DATABASE_URL`，不必继续使用内置 MySQL 容器
- 后端测试必须额外显式提供 `TEST_DATABASE_URL`
- `TEST_DATABASE_URL` 也只接受 `mysql+asyncmy://`，缺失或写成其他方言时测试会失败快，而不是偷偷回落到 SQLite

### 3. 时间与日志配置

- 应用层日期判断和日志接口展示按 `Asia/Shanghai` 处理
- Docker 部署下，后端容器默认也会固定为 `Asia/Shanghai`，因此 `docker logs` 中看到的业务日志和 Uvicorn 访问日志默认也是东八区
- 如果脱离 Docker 单独运行，控制台日志时间跟随运行进程所在系统时区

### 4. 加密密钥配置

- `ENCRYPTION_KEY` 必须通过 `.env` 或环境变量显式固定
- 如果仍使用运行期随机默认值，服务重启后旧高权限根凭据、工作 Cookie 与其他敏感密文都会无法解密
- 这和“网页登录扫码能否拿到 `stoken`”是两个不同问题，不能混为一谈
- 当前高权限登录维护边界见 [docs/maintenance/passport-high-privilege-login.md](docs/maintenance/passport-high-privilege-login.md)
- 网页登录为什么不再作为正式能力，见 [docs/maintenance/web-login-credential-boundary.md](docs/maintenance/web-login-credential-boundary.md)

### 5. 外观配置

- 前端支持浅色 / 深色模式切换
- 深色模式仅保存在浏览器本地，不会写入服务端用户资料

### 6. 管理员菜单与功能开关管理

- 管理员可在后台统一控制各个导航菜单是否对普通用户 / 管理员显示
- `admin_menu_management` 属于管理员保底入口，不允许在后台被隐藏
- 登录态恢复、注册返回与 `/api/auth/me` 会统一返回 `visible_menu_keys`

菜单显隐属于系统级全局配置，保存在 `system_settings.menu_visibility_json` 中。

### 7. 登录态校验

当前版本的正式账号链路已经切到 `Passport/HoyoPlay` 高权限登录，运行时采用“两层凭据模型”：

- 根凭据：`stoken / ltoken / cookie_token / login_ticket / stuid / mid`
- 工作 Cookie：`cookie_encrypted`

系统对外的稳定语义是：

- 调度器每天会统一巡检账号登录态
- 手动签到、定时签到前，如果账号状态不是 `valid`，也会先做一次登录态校验
- 工作 Cookie 失效时，系统会优先尝试利用高权限根凭据自动补齐；只有根凭据也失效时才会进入 `reauth_required`
- 旧网页登录 Cookie-only 账号会被明确标记为“需要升级登录”，不再被当成正式高权限账号
- 网页扫码链路只保留为历史背景诊断结论，不再作为正式产品能力

账号中心当前会显示：

- 当前登录态
- 是否已接入高权限根凭据
- 最近一次校验时间
- 最近一次校验结果摘要

抽卡记录中心当前会显示：

- 正式交换协议为 `UIGF v4.2`
- 抽卡档案正式维度为 `账号 + 游戏 + 角色 UID`
- 前端必须先选择“账号 -> 游戏 -> 角色 UID”，同账号同游戏的多个 UID 会严格隔离
- 原神支持“手贴完整链接 / 从账号自动导入 / 导入导出 UIGF”，且自动导入必须显式绑定当前所选 `game_uid`
- 星穹铁道当前只支持“手贴完整链接 / 导入导出 UIGF”
- UIGF 导入导出都严格按当前 `game_uid` 工作，不再把同游戏多个 UID 压平成一份档案

### 8. 签到链路差异

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

### 1. 为什么后端测试必须配置 TEST_DATABASE_URL

当前后端测试底座已经切到 `MySQL-only`，不会再自动回落到 SQLite。

正确做法是：

- 先准备一个专用测试 schema，例如 `miyoushe_test`
- 显式设置 `TEST_DATABASE_URL=mysql+asyncmy://<user>:<password>@127.0.0.1:3306/miyoushe_test?charset=utf8mb4`
- 再运行后端测试

注意：

- 测试基座会在每个用例前建表并清空所有表
- 不要把 `TEST_DATABASE_URL` 指向正式业务库
- 如果缺少测试库或权限不足，测试会直接失败，而不是偷偷换到别的数据库

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

如果是管理员群发通知，请额外确认：

- 后台可筛选到“已绑定邮箱且账号启用”的收件人
- 当前 SMTP 配置可正常发信；群发通知不会复用用户个人 `email_notify` / `notify_on` 偏好

如果日志里出现类似 `The "From" header is missing or invalid`，通常是 SMTP 发件人头格式问题；当前代码已经兼容中文发件人名称，前提是服务已更新到最新版本并重启。

### 4. 登录态失效后为什么反复提示需要重新扫码

当账号进入 `reauth_required` 时，表示当前系统已经确认：

- 当前工作 Cookie 已无法直接使用
- 且 Passport 高权限根凭据也已经无法继续自动修复
- 需要通过重新扫码更新高权限登录态

这时继续点“校验登录态”通常只会重复得到同一结论，正确处理方式是：

- 直接点击账号卡片里的“重新扫码登录”
- 扫码成功后，系统会覆盖更新原账号的高权限根凭据、工作 Cookie 和角色列表

为了避免打扰，登录态失效邮件默认只会在账号首次进入 `reauth_required` 时发送一次；
如果账号恢复后再次失效，才会重新发送。

### 5. 为什么管理员菜单管理里不能把自己入口也隐藏掉

`admin_menu_management` 是管理员保底入口，目的是避免后台把“菜单与功能开关管理”本身一起关掉后没有恢复路径。

如果你需要临时隐藏某些后台能力，请关闭对应业务菜单或功能开关，不要关闭菜单管理入口本身。

### 6. Docker 日志时间看起来不对

当前项目的 `docker logs` 时间依赖后端容器系统时区，而不是接口里的 `APP_TIMEZONE` 配置。
默认 `docker-compose.yml` 已将后端容器固定为 `Asia/Shanghai`；若你改过镜像、运行参数或未重建容器，请重新执行：

```powershell
docker compose up -d --build backend
docker exec -it miyoushe-backend date
```

若 `date` 输出不是东八区时间，则说明当前运行中的容器没有吃到新的时区配置。

### 7. 签到日志时间与 Docker 日志时间对不上

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

登录态校验相关回归测试当前也包含在后端总测试集中，重点覆盖：

- Cookie 校验与 `reauth_required` 状态流转
- `reauth_required` 邮件通知去重
- `system_settings` 默认配置行的持久化与事务边界
- 注册响应与 `/api/auth/me` 返回的菜单可见性一致性
- 账号列表新字段与手动维护接口
- SQLite 核心数据迁移到新库的约束与校验

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

- 当前生产默认以 MySQL 8 为准；如果需要从 SQLite 升级，请走显式迁移脚本，不要再依赖“重启后自动补列”
- 当前版本已不再支持 SQLite 迁移脚本、SQLite 兼容补列或 SQLite 测试路径；请直接维护 MySQL 数据库与专用测试库
- `ENCRYPTION_KEY` 必须固定；如果仍使用运行期随机默认值，服务重启后旧高权限根凭据与工作 Cookie 都会无法解密
- 正式登录底座已经切到官方 Passport，高权限凭据边界见 [docs/maintenance/passport-high-privilege-login.md](docs/maintenance/passport-high-privilege-login.md)
- 历史网页登录链路的凭据边界见 [docs/maintenance/web-login-credential-boundary.md](docs/maintenance/web-login-credential-boundary.md)，不要再基于拿不到的数据设计产品能力
- 账号进入 `reauth_required` 后，通知和 UI 都要保持“明确但不过度惊扰”的语义，避免一边高频发信、一边在页面里堆原始错误文本
- 抽卡正式交换协议为 `UIGF v4.2`；不要再把私有 JSON records 数组当成对外标准
- 抽卡档案正式维度是 `账号 + 游戏 + game_uid`；任何跳到 `/gacha` 的入口都必须带上目标 `game_uid`
- 原神账号自动导入目前只支持原神，且必须显式指定目标 `game_uid`；看到 `hkrpg` 的 UIGF 字段并不意味着星穹铁道也已支持账号直连导入
- 后端测试前必须确认 `TEST_DATABASE_URL` 指向独立测试 schema；缺少可写测试库时，不要拿正式库跑清库测试
- 签到链路不要随意删减设备参数、`DS` 或风控延迟，这些机制必须成套存在
- 崩坏3与绝区零存在游戏专属活动参数与请求头差异，后续若要重构签到配置，请先保留“按游戏覆盖 URL / Referer / signgame”的能力
- 管理员 SMTP 与用户通知邮箱是两层配置，排障时不要混淆
- `system_settings` 的默认单例配置必须用独立事务初始化；不要为了“顺手补一行默认数据”直接提交共享业务 session
- `/api/auth/register`、`/api/auth/me` 与前端路由守卫依赖同一套 `visible_menu_keys` 语义，后续不要再出现“注册返回”和“登录态恢复返回”不一致
- 手动签到、定时签到、邮件通知与日志展示已经逐步统一语义；后续修改时不要让两条执行链路再次分叉
- 日志接口时间和 Docker 控制台日志虽然都默认是东八区，但来源不同；排障时要区分“接口换算问题”和“容器时区问题”

## 鸣谢与参考

本项目的开发过程中参考了以下优秀开源项目或协议，排名不分先后：

- [Starward](https://github.com/Scighost/Starward)：参考了其国服签到请求机制与设备参数对齐逻辑。
- [Snap Hutao](https://github.com/DGP-Studio/Snap.Hutao)：参考了其优秀的抽卡分析 UI 布局、保底计算逻辑与可视化思路。
- [UIGF (Unified Impact Gacha Log Format)](https://uigf.org/)：本项目抽卡记录交换协议遵循 UIGF v4.2 标准。
