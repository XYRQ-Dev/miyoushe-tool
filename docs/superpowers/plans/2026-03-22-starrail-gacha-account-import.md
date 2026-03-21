# 崩铁账号自动导入抽卡链接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让星穹铁道国服官服账号像当前原神一样，支持从账号根凭据自动换取临时抽卡链接并导入记录，同时前端只在当前角色真正支持该能力时展示“从账号自动导入”入口。

**Architecture:** 继续沿用现有“账号态换票据服务 + `GachaService` 统一分页导入”的结构，不复制第二套抓取/落库逻辑。新增独立的 `StarrailAuthkeyService` 负责崩铁上游契约，`GachaService` 只做角色选择、能力判定和按游戏分发；前端通过后端下发的 `supports_account_import` 显式能力位决定按钮显隐，不把区服细节散落到页面判断里。

**Tech Stack:** FastAPI、SQLAlchemy Async、Pydantic、httpx、Vue 3、TypeScript、Element Plus、后端 `unittest`、前端源码级 `node --experimental-strip-types` 回归测试

---

## 文件边界

**后端核心文件**
- Create: `backend/app/services/starrail_authkey.py`
- Modify: `backend/app/services/gacha.py`
- Modify: `backend/app/schemas/gacha.py`
- Modify: `backend/app/utils/device.py`
- Modify: `backend/app/utils/ds.py`
- Test: `backend/tests/test_gacha.py`

**前端核心文件**
- Modify: `frontend/src/views/GachaRecords.vue`
- Test: `frontend/tests/accountRoutePrefill.test.ts`

**文档文件**
- Modify: `docs/maintenance/passport-high-privilege-login.md`
- Modify: `docs/maintenance/web-login-credential-boundary.md`

**默认约束**
- 自动导入范围只开放到 `hkrpg_cn`；`hkrpg_bilibili`、国际服与其他游戏继续只支持“手贴链接 / UIGF 导入导出”。
- 前端消费 `supports_account_import: boolean`，不直接依赖 `game_biz` 做展示判断。
- 不把原神、崩铁重构成通用 provider 框架；本轮保持两个独立票据服务，由 `GachaService` 按游戏分发。
- `authkey` 与完整抽卡 URL 只允许驻留内存，不得写入数据库、日志或导入历史明文。

### Task 1: 先补后端红灯测试，锁定崩铁自动导入契约与能力位

**Files:**
- Test: `backend/tests/test_gacha.py`

- [ ] **Step 1: 为账号列表能力位补测试**

在 `test_list_supported_accounts_returns_gacha_roles` 附近扩展断言，要求 `GachaRoleOption` 新增 `supports_account_import`，并覆盖至少以下角色：

```python
[
    {"game_biz": "hk4e_cn", "game_uid": "10001", "region": "cn_gf01"},
    {"game_biz": "hk4e_os", "game_uid": "10002", "region": "os_usa"},
    {"game_biz": "hkrpg_cn", "game_uid": "80001", "region": "prod_gf_cn"},
    {"game_biz": "hkrpg_bilibili", "game_uid": "80002", "region": "prod_gf_b"},
]
```

目标断言：
- `genshin/hk4e_cn` 为 `True`
- `genshin/hk4e_os` 为 `False`
- `starrail/hkrpg_cn` 为 `True`
- `starrail/hkrpg_bilibili` 为 `False`

- [ ] **Step 2: 为崩铁账号自动导入成功路径补测试**

在 `backend/tests/test_gacha.py` 新增一个与原神成功用例并列的崩铁用例，固定验证：
- `import_gacha_records_from_account(... game="starrail", game_uid="80001")` 能成功导入
- 崩铁 authkey 服务发起的是单独的上游请求，不复用原神常量名
- 上游 payload 至少包含：

```python
{
    "auth_appid": "webview_gacha",
    "game_biz": "hkrpg_cn",
    "game_uid": 80001,
    "region": "prod_gf_cn",
}
```

- 生成后的分页导入请求会带上返回的 `authkey`

- [ ] **Step 3: 为崩铁不支持角色补测试**

新增一个 `hkrpg_bilibili` 角色的账号自动导入用例，断言：
- 本地直接返回 `HTTPException(400)`
- 文案为 `当前仅支持星穹铁道国服官服账号自动导入`
- 不会真的发出崩铁 authkey 上游请求

- [ ] **Step 4: 为崩铁根凭据失效映射补测试**

新增一个崩铁 authkey 上游返回“登录状态失效，请重新登录”的用例，断言错误会被翻译成：

```python
"星穹铁道 authkey 生成失败：米游社登录状态已失效，请重新扫码登录"
```

- [ ] **Step 5: 运行后端目标测试确认红灯**

Run:
```powershell
cd C:\Dev\miyoushe-tool\backend
.\.venv313\Scripts\python.exe -m unittest tests.test_gacha -v
```

Expected:
- 新增崩铁用例失败
- 失败原因集中在 `GachaRoleOption` 尚无 `supports_account_import`、`import-from-account` 仍只支持原神、崩铁 authkey 服务尚不存在

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_gacha.py
git commit -m "test(gacha): lock starrail account import contract"
```

### Task 2: 扩展抽卡账户响应与后端能力判定

**Files:**
- Modify: `backend/app/schemas/gacha.py`
- Modify: `backend/app/services/gacha.py`
- Test: `backend/tests/test_gacha.py`

- [ ] **Step 1: 在抽卡角色响应中加入显式能力位**

在 `backend/app/schemas/gacha.py` 的 `GachaRoleOption` 中新增：

```python
supports_account_import: bool = Field(
    description="当前角色是否支持从账号根凭据直接自动导入抽卡记录"
)
```

这里必须保留中文维护注释，说明前端消费的是“能力结果”而不是区服规则本身，避免后续又把 `game_biz` 暴露给页面做重复判断。

- [ ] **Step 2: 在游戏配置中补充自动导入支持范围**

在 `backend/app/services/gacha.py` 的 `SUPPORTED_GACHA_GAME_CONFIGS` 中为每个游戏新增专用字段，例如：

```python
"account_import_role_game_bizs": {"hk4e_cn"}
"account_import_role_game_bizs": {"hkrpg_cn"}
```

不要把它复用成 `supported_role_prefixes`。前者是“允许展示自动导入能力的精确区服集合”，后者仍然表示“允许做手贴链接/UIGF 读写的角色前缀范围”。

- [ ] **Step 3: 让账号列表返回 `supports_account_import`**

在 `list_supported_accounts()` 中生成 `GachaRoleOption` 时，按当前 `role.game_biz` 是否落在 `account_import_role_game_bizs` 里计算布尔值：

```python
supports_account_import = role.game_biz in config["account_import_role_game_bizs"]
```

- [ ] **Step 4: 抽一个本地能力判断 helper**

在 `GachaService` 中新增私有 helper，例如：

```python
def _supports_account_import_role(self, game: str, role: GameRole) -> bool:
    config = self._ensure_supported_game(game)
    return role.game_biz in config["account_import_role_game_bizs"]
```

后续 `list_supported_accounts()`、`_generate_genshin_authkey()`、`_generate_starrail_authkey()` 共用它，避免两处维护时区服规则漂移。

- [ ] **Step 5: 运行后端目标测试确认只剩崩铁票据链红灯**

Run:
```powershell
cd C:\Dev\miyoushe-tool\backend
.\.venv313\Scripts\python.exe -m unittest tests.test_gacha -v
```

Expected:
- `supports_account_import` 相关断言转绿
- 仍失败在崩铁 authkey 服务与 `import-from-account` 分发未实现

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/gacha.py backend/app/services/gacha.py backend/tests/test_gacha.py
git commit -m "feat(gacha): expose account-import capability by role"
```

### Task 3: 新增崩铁 authkey 服务并接入账号自动导入分发

**Files:**
- Create: `backend/app/services/starrail_authkey.py`
- Modify: `backend/app/services/gacha.py`
- Modify: `backend/app/utils/device.py`
- Modify: `backend/app/utils/ds.py`
- Test: `backend/tests/test_gacha.py`

- [ ] **Step 1: 在 `ds.py` 中为崩铁 authkey 增加独立 helper**

新增崩铁专用常量与 helper，命名固定为：

```python
STARRAIL_AUTHKEY_SALT = "..."

def generate_starrail_authkey_ds() -> str:
    return generate_cn_gen1_ds(salt=STARRAIL_AUTHKEY_SALT, include_chars=True)
```

不要复用 `generate_cn_gen1_ds_lk2()` 的名字和盐值。哪怕最终随机规则相同，也必须让“原神专用盐值”和“崩铁专用盐值”在代码结构上可见。

- [ ] **Step 2: 在 `device.py` 中新增崩铁 authkey 请求头 helper**

新增独立 helper，例如：

```python
def build_starrail_authkey_headers(
    cookie: str,
    *,
    device_id: str,
    ds: str,
    device_fp: str | None = None,
    app_version: str = STARRAIL_AUTHKEY_APP_VERSION,
) -> dict[str, str]:
    ...
```

实现要求：
- 不复用 `build_genshin_authkey_headers()` 名字
- 继续显式带 `Cookie`、`DS`、`x-rpc-device_id`
- `Referer`、`User-Agent`、`x-rpc-app_version` 采用经参考客户端验证后的崩铁值
- 若参考客户端要求 `device_fp`，就强制带上；若不要求，也保留可选参数，便于和系统设置复用

- [ ] **Step 3: 创建 `StarrailAuthkeyService`**

在 `backend/app/services/starrail_authkey.py` 中对齐原神服务结构，至少包含：

```python
STARRAIL_AUTHKEY_API_URL = "..."
STARRAIL_GACHA_LOG_API_URL = "..."
STARRAIL_REGION_BY_GAME_BIZ = {"hkrpg_cn": "prod_gf_cn"}

class StarrailAuthkeyService:
    async def generate_import_url(self, account: MihoyoAccount, role: GameRole) -> str: ...
    def _normalize_supported_role(self, role: GameRole) -> tuple[str, str]: ...
    def _build_payload(self, role: GameRole) -> dict[str, Any]: ...
    async def _request_authkey(self, account: MihoyoAccount, payload: dict[str, Any]) -> dict[str, Any]: ...
```

行为固定为：
- 先调用 `AccountCredentialService(self.db).get_root_credential_snapshot(account)`，不允许回退到工作 Cookie-only
- 仅允许 `hkrpg_cn`
- region 缺失时只允许 `hkrpg_cn -> prod_gf_cn` 的最小 fallback
- 成功后拼出完整导入 URL，至少包含 `authkey`、`authkey_ver`、`sign_type`、`lang=zh-cn`、默认崩铁卡池类型
- 失败时统一转成 `星穹铁道 authkey 生成失败：...`
- 日志只记脱敏后的请求轮廓，不落 Cookie、DS、authkey 明文

- [ ] **Step 4: 在 `GachaService` 接入崩铁分发**

在 `backend/app/services/gacha.py` 中：
- 引入 `StarrailAuthkeyService`
- 将 `import_records_from_account()` 改为：

```python
if game == "genshin":
    import_url = await self._generate_genshin_authkey(account, game_uid)
elif game == "starrail":
    import_url = await self._generate_starrail_authkey(account, game_uid)
else:
    raise HTTPException(status_code=400, detail="暂不支持该游戏的账号自动导入")
```

- 新增 `_generate_starrail_authkey()`，查询当前账号下目标 `game_uid` 的 `hkrpg_` 角色，再通过 `_supports_account_import_role()` 严格校验只能走 `hkrpg_cn`
- 原神现有 `_generate_genshin_authkey()` 也改成复用 `_supports_account_import_role()`，不要继续保留一套单独写死逻辑

- [ ] **Step 5: 运行后端测试确认绿灯**

Run:
```powershell
cd C:\Dev\miyoushe-tool\backend
.\.venv313\Scripts\python.exe -m unittest tests.test_gacha -v
.\.venv313\Scripts\python.exe -m compileall app
```

Expected:
- `tests.test_gacha` 全绿
- `compileall` 通过

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/starrail_authkey.py backend/app/services/gacha.py backend/app/utils/device.py backend/app/utils/ds.py backend/tests/test_gacha.py
git commit -m "feat(gacha): add starrail account authkey import"
```

### Task 4: 先补前端源码回归，再把自动导入入口扩展到崩铁

**Files:**
- Modify: `frontend/tests/accountRoutePrefill.test.ts`
- Modify: `frontend/src/views/GachaRecords.vue`

- [ ] **Step 1: 在现有前端源码级测试里补红灯断言**

继续复用当前唯一测试入口 `frontend/tests/accountRoutePrefill.test.ts`，新增断言覆盖：
- `GachaRecords.vue` 的角色类型包含 `supports_account_import`
- `showImportFromAccount` 不再写死 `selectedGame === 'genshin'`
- 页面文案从“原神支持三种入口”改成“当前角色支持时可自动导入”
- 仍保留崩铁 `手贴链接 / UIGF` 入口

可参考断言模式：

```ts
assertSourceMatches(
  gachaRecordsView,
  /supports_account_import/,
  'GachaRecords.vue 需要消费后端返回的 supports_account_import 能力位',
)
assertSourceOmits(
  gachaRecordsView,
  /selectedGame\.value === 'genshin'/,
  '自动导入按钮显隐不应再写死成 only genshin',
)
```

- [ ] **Step 2: 运行前端测试确认红灯**

Run:
```powershell
cd C:\Dev\miyoushe-tool\frontend
npm test
```

Expected:
- 新增断言失败
- 失败点集中在 `GachaRecords.vue` 仍按 `genshin` 写死入口判断

- [ ] **Step 3: 修改 `GachaRecords.vue` 使用能力位渲染**

在 `frontend/src/views/GachaRecords.vue` 中：
- 扩展本地 `GachaRole` 类型：

```ts
type GachaRole = {
  game: string
  game_uid: string
  nickname?: string | null
  region?: string | null
  supports_account_import: boolean
}
```

- 将按钮显隐逻辑改为：

```ts
const showImportFromAccount = computed(() => Boolean(currentRole.value?.supports_account_import))
```

- 更新 `importSectionDescription`、`gameScopeHint`、`emptyRecordsDescription` 文案，改成能力导向而不是原神硬编码
- 保留中文维护注释，说明“前端只消费能力位，不能自行根据游戏名猜测支持范围”

- [ ] **Step 4: 保持交互边界不变**

确认 `handleImportFromAccount()` 只做一件事：把 `account_id + game + game_uid` 原样交给后端。不要在前端补额外区服猜测、URL 拼接或 authkey 处理。

- [ ] **Step 5: 运行前端验证**

Run:
```powershell
cd C:\Dev\miyoushe-tool\frontend
npm test
npm run build
```

Expected:
- 源码回归测试通过
- `vue-tsc` 与 `vite build` 通过

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/GachaRecords.vue frontend/tests/accountRoutePrefill.test.ts
git commit -m "feat(frontend): surface starrail account gacha import entry"
```

### Task 5: 更新维护文档并完成联调回归

**Files:**
- Modify: `docs/maintenance/passport-high-privilege-login.md`
- Modify: `docs/maintenance/web-login-credential-boundary.md`

- [ ] **Step 1: 更新高权限登录维护文档**

在 `docs/maintenance/passport-high-privilege-login.md` 中把“当前账号直连自动导入 v1 只支持原神”更新为：
- 支持：原神国服官服、星穹铁道国服官服 `SToken -> authkey -> 完整 URL -> 导入`
- 不支持：崩铁 B 服、国际服
- 继续强调 `authkey` / 完整 URL 不落库

- [ ] **Step 2: 更新网页登录边界文档**

在 `docs/maintenance/web-login-credential-boundary.md` 中补充：
- 自动导入的正式高权限来源仍然只能是 Passport 根凭据
- 崩铁接入后也必须显式绑定当前 `game_uid`
- 不允许因为“崩铁已接入”而回退到网页 Cookie-only 心智

- [ ] **Step 3: 做后端接口联调验证**

在本地使用一个具备 `hkrpg_cn` 角色和高权限根凭据的测试账号，执行：

```powershell
cd C:\Dev\miyoushe-tool\backend
.\.venv313\Scripts\python.exe -m unittest tests.test_gacha -v
```

然后用已登录前端页面的 `access_token` 实际请求：

```powershell
$token = "<从浏览器 localStorage 读取的 access_token>"
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:8000/api/gacha/accounts -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/api/gacha/import-from-account -Method Post -Headers $headers -ContentType "application/json" -Body '{"account_id":1,"game":"starrail","game_uid":"80001"}'
```

Expected:
- `/gacha/accounts` 中目标崩铁角色 `supports_account_import` 为 `true`
- `/gacha/import-from-account` 返回成功导入结果，且导入历史中只存脱敏 URL

- [ ] **Step 4: 做前端显隐与回归验证**

手工验证：
- 选择 `hkrpg_cn` 角色时显示“从账号自动导入”
- 切到 `hkrpg_bilibili` 角色时按钮消失
- 切回原神国服角色后原有自动导入入口保持可用
- 选中任一不支持角色时仍可正常手贴链接、导入/导出 UIGF

- [ ] **Step 5: Commit**

```bash
git add docs/maintenance/passport-high-privilege-login.md docs/maintenance/web-login-credential-boundary.md
git commit -m "docs(gacha): document starrail account import boundary"
```

## 风险与防回归点

- 崩铁自动导入的风险核心在“上游换票契约”，不是分页抓取本身；因此票据生成必须独立封装，不得混进 `GachaService`。
- `supported_role_prefixes` 与 `account_import_role_game_bizs` 语义不同，混用会导致 B 服角色被错误展示自动导入按钮。
- 前端必须只消费 `supports_account_import`，不能自行根据 `selectedGame` 或 `region` 猜测能力；否则后续规则变化会出现前后端语义漂移。
- 原神 `_generate_genshin_authkey()` 也要复用统一能力 helper，避免“崩铁走一套、原神走另一套”的隐蔽分叉。
- 崩铁 authkey 服务的日志必须和原神一样只记脱敏轮廓；若把新链路调通时把 authkey/完整 URL 打进日志，风险比功能收益更大。

## 建议提交拆分

1. `test(gacha): lock starrail account import contract`
2. `feat(gacha): expose account-import capability by role`
3. `feat(gacha): add starrail account authkey import`
4. `feat(frontend): surface starrail account gacha import entry`
5. `docs(gacha): document starrail account import boundary`

## 实施前提

- 先根据当前参考客户端或抓包结果确认崩铁国服官服的真实 `genAuthKey` endpoint、`Referer`、`app_version`、DS 盐值与默认抽卡日志 host/参数。
- 如果参考契约与本计划假设不一致，只允许在 `backend/app/services/starrail_authkey.py`、`backend/app/utils/device.py`、`backend/app/utils/ds.py` 内调整常量与 helper，不得破坏本计划既定的服务边界、错误语义和能力位方案。
