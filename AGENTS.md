# 米游社签到平台：项目指南

本文件适用于整个仓库，补充全局协作规则；修改子目录前读取该路径下适用的 `AGENTS.md` 或 `AGENTS.override.md`。用户当前明确指令优先于项目约定。

## 项目与入口

自托管的米游社国服账号管理与签到平台：FastAPI 后端、Vue 3 + TypeScript 前端、MySQL 数据库，支持 Docker Compose 部署。

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 生命周期与 WebSocket 登录入口 |
| `backend/app/api/`、`schemas/`、`models/` | HTTP 路由、接口结构、SQLAlchemy 模型；后两者也位于 `backend/app/` |
| `backend/app/services/`、`backend/app/utils/` | 业务服务；时间、加密、设备参数等公共工具 |
| `backend/app/config.py`、`backend/app/database.py` | 配置读取、数据库连接与初始化 |
| `frontend/src/views/`、`frontend/src/components/` | 页面与共享组件 |
| `frontend/src/api/`、`stores/`、`router/` | 请求、状态、路由；后两者也位于 `frontend/src/` |
| `backend/tests/`、`frontend/tests/` | 后端 unittest 与前端回归用例 |
| `.env.example`、`docker-compose.yml` | 配置示例与容器编排 |

按任务读取文档，不将历史说明直接当作当前实现：

- 开发、部署与配置：`README.md`
- 登录与凭据维护：先读 `docs/maintenance/passport-high-privilege-login.md`
- 平台令牌签发、校验与刷新：`docs/maintenance/token-purpose-isolation.md`
- 用户删除与并发清理：`docs/maintenance/user-deletion.md`

## 工作方式与实现约定

- 开始先查看 `git status --short` 及任务相关的工作区、暂存区 diff，保留已有改动
- 只读分析不进入实现；实现任务完成授权范围内的最小改动与验证，不顺带重构或格式化无关代码
- Python 使用 4 空格缩进和 `snake_case`；Vue、TypeScript、CSS 使用 2 空格缩进，组件与页面用 `PascalCase`
- 路由复用服务层逻辑；接口字段变更同时检查后端 schema、前端请求类型、状态与消费页面，公开 API 按需补充说明
- 登录、调度或 API 行为变更应补充有意义的回归用例；编写用例不等于授权运行测试
- 复杂边界、非显然决策和易误改区域使用中文注释，句末不加句号，不批量改写旧注释
- 修改登录参数、SMTP、数据库默认值或配置项时检查部署兼容性，按需同步 `.env.example`、README 与维护文档

## 必须保持的业务边界

### 登录与凭据

- 正式登录使用官方 `Passport/HoyoPlay`；二维码用于绑定、升级和重新登录，短信验证码入口只校验根凭据，不直接落库绑定账号
- 高权限根凭据与派生工作 Cookie（`cookie_encrypted`）分层处理；工作 Cookie 失效时优先通过根凭据修复，不直接判定根凭据失效
- 保留 `credential_status`、`cookie_status`、`has_high_privilege_auth`、`upgrade_required` 的独立语义及重新登录通知去重
- 旧网页登录 Cookie-only 账号走升级提示，不恢复为正式高权限来源
- 根凭据、Cookie 等敏感数据加密存储；`ENCRYPTION_KEY` 必须显式固定，更换会导致已有密文无法解密

### 数据库与时间

- 运行时和数据库测试均使用 MySQL，不添加 SQLite 运行时、迁移或测试回退
- 配置使用 `mysql+asyncmy://`；保留 `backend/app/database.py` 的现有 MySQL URL 归一化兼容，测试连接串必须显式使用异步驱动
- 模型变更同步检查已有 MySQL 库的补表、补列流程，不能依赖 `create_all()` 更新既有表结构
- `system_settings` 默认单例行在独立事务中初始化，不能为补默认配置提交共享业务 session
- 业务日期、调度、日志和前端展示统一为 `Asia/Shanghai`；数据库存 UTC 绝对时刻，接口输出带 `+08:00`，JWT `exp` 使用 UTC
- 复用 `backend/app/utils/timezone.py` 和 `frontend/src/utils/datetime.ts`，不增加可选时区或浏览器本地时区展示

### 签到、通知与权限

- 手动与定时签到复用业务和通知策略，保持状态、日志、通知语义一致
- 保留各游戏独立的活动号、URL、Referer、`x-rpc-signgame` 覆盖；崩坏 3、绝区零不能直接套用原神、星铁的通用参数
- 保留 `DS`、设备参数与风控延迟，修改前核对 `backend/app/services/checkin.py` 及相关工具
- 区分系统 SMTP、用户通知邮箱、个人通知策略；管理员群发不套用个人签到通知开关
- 注册、登录态恢复和 `/api/auth/me` 使用一致的 `visible_menu_keys` 语义，保留 `admin_menu_management` 管理员入口；菜单显隐不能替代服务端权限校验

## 验证与运行命令

使用 Windows、PowerShell 7 和现有依赖环境；缺少解释器或依赖时报告限制，不擅自安装或更改环境。以下是按需入口，不是每次任务的必跑清单。

| 用途 | 工作目录 | 命令 | 执行条件 |
| --- | --- | --- | --- |
| 后端静态编译 | `backend/` | `.\.venv313\Scripts\python.exe -m compileall app` | 后端代码变更时按需执行 |
| 前端类型检查与构建 | `frontend/` | `npm run build` | 前端代码变更时按需执行，包含 `vue-tsc --noEmit` 和 Vite 构建 |
| 后端全量测试 | `backend/` | `.\.venv313\Scripts\python.exe -m unittest discover -s tests -v` | 仅明确授权全量自动化测试后执行 |
| 前端全量测试 | `frontend/` | `npm test` | 仅明确授权对应自动化测试后执行 |
| 后端开发服务 | `backend/` | `.\.venv313\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | 仅已授权运行任务；会初始化数据库并启动调度器 |
| 前端开发服务 | `frontend/` | `npm run dev` | 仅已授权运行任务 |
| 完整容器服务 | 仓库根目录 | `docker compose up -d --build` | 仅明确授权环境或部署操作后执行 |

- 默认采用代码审查、针对性检索、diff 检查及必要静态检查或构建；仅文档变更核对内容、路径和 diff 即可
- 不主动运行单元、集成、端到端测试或自动化冒烟；用户授权局部测试时只运行对应范围，不自动扩大到全量
- 数据库测试必须显式配置 `TEST_DATABASE_URL` 并确认授权范围内的独立 MySQL 测试 schema；测试基座会建表、清空表，部分用例会重建结构，禁止指向正式库或需保留数据的开发库
- 界面或运行态变更需给出人工操作步骤和预期结果，由用户验收；UI 按相关性覆盖桌面、平板、手机、深色模式，构建通过不代表行为验收通过

## 完成与交付

- 最终检查本次 diff：变更符合任务范围、相关接口与文档一致、已有改动得到保留
- 说明用户可见变化、实际执行的验证及结果、未验证项和剩余风险；受环境或授权限制的验证明确标注，不能声称通过
- 密钥与凭据只放 `.env` 或环境变量，不硬编码、提交或输出真实值；文档使用占位符
- 不提交虚拟环境、`node_modules/`、`frontend/dist/`、自动生成的前端类型声明、`.playwright-cli/`、`output/`、日志或临时数据库
- 提交、远程操作、部署、数据库写入及对外发送遵循全局授权边界；只有用户明确授权相应范围才执行
- 获准提交时使用 Conventional Commits，例如 `fix(signin): ...`；PR 说明用户可见变化、验证结果、未验证项、配置或迁移影响，UI 变更附可用截图或人工验收说明
