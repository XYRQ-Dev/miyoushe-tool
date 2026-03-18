# 实时便笺独立功能开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有菜单管理体系内新增独立的 `notes` 功能开关，关闭后前端不再请求 `/api/notes/*`，后端接口也直接拒绝访问，从而彻底停止实时便笺上游调用。

**Architecture:** 继续复用 `system_settings.menu_visibility_json` 作为唯一功能开关来源，不新增第二套权限系统。`notes` 作为“仪表盘内模块”进入菜单可见性定义，但不作为独立导航项展示；前端基于 `visible_menu_keys` 决定是否渲染并加载便笺面板，后端在 `/api/notes/*` 入口重复校验，保证即使有人绕过前端也不会继续打上游。

**Tech Stack:** FastAPI、SQLAlchemy Async、Pydantic、Vue 3、Pinia、Element Plus、现有 `unittest` 与前端轻量源码回归测试

---

## 文件边界

**后端核心文件**
- 修改: `backend/app/services/menu_visibility.py`
- 修改: `backend/app/services/system_settings.py`
- 修改: `backend/app/schemas/system_setting.py`
- 修改: `backend/app/api/notes.py`
- 测试: `backend/tests/test_notes.py`
- 测试: `backend/tests/test_checkin_and_admin.py`

**前端核心文件**
- 修改: `frontend/src/constants/appMenus.ts`
- 修改: `frontend/src/utils/menuVisibility.ts`
- 修改: `frontend/src/views/Dashboard.vue`
- 修改: `frontend/src/views/Layout.vue`
- 修改: `frontend/src/views/AdminMenuManagement.vue`
- 测试: `frontend/tests/accountRoutePrefill.test.ts`

**约束**
- 不拆独立便笺页面，仍保留在仪表盘内部。
- 不新增新的用户角色或权限表。
- `notes` 必须纳入管理员“菜单与功能开关”页，但不得出现在侧边栏导航。
- 默认行为保持兼容: 新库、旧库、未配置菜单显隐时，`notes` 默认对 `user/admin` 都开启。

### Task 1: 后端先补红灯测试，锁定 `notes` 开关语义

**Files:**
- Test: `backend/tests/test_checkin_and_admin.py`
- Test: `backend/tests/test_notes.py`

- [ ] **Step 1: 为默认菜单可见性补测试**

在 `test_register_returns_visible_menu_keys_consistent_with_get_me`、`test_get_me_returns_visible_menu_keys_by_role` 附近补断言，要求默认 `visible_menu_keys` 包含 `notes`。

- [ ] **Step 2: 为禁用后的接口拒绝补测试**

在 `backend/tests/test_notes.py` 新增至少两个用例:
- 普通用户在 `notes` 被管理员关闭后访问 `get_note_accounts` 返回 `HTTPException(403)`
- 管理员在 `notes` 被管理员关闭后访问 `get_realtime_notes` 返回 `HTTPException(403)`

测试必须同时断言:
- 错误文案明确指出“实时便笺功能已被管理员禁用”
- 不会进入 `NoteService.get_summary` 等真正上游链路

- [ ] **Step 3: 运行后端目标测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
..\.venv313\Scripts\python.exe -m unittest tests.test_notes tests.test_checkin_and_admin
```

Expected:
- 新增用例失败
- 失败原因集中在 `notes` 尚未进入默认菜单定义、接口尚未做 403 门禁

### Task 2: 后端实现 `notes` 独立开关与接口门禁

**Files:**
- Modify: `backend/app/services/menu_visibility.py`
- Modify: `backend/app/services/system_settings.py`
- Modify: `backend/app/schemas/system_setting.py`
- Modify: `backend/app/api/notes.py`

- [ ] **Step 1: 扩展菜单定义模型**

在 `backend/app/services/menu_visibility.py` 中为 `AppMenuDefinition` 增加“是否导航项”的显式字段，例如 `navigable: bool = True`。新增:

```python
AppMenuDefinition(
    "notes",
    "实时便笺（仪表盘模块）",
    "/ (仪表盘内模块)",
    True,
    True,
    navigable=False,
)
```

这里必须保留中文说明，原因是它不是独立页面，后续如果有人误把它当普通路由菜单，会导致侧边栏和权限语义再次混淆。

- [ ] **Step 2: 让菜单管理响应带出非导航属性**

扩展 `AdminMenuVisibilityItem` 与 `SystemSettingsService.get_menu_visibility()`，把 `navigable` 一并返回给前端。这样管理页可以明确把 `notes` 渲染成“功能开关”而不是普通菜单。

- [ ] **Step 3: 为 `/api/notes/*` 增加统一门禁**

在 `backend/app/api/notes.py` 增加内部 helper，逻辑固定为:
1. `settings = await SystemSettingsService(db).get_or_create()`
2. `visible_keys = resolve_visible_menu_keys(role=current_user.role, raw_value=settings.menu_visibility_json)`
3. `if "notes" not in visible_keys: raise HTTPException(status_code=403, detail="实时便笺功能已被管理员禁用")`

然后在 `/accounts` 与 `/summary` 两个入口都先执行该校验，再创建 `NoteService`。

- [ ] **Step 4: 运行后端目标测试确认绿灯**

Run:
```powershell
cd miyoushe-tool/backend
..\.venv313\Scripts\python.exe -m unittest tests.test_notes tests.test_checkin_and_admin
```

Expected:
- 新增用例通过
- 既有菜单管理与便笺用例不回归

### Task 3: 前端先补回归测试，锁定“禁用后不再请求”

**Files:**
- Test: `frontend/tests/accountRoutePrefill.test.ts`

- [ ] **Step 1: 扩展现有轻量测试，不改测试入口**

当前 `npm test` 只跑 `frontend/tests/accountRoutePrefill.test.ts`，不要为了这次改动引入整套 Vitest。直接在该文件增加源码级回归断言，覆盖:
- `appMenus.ts` 包含 `notes`
- `Layout.vue` 的侧边栏不会把 `notes` 当导航项渲染
- `Dashboard.vue` 存在基于 `visible_menu_keys` 的 `hasNotesAccess`
- `Dashboard.vue` 在 `loadData()` 中只有 `hasNotesAccess` 为真时才调用 `loadNotesPanel()`
- `AdminMenuManagement.vue` 文案明确为“菜单与功能开关”

- [ ] **Step 2: 运行前端测试确认红灯**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
```

Expected:
- 新断言失败
- 失败点集中在 `notes` 尚未被纳入菜单定义与仪表盘加载条件

### Task 4: 前端实现非导航型 `notes` 功能开关

**Files:**
- Modify: `frontend/src/constants/appMenus.ts`
- Modify: `frontend/src/utils/menuVisibility.ts`
- Modify: `frontend/src/views/Dashboard.vue`
- Modify: `frontend/src/views/Layout.vue`
- Modify: `frontend/src/views/AdminMenuManagement.vue`

- [ ] **Step 1: 扩展前端菜单定义**

在 `frontend/src/constants/appMenus.ts` 给 `AppMenuDefinition` 增加 `navigable: boolean`，新增 `notes`:

```ts
{ key: 'notes', label: '实时便笺（仪表盘模块）', path: '/ (仪表盘内模块)', navigable: false }
```

`AppMenuKey` 也必须同步补上 `notes`。

- [ ] **Step 2: 菜单过滤逻辑区分“可见”与“可导航”**

在 `frontend/src/utils/menuVisibility.ts` 中:
- `getVisibleMenus()` 只返回 `visibleMenuKeys` 中且 `navigable !== false` 的项
- `hasMenuAccess()` 仍按 key 判断，不依赖是否导航

这样 `notes` 可以存在于权限集合里，但不会进入侧边栏。

- [ ] **Step 3: 仪表盘按开关条件渲染并停止请求**

在 `frontend/src/views/Dashboard.vue`:
- 引入 `useUserStore`
- 新增 `const hasNotesAccess = computed(() => hasMenuAccess('notes', userStore.visibleMenuKeys))`
- 整个 `notes-panel` 使用 `v-if="hasNotesAccess"`
- `loadData()` 改为:

```ts
await Promise.all([
  loadDashboardSummary(),
  hasNotesAccess.value ? loadNotesPanel() : Promise.resolve(resetNotesState()),
])
```

- 新增 `resetNotesState()`，同时清空:
  - `noteAccounts`
  - `selectedNoteAccountId`
  - `routeAccountPrefillConsumed`
  - `noteSummary`

这里必须写清中文注释: 为什么关闭功能时要主动清空状态。否则后续若用户从“开启 -> 关闭”热切换，页面可能残留旧便笺数据，造成“看起来没请求但仍显示旧数据”的误判。

- [ ] **Step 4: 管理页文案和标识改成“菜单与功能开关”**

在 `frontend/src/views/AdminMenuManagement.vue`:
- 标题改为“菜单与功能开关”
- 说明文案改为“导航菜单与仪表盘内功能模块统一在这里控制”
- 对 `navigable === false` 的行显示“功能开关”标签，避免误解为独立页面

- [ ] **Step 5: 布局标题逻辑保持兼容**

`Layout.vue` 的 `pageTitle` 仍应只按真实路由匹配；`notes` 没有真实导航入口，不能破坏标题解析。

- [ ] **Step 6: 运行前端验证**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
npm run build
```

Expected:
- 轻量回归测试通过
- TypeScript 与打包通过

### Task 5: 联调验证“禁用即不再打上游”

**Files:**
- 无新增文件，复用现有管理页与仪表盘

- [ ] **Step 1: 管理员关闭 `notes`**

在后台“菜单与功能开关”页关闭 `notes` 的 `user/admin` 可见性，保存后重新拉取 `/api/auth/me`，确认 `visible_menu_keys` 不再包含 `notes`。

- [ ] **Step 2: 验证前端不请求**

打开仪表盘，确认:
- 页面不再渲染实时便笺区块
- 浏览器网络面板不再出现 `/api/notes/accounts` 与 `/api/notes/summary`

- [ ] **Step 3: 验证后端硬拒绝**

用已登录态直接请求:

```powershell
curl http://127.0.0.1:8000/api/notes/accounts
curl "http://127.0.0.1:8000/api/notes/summary?account_id=1"
```

Expected:
- 两者都返回 `403`
- 响应 detail 为“实时便笺功能已被管理员禁用”

- [ ] **Step 4: 再次开启并做回归**

重新开启 `notes`，确认:
- 仪表盘便笺恢复展示
- `/api/notes/*` 恢复可用
- 既有签到、抽卡、资产、菜单管理功能无异常

## 风险与防回归点

- `notes` 是功能开关，不是独立路由；如果只新增 key 而不区分 `navigable`，它会错误出现在侧边栏。
- 只做前端隐藏不够，必须后端 403；否则第三方脚本或旧前端仍会继续访问上游。
- 只做后端 403 不够，前端也要停止请求；否则仪表盘每次打开仍会先打本地接口，形成无意义错误噪音。
- 默认菜单配置必须包含 `notes`；否则升级后所有用户会被意外关闭新功能。
- 管理页文案必须明确“仪表盘模块”；否则运维可能误以为它控制的是独立页面入口。

## 建议提交拆分

1. `test(notes): cover menu-gated realtime notes access`
2. `feat(menu): add non-navigable notes feature toggle`
3. `docs(admin): clarify menu and feature toggle semantics`
