# 米游社签到平台：仓库协作规则

## 适用范围

- 本文件适用于整个仓库，仅补充项目约束；与适用的全局规则及子目录 `AGENTS.md` 叠加使用，用户最新指令优先
- 开始工作先查看当前 Git 状态和相关 diff，保留已有改动；文档与实现不一致时核对当前代码，不将历史说明直接视为现状
- 开发与部署说明见 `README.md`；登录凭据维护前先读 `docs/maintenance/passport-high-privilege-login.md`

## 目录与职责

- `backend/app/main.py`：FastAPI 入口、生命周期与 WebSocket 登录入口
- `backend/app/api/`：HTTP 路由；`schemas/`：接口数据结构；`models/`：SQLAlchemy 模型
- `backend/app/services/`：登录、凭据维护、签到、调度、通知和系统配置等业务逻辑；`utils/`：时间、加密、设备参数等公共工具
- `backend/app/config.py`、`database.py`：配置读取、数据库连接及初始化
- `backend/tests/`：Python unittest 用例与 MySQL 测试基座
- `frontend/src/views/`、`components/`：页面与共享组件；`api/`、`stores/`、`router/`：请求、状态与路由；`styles/`、`utils/`、`constants/`：样式、工具与常量
- `frontend/tests/`：前端回归用例；`frontend/package.json`：前端脚本与依赖的依据，在 `frontend/` 内执行 npm 命令
- `docs/maintenance/`：维护说明；`.env.example`：配置示例；`docker-compose.yml`：MySQL、后端和前端的容器编排

## 实现约定

- Python 使用 4 空格缩进，模块与函数用 `snake_case`；Vue、TypeScript、CSS 使用 2 空格缩进，组件与页面用 `PascalCase`
- 路由复用服务层逻辑；修改接口字段时同步检查后端 schema、前端请求类型、状态和消费页面，必要时更新维护文档
- 登录、调度或 API 行为变更应补充或更新有意义的回归用例；编写用例与执行测试分开，运行条件见下文
- 复杂业务边界和易误改区域使用中文注释，句末不保留句号；不为统一格式批量改写旧注释

## 关键业务边界

### 登录与凭据

- 正式登录底座为官方 `Passport/HoyoPlay`；二维码用于绑定、升级与重新登录，短信验证码入口只校验根凭据，不直接落库绑定账号
- 区分高权限根凭据与派生工作 Cookie（`cookie_encrypted`），不要把工作 Cookie 失效直接等同于根凭据失效
- 工作 Cookie 失效时优先使用根凭据修复；保留 `credential_status`、`cookie_status`、`has_high_privilege_auth` 与 `upgrade_required` 的分层语义
- 旧网页登录 Cookie-only 账号走升级提示，不恢复为正式高权限来源；保留重新登录通知的去重机制
- 根凭据、Cookie 等敏感数据保持加密存储；`ENCRYPTION_KEY` 必须显式固定，不随意更换导致已有密文不可解密

### 数据库与时间

- 运行时与测试均为 MySQL-only，不恢复 SQLite 运行时、迁移脚本或测试回退路径
- 配置使用 `mysql+asyncmy://`；运行时现有 MySQL URL 归一化兼容由 `backend/app/database.py` 维护，测试库要求显式使用异步连接串
- 修改模型时检查已有 MySQL 库的补表、补列流程，不能假设 `create_all()` 会更新既有表结构
- `system_settings` 默认单例行使用独立事务初始化，不为补默认配置而提交共享业务 session
- 业务日期、调度、接口时间、前端展示及日志统一为 `Asia/Shanghai`，不增加可选时区或按浏览器本地时区展示
- 数据库存储仍使用 UTC 绝对时刻，接口输出带 `+08:00`，JWT `exp` 使用 UTC；复用后端 `utils/timezone.py` 和前端 `utils/datetime.ts`

### 签到、通知与权限

- 手动和定时签到复用业务与通知策略，避免状态、日志及通知语义分叉
- 保留各游戏独立的活动号、URL、Referer 和 `x-rpc-signgame` 覆盖能力；崩坏3与绝区零不能直接合并为原神、星铁的通用请求参数
- 不随意删减 `DS`、设备参数或风控延迟；具体配置以 `backend/app/services/checkin.py` 及相关工具为准
- 系统 SMTP、用户通知邮箱和个人通知策略是不同层次；管理员群发通知不套用个人签到通知开关
- 注册、登录态恢复和 `/api/auth/me` 保持同一套 `visible_menu_keys` 语义；保留 `admin_menu_management` 管理员入口，菜单显隐不能替代服务端权限校验

## 验证与运行

默认采用代码审查、针对性检索、diff 检查及必要的静态检查或构建，不主动运行自动化测试。以下命令供对应任务使用，不是每次修改的必跑清单。仅修改文档时核对内容、路径和 diff 即可。

静态检查与构建分别在指定目录运行：

```powershell
# 工作目录：backend
.\.venv313\Scripts\python.exe -m compileall app

# 工作目录：frontend
npm run build
```

`npm run build` 包含 `vue-tsc --noEmit` 与 Vite 构建。优先使用已有依赖环境；缺少解释器或依赖时说明限制，不擅自安装或改动环境。

仅在用户明确要求自动化测试及其范围后，选择对应测试命令；下面列出的是全量入口：

```powershell
# 工作目录：backend
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v

# 工作目录：frontend
npm test
```

后端数据库测试必须显式配置 `TEST_DATABASE_URL`，并确认授权范围内的独立测试 schema。测试基座会建表、清空表，部分用例会重建表结构；不得指向正式库或有需保留数据的开发库，也不得在缺少测试库时回退到 SQLite。

涉及界面或运行态行为时，提供人工操作步骤与预期结果；UI 改动按相关性覆盖桌面、平板、手机和深色模式。交付时列明已完成的验证与未验证项，构建通过不代表人工验收通过。

以下为开发启动入口，仅在已授权的运行任务中使用；后端启动会初始化数据库并启动调度器，不能当作无副作用的静态验证：

```powershell
# 工作目录：backend
.\.venv313\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 工作目录：frontend
npm run dev
```

仓库根目录的 `docker compose up -d --build` 会构建并启动完整服务，须有明确的环境或部署授权后执行。

## 配置、产物与交付

- 密钥与凭据放在 `.env` 或环境变量中，不硬编码、不提交，也不在日志、文档或回复中输出真实值；配置说明使用占位符
- 修改登录参数、SMTP、数据库默认值或配置项时检查现有部署兼容性，并按需同步 `.env.example`、README 和维护说明
- 不提交虚拟环境、`node_modules/`、`frontend/dist/`、自动生成的前端类型声明、`.playwright-cli/`、`output/`、日志或临时数据库；避免构建产物混入业务 diff
- 提交采用 Conventional Commits，例如 `fix(signin): ...`、`feat(frontend): ...`；只有用户授权提交或远程操作时才执行相应动作
- PR 说明用户可见变化、实际验证结果、未验证项及配置或迁移影响；界面改动附可用截图或人工验收说明，不声称未执行的验证已通过
