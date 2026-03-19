# 实时便笺 `genshin.py` 迁移审查修复 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `notes` 迁移到 `genshin.py` 后的 5 个高优先级审查问题，先收敛 `verification_required` 误判与前端类型文件漏提风险，再补齐 provider 契约、异常边界与回归测试覆盖，同时保持现有前后端协议不变。

**Architecture:** 继续保留后端以 `genshin.py` 统一拉取三游实时便笺、再映射到前端固定 `schema_version=2` 协议的设计。这一轮修复只收紧五条边界：验证状态判定必须可审计、前端类型文件必须纳入提交物、角色服上下文必须显式透传、接入层测试必须覆盖真实 provider 用法、本地映射异常不得伪装成上游故障，避免再次把问题藏进宽泛 mock、模糊启发式或漏提文件里。

**Tech Stack:** FastAPI、SQLAlchemy Async、`genshin.py` 1.7.23、Python `unittest`、Vue 3、TypeScript、Node.js、Git

---

## 文件边界

**后端生产代码**
- Modify: `backend/app/services/notes.py`

**后端测试**
- Modify: `backend/tests/test_notes.py`
- Verify: `backend/tests/test_checkin_and_admin.py`

**前端生产代码**
- Verify / include in commit: `frontend/src/types/notes.ts`
- Verify only: `frontend/src/api/index.ts`
- Verify only: `frontend/src/utils/noteStatus.ts`
- Verify only: `frontend/src/views/Dashboard.vue`

**计划与提交物核对**
- Modify: `docs/superpowers/plans/2026-03-19-notes-review-fixes.md`
- Verify: Git working tree / tracked files

## 审查问题映射

1. **Critical：`verification_required` 判定过宽**
- `_is_verification_exception()` 当前只要异常信息包含 `app` 或 `验证` 就可能映射成 `verification_required`。
- 这会把真实上游故障误判成“请去 App 验证”，污染状态语义并误导用户动作。

2. **Critical：`frontend/src/types/notes.ts` 已被引用但仍未纳入提交物**
- `frontend/src/api/index.ts` 已 import `../types/notes`，但 `git status` 显示 `frontend/src/types/` 仍未跟踪。
- 如果漏提，CI 或他人环境会直接 TypeScript 编译失败。

3. **Important：provider 请求未显式携带角色服信息**
- 当前 `_fetch_role_note_payload()` 只把 `uid` 传给 `genshin.py`，没有把 `role.region` 显式纳入调用边界或契约测试。

4. **Important：测试过度 mock 内部 helper，未覆盖真实接入层**
- 当前多处直接 patch `NoteService._build_genshin_client` / `_fetch_role_note_payload`，导致测不到 `genshin.Client(...)` 构造参数、cookies 形态、语言参数和 `autoauth=True`。

5. **Important：本地映射异常被统一吞成 `upstream_error`**
- 当前 `_fetch_role_note_card()` 把 provider 调用和 `detail/metrics` 映射放在同一个大 `try` 里，末尾裸 `except Exception` 会把本地 bug 误报成“上游暂不可用”。

## 执行约束

- 不改前端实时便笺协议：继续保持 `schema_version`、`provider`、`detail_kind`、`detail`、`metrics` 字段语义不变。
- 不改三游识别范围：仅覆盖 `genshin`、`starrail`、`zzz`，其中绝区零继续使用 `nap_` 前缀。
- 后端新增或调整的中文注释必须解释“为什么验证判定必须收窄”“为什么必须显式 server/region”“为什么异常边界必须拆开”“误改后会造成什么伪成功/伪失败风险”，不能只写表面动作。
- 这轮必须把“代码正确性”和“提交物完整性”都纳入验收；只修逻辑、不检查 tracked 文件视为未完成。
- 本项目后续不创建 worktree；本计划按当前仓库直接执行。

### Task 1: 收窄 `verification_required` 判定规则

**Files:**
- Modify: `backend/tests/test_notes.py`
- Modify: `backend/app/services/notes.py`

- [ ] **Step 1: 先补失败测试，锁定误判边界**

在 `backend/tests/test_notes.py` 新增最少两类测试，直接覆盖 `_is_verification_exception()` 或经 `get_realtime_notes()` 走到状态卡片输出：
- `retcode` 命中当前游戏白名单时，仍应判定为 `verification_required`
- message 仅包含普通英文单词 `app`，但 retcode 不在白名单时，必须保持 `upstream_error`

示例断言方向：

```python
self.assertFalse(
    service._is_verification_exception(
        genshin_config,
        genshin.GenshinException({"retcode": 12345, "message": "upstream app service busy"}),
    )
)
```

以及：

```python
self.assertEqual(response.cards[0].status, "upstream_error")
self.assertEqual(response.cards[0].message, "upstream app service busy")
```

- [ ] **Step 2: 运行目标测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_get_realtime_notes_does_not_treat_plain_app_keyword_as_verification -v
```

Expected:
- 新增测试失败
- 失败原因是当前实现把包含 `app` 的普通错误误报成 `verification_required`

- [ ] **Step 3: 做最小实现，删除过宽启发式**

在 `backend/app/services/notes.py` 中收紧 `_is_verification_exception()`：
- 以 `config.verification_retcodes` 为主
- 如确实需要 message 辅助匹配，只允许使用窄白名单短语，并在注释中列出这些短语为什么安全
- 明确删除 `"app" in message.lower()` 这一类不可审计的宽泛匹配

要求补中文维护注释，说明：
- 为什么 `app` 关键字会误伤普通上游错误
- 为什么验证态必须是高确信度判定，不能为了“多兜一点”牺牲语义准确性

- [ ] **Step 4: 重跑相关测试确认绿灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_get_realtime_notes_does_not_treat_plain_app_keyword_as_verification -v
```

Expected:
- 新增误判边界测试通过
- 原有 `5003/10041/-1104` 验证态测试不回归

### Task 2: 确认并纳入 `frontend/src/types/notes.ts`

**Files:**
- Verify / include in commit: `frontend/src/types/notes.ts`
- Verify: `frontend/src/api/index.ts`
- Verify: Git working tree / tracked files

- [ ] **Step 1: 先核对类型文件内容与引用边界**

检查 `frontend/src/types/notes.ts` 是否已经完整定义生产代码依赖的导出，例如：
- `NoteAccount`
- `NoteSummaryResponse`
- 以及其下游需要的 detail / metrics 结构

同时确认 `frontend/src/api/index.ts` 的 import 与该文件实际导出保持一致，避免只是“把文件加进 git”但内容仍不完整。

- [ ] **Step 2: 运行提交物完整性检查，确认当前为红灯**

Run:
```powershell
git -C miyoushe-tool status --short
```

Expected:
- 仍能看到 `?? frontend/src/types/` 或等价未跟踪提示
- 这一步的红灯含义是“提交物不完整”，不是业务逻辑失败

- [ ] **Step 3: 把类型文件纳入本次变更集并再次核对**

要求：
- 确保 `frontend/src/types/notes.ts` 留在当前方案里，而不是再把类型内联回 `index.ts`
- 如目录下有多余临时文件，不能顺手一并纳入；只纳入真实生产源码
- 如果还发现其它被引用但未跟踪的 notes 相关源码文件，也在这里一并补齐

- [ ] **Step 4: 重跑提交物检查确认绿灯**

Run:
```powershell
git -C miyoushe-tool status --short
```

Expected:
- `frontend/src/types/notes.ts` 不再以未跟踪目录形式出现
- 变更集里不存在“生产代码引用了未跟踪源码文件”的风险

### Task 3: 固定角色服上下文契约并补红灯测试

**Files:**
- Modify: `backend/tests/test_notes.py`
- Modify: `backend/app/services/notes.py`

- [ ] **Step 1: 先补失败测试，锁定“不能只靠 UID 推断 server”**

在 `backend/tests/test_notes.py` 新增一个面向 `NoteService._fetch_role_note_payload()` 的精确契约测试，不再 patch `_fetch_role_note_payload` 本身，而是直接构造：
- 一个带特殊区服的 `GameRole`
- 一个 `AsyncMock` 形式的 client，其 `get_*_notes` 可记录调用参数

测试至少断言：

```python
client.get_genshin_notes.assert_awaited_once()
kwargs = client.get_genshin_notes.await_args.kwargs
self.assertEqual(kwargs["uid"], 10001)
self.assertEqual(kwargs["lang"], "zh-cn")
self.assertTrue(kwargs["autoauth"])
self.assertIn("server", kwargs)
self.assertEqual(kwargs["server"], "cn_qd01")
```

如果最终 `genshin.py` 某个方法实际要求的字段名不是 `server`，测试也必须把“显式传递角色服上下文”这个契约固定住，而不是退回“只要请求发出即可”。

- [ ] **Step 2: 运行目标测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_fetch_role_note_payload_passes_explicit_server_context -v
```

Expected:
- 新增测试失败
- 失败原因是当前实现只传 `uid/lang/autoauth`，没有显式传角色服上下文

- [ ] **Step 3: 在生产代码中补最小实现**

在 `backend/app/services/notes.py` 中为 `_fetch_role_note_payload()` 增加显式 server/region 上下文透传，要求：
- 对原神、星铁、绝区零统一走配置分发，不把 server 逻辑散落成多段 `if/else`
- 优先使用 `role.region`
- 若第三方库参数名与数据库字段语义不一致，需要在注释里写明映射关系和误改风险

建议实现形式接近：

```python
payload = await method(
    uid=int(role.game_uid),
    server=role.region,
    lang="zh-cn",
    autoauth=True,
)
```

如果实际需要做更细的 region 到 server 归一化，也必须把转换规则集中在单一 helper 中，并补注释说明为什么不能直接依赖 UID 猜服。

- [ ] **Step 4: 重跑相关测试确认绿灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_fetch_role_note_payload_passes_explicit_server_context -v
```

Expected:
- 新增测试通过
- 调用参数里稳定带有显式角色服上下文

### Task 4: 为 `genshin.py` 接入层补真实契约测试

**Files:**
- Modify: `backend/tests/test_notes.py`

- [ ] **Step 1: 先补一组不再 mock 内部 helper 的接入层测试**

在 `backend/tests/test_notes.py` 新增至少 3 类测试，直接 patch `app.services.notes.genshin.Client`：
- 原神角色会调用 `get_genshin_notes(...)`
- 星铁角色会调用 `get_starrail_notes(...)`
- 绝区零角色会调用 `get_zzz_notes(...)`

每个测试都要断言：

```python
mock_client_cls.assert_called_once_with(
    cookies="ltuid=10001; cookie_token=test-token",
    lang="zh-cn",
)
mock_client.get_genshin_notes.assert_awaited_once_with(
    uid=10001,
    server="cn_gf01",
    lang="zh-cn",
    autoauth=True,
)
```

星铁和绝区零同理，分别固定正确的方法名与 server 值。不要再通过 patch `_build_genshin_client` 或 `_fetch_role_note_payload` 绕开真实接入层。

- [ ] **Step 2: 运行新增测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes -v
```

Expected:
- 新增契约测试先失败
- 失败原因应直接指向 client 构造参数或 `get_*_notes` 调用参数不符合预期

- [ ] **Step 3: 收敛旧测试里的过度 mock**

调整已有测试策略：
- 保留 API 层 summary/card 映射测试对 `_fetch_role_note_payload` 的 mock，用于覆盖 UI 协议映射
- 新增接入层契约测试专门覆盖 `genshin.Client` 构造和 `get_*_notes(... autoauth=True)` 行为
- 避免同一行为同时被“宽泛 mock 测试”和“真实接入层测试”重复覆盖但断言标准不一致

必要时可把当前测试拆成两个层次：
- “协议映射测试”：允许 mock payload
- “provider 契约测试”：禁止 mock `_fetch_role_note_payload`

- [ ] **Step 4: 重跑 `tests.test_notes` 确认通过**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes -v
```

Expected:
- `tests.test_notes` 通过
- 三游 provider 契约、cookies、语言参数、`autoauth=True` 均有显式断言

### Task 5: 拆开 provider 异常与本地映射异常边界

**Files:**
- Modify: `backend/tests/test_notes.py`
- Modify: `backend/app/services/notes.py`

- [ ] **Step 1: 先补失败测试，证明本地映射 bug 不能伪装成 `upstream_error`**

在 `backend/tests/test_notes.py` 为 `_fetch_role_note_card()` 新增测试：
- patch `_fetch_role_note_payload` 返回一个合法 payload
- patch `_build_detail_and_metrics` 抛出 `ValueError("detail-mapping-bug")` 或等价本地异常

测试目标：
- 该异常必须向上抛出，或被转换成明确的内部错误信号
- 总之不能再返回 `status="upstream_error"` 且 message 为“实时便笺暂时不可用，请稍后重试”

例如：

```python
with self.assertRaises(ValueError):
    await service._fetch_role_note_card(client, role)
```

如果团队决定改成包装成 `RuntimeError` 之类的内部异常，也可以，但必须与 provider 异常卡片语义严格区分。

- [ ] **Step 2: 运行目标测试确认红灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_fetch_role_note_card_does_not_mask_local_mapping_errors -v
```

Expected:
- 新增测试失败
- 失败原因是当前实现把本地异常吞掉并返回了 `upstream_error`

- [ ] **Step 3: 在生产代码里拆分 `try/catch` 范围**

调整 `backend/app/services/notes.py` 中 `_fetch_role_note_card()`：
- 第一段 `try` 只包 provider 调用：`_fetch_role_note_payload`
- provider 相关异常继续映射为 `invalid_cookie`、`verification_required`、`upstream_error`
- `detail, metrics = self._build_detail_and_metrics(config.game, payload)` 与 `NoteCardResponse(...)` 组装放到 provider `try` 之外
- 不再保留会吞掉本地 bug 的裸 `except Exception`

建议结构接近：

```python
try:
    _, payload = await self._fetch_role_note_payload(client, role)
except genshin.InvalidCookies:
    ...
except genshin.CookieException:
    ...
except genshin.GenshinException as exc:
    ...

detail, metrics = self._build_detail_and_metrics(config.game, payload)
return NoteCardResponse(...)
```

这里必须加中文注释说明：
- provider 故障应转换为用户可见状态卡片
- 本地映射异常属于实现 bug，必须暴露给测试和日志，不能再伪装成上游不可用

- [ ] **Step 4: 重跑目标测试确认绿灯**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes.NoteTests.test_fetch_role_note_card_does_not_mask_local_mapping_errors -v
```

Expected:
- 新增测试通过
- 本地映射异常不再被误报为 `upstream_error`

### Task 6: 全量回归与影响面核对

**Files:**
- Verify: `backend/tests/test_notes.py`
- Verify: `backend/tests/test_checkin_and_admin.py`
- Verify: `backend/app/services/notes.py`
- Verify: `frontend/src/api/index.ts`
- Verify: `frontend/src/types/notes.ts`
- Verify: `frontend/src/utils/noteStatus.ts`
- Verify: `frontend/src/views/Dashboard.vue`
- Verify: Git working tree / tracked files

- [ ] **Step 1: 跑后端测试回归**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m unittest tests.test_notes tests.test_checkin_and_admin -v
```

Expected:
- 所有后端相关测试通过
- 新增误判边界测试、provider 契约测试与异常边界测试全部通过

- [ ] **Step 2: 跑后端语法编译检查**

Run:
```powershell
cd miyoushe-tool/backend
.\.venv313\Scripts\python.exe -m compileall app
```

Expected:
- `app` 编译通过
- 没有新的语法或导入错误

- [ ] **Step 3: 跑前端回归**

Run:
```powershell
cd miyoushe-tool/frontend
npm test
npm run build
```

Expected:
- 现有前端测试通过
- 构建通过，说明后端返回协议未破坏现有前端类型和状态映射

- [ ] **Step 4: 再次核对提交物完整性**

Run:
```powershell
git -C miyoushe-tool status --short
```

Expected:
- `frontend/src/types/notes.ts` 已纳入变更集，不再以未跟踪目录形式存在
- 没有其它被生产代码引用但仍未跟踪的 notes 相关源码文件

- [ ] **Step 5: 人工核对协议未扩散**

确认以下结论：
- 前端仍只依赖 `schema_version=2` 和既有 `detail_kind/detail/metrics` 协议，不需要跟着 server 透传改动而改接口
- `provider` 仍为 `genshin.py`
- 这轮修复没有把 `notes.py` 再次引回手写请求头或自定义上游协议
- `verification_required` 只在高确信度条件下出现，不再把普通 `app` 字样错误误判为验证态

## 风险与注意事项

- 如果 `genshin.py` 某些 `get_*_notes` 方法实际不接受 `server`，不要为了“让测试过”硬塞无效参数；应该先核对官方签名，再把“显式角色服上下文”落在库认可的位置，并同步调整契约测试。
- 不要把 Task 4 做成纯 mock 自证；目标是锁定接入层边界，而不是继续让内部 helper 遮蔽问题。
- Task 5 的目标是暴露真实 bug，不是把所有异常都直接抛给用户；只有本地实现错误要脱离 `upstream_error` 语义，provider 异常仍应保持用户可读卡片状态。
- `frontend/src/types/notes.ts` 的验收标准不是“本地存在”，而是“已被纳入变更集且导出与引用一致”。
- 本计划按当前会话约束未派发计划审查子代理；如需执行，可在后续选择 `subagent-driven-development` 或 `executing-plans` 路线。
