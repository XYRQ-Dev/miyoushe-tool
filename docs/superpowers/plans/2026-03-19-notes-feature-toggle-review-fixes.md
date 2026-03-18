# 实时便笺独立功能开关审查修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `notes` 独立功能开关实现中的审查问题，消除后端伪路由元数据歧义，并降低前端源码回归测试对格式细节的脆弱依赖。

**Architecture:** 继续复用现有菜单可见性体系，不改变功能开关总设计，只修正“元数据表达”和“测试稳定性”两个层面。后端把 `notes` 明确定义为仪表盘内模块而非真实路由页面，前端测试继续沿用现有源码断言模式，但要补足对照样本和最低语义覆盖线，避免无行为回归时因换行/缩进波动误报失败，也避免把断言削弱成只剩表面字符串检查。

**Tech Stack:** FastAPI、SQLAlchemy Async、Pydantic、Vue 3、Element Plus、Python `unittest`、前端 Node 源码断言测试

---

## 文件边界

**后端文件**
- Modify: `backend/app/services/menu_visibility.py`
- Test: `backend/tests/test_checkin_and_admin.py`

**前端文件**
- Modify: `frontend/src/views/AdminMenuManagement.vue`
- Test: `frontend/tests/accountRoutePrefill.test.ts`

## 审查结论映射

1. **重要问题**
- `notes` 在后端菜单定义里仍暴露为真实路径 `/notes`，与“仪表盘内模块、非独立页面”的设计冲突。

2. **次要问题**
- 管理页目前用 `navigable === false` 直接映射为“仪表盘功能开关”，对未来其它非导航功能项的扩展不安全。
- 前端测试用整段多行字符串精确匹配 `loadData()` 分支，过度依赖换行和缩进，容易假失败。

## 执行约束

- 后端 `notes.path` 如需保留在接口模型中，只允许使用“稳定占位值”来表达“非真实路由页面”。
- 这个占位值的职责仅是消除伪路由歧义，前后端都不得把它当真实导航地址，也不得把它当可随意本地化的 UI 文案。
- 前端这轮继续使用 `frontend/tests/accountRoutePrefill.test.ts` 做源码级语义断言，不引入新测试框架；因此每个红灯条件都必须能通过源码样本和对照样本稳定触发。
- Task 3 虽然目标是“降敏”，但不能降低覆盖力度；至少要继续覆盖：`hasNotesAccess` 分支存在、授权时会调用 `loadNotesPanel()`、未授权时会执行清理逻辑。

### Task 1: 修正 `notes` 的后端元数据语义

**Files:**
- Modify: `backend/app/services/menu_visibility.py`
- Test: `backend/tests/test_checkin_and_admin.py`

- [ ] **Step 1: 先补失败测试**

为菜单管理返回值补断言，要求 `notes` 不再暴露成真实可访问页面路径。测试不要只写“不是 `/notes`”，而要把稳定占位语义固定住，例如：

```python
self.assertEqual(by_key["notes"].path, "[module] dashboard-notes")
```

如果团队决定使用别的稳定占位值，也必须满足两个条件：
- 明确表示“不是路由”
- 不带展示性中文，避免把接口契约和界面文案绑死

- [ ] **Step 2: 运行后端目标测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_checkin_and_admin
```

Expected:
- 新增断言失败
- 失败原因是 `notes` 当前仍返回 `/notes`

- [ ] **Step 3: 做最小实现**

在 `backend/app/services/menu_visibility.py` 中把 `notes` 的 `path` 从伪路由改成稳定占位值，例如 `[module] dashboard-notes`。

这里必须保留中文注释，说明为什么不能再返回伪路由：
- 当前前端虽然不会把它渲染到侧边栏，但其它调用方仍可能把 `path` 当成真实页面入口
- 若继续暴露 `/notes`，等于重新把“功能开关”和“路由菜单”混成一类
- 这里返回的是接口契约级占位值，不是 UI 文案

- [ ] **Step 4: 重跑后端测试确认绿灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_checkin_and_admin tests.test_notes
```

Expected:
- 新增断言通过
- 已有 `notes` 门禁测试不回归

### Task 2: 收紧前端管理页对“功能开关”的识别条件

**Files:**
- Modify: `frontend/src/views/AdminMenuManagement.vue`
- Test: `frontend/tests/accountRoutePrefill.test.ts`

- [ ] **Step 1: 先设计源码级红灯夹具**

由于本项目当前前端测试是源码断言，不做组件挂载，因此这里必须在 `accountRoutePrefill.test.ts` 中构造“对照样本思维”的断言，而不是只检查 `notes` 自身。

至少补两类断言：
- 断言管理页源码中存在对 `row.key === 'notes'` 或等价 helper 的明确识别
- 断言实时便笺专属文案不再单纯绑定到 `row.navigable === false`

这样即使未来再出现另一个 `navigable === false` 项，也不会被默认套用实时便笺文案。

- [ ] **Step 2: 运行前端测试确认红灯**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
```

Expected:
- 新断言失败
- 失败原因是管理页当前对所有非导航项都套用了实时便笺文案

- [ ] **Step 3: 做最小实现**

在 `frontend/src/views/AdminMenuManagement.vue` 中：
- 对 `notes` 单独判断展示“仪表盘功能开关”与“关闭后会同时停止首页便笺渲染与数据请求”
- `navigable === false` 只用于表达“非独立页面/功能开关类型”，不要直接绑定到实时便笺专属文案

如果需要，可引入局部 helper，例如：

```ts
function isNotesModule(row: AdminMenuItem) {
  return row.key === 'notes'
}
```

- [ ] **Step 4: 重跑前端测试**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
```

Expected:
- 新断言通过
- 既有菜单与便笺相关断言不回归

### Task 3: 降低前端源码断言的格式耦合，但保留最低语义覆盖线

**Files:**
- Test: `frontend/tests/accountRoutePrefill.test.ts`

- [ ] **Step 1: 先改测试，不改生产代码**

把当前这类脆弱断言：

```ts
dashboardView.includes('if (hasNotesAccess.value) {\n    await loadNotesPanel()\n  } else {')
```

改成更稳健的语义组合断言。最低要求必须同时保留以下三项：
- 存在 `hasNotesAccess` 分支判断
- 授权路径会调用 `loadNotesPanel()`
- 未授权路径会执行清理逻辑，例如 `resetNotesPanelState()`

必要时用正则表达式替代整段换行字符串匹配，但不要把这三条语义中的任何一条删掉。

- [ ] **Step 2: 运行前端测试**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
```

Expected:
- 测试继续通过
- 不再依赖特定换行/缩进格式
- 仍然能够覆盖“有权限加载、无权限清理”的关键行为语义

### Task 4: 全量回归与影响面核对

**Files:**
- 无新增文件

- [ ] **Step 1: 运行后端目标测试**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes tests.test_checkin_and_admin
```

- [ ] **Step 2: 运行前端测试与构建**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
npm run build
```

- [ ] **Step 3: 核对 `menu_visibility.path` 影响面**

明确检查：
- 除管理页展示外，当前前端没有其它逻辑依赖 `notes.path` 做导航或路由匹配
- 新的稳定占位值不会被侧边栏、标题计算或路由守卫误当成页面路径使用

- [ ] **Step 4: 人工检查管理页语义**

确认：
- `notes` 在管理页显示为仪表盘模块/功能开关
- 不会再对未来所有 `navigable === false` 项默认套用实时便笺文案

## 风险与注意事项

- 这轮修复不应该重新设计权限系统，只修正表达语义与测试稳定性。
- `notes.path` 的调整属于接口契约修正，不是展示层文案优化；若后续确实需要单独的展示说明字段，应另起变更，不要再次复用 `path` 承担 UI 文案职责。
- 不要把“测试降敏”做成“测试失真”；目标是摆脱换行缩进依赖，不是放弃对关键语义的断言。
