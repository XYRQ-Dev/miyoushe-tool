# Passport 高权限登录维护说明

## 目的

这份文档记录当前正式登录底座、凭据分层、抽卡票据链路边界，以及维护时最容易被误改的风险点。

如果你只想看“为什么网页登录二维码不再作为正式能力”，请看：

- [web-login-credential-boundary.md](C:/Dev/miyoushe-tool/docs/maintenance/web-login-credential-boundary.md)

## 当前正式登录底座

当前系统的正式登录底座已经切换到官方 `Passport/HoyoPlay`，不再把网页扫码当成正式高权限来源。

当前前后端对外稳定语义是：

- 二维码登录：正式的账号绑定与升级入口
- 短信验证码登录：只校验 Passport 根凭据，不直接落库绑定账号
- 登录态校验：优先验证工作 Cookie；失效时尝试利用根凭据自动补齐
- 重新登录：只有在根凭据也失效时才要求用户重新扫码

## 两层凭据模型

### 1. 根凭据

根凭据负责续期、自愈和票据换取，当前包括：

- `stoken`
- `ltoken`
- `cookie_token`
- `login_ticket`
- `stuid`
- `mid`

这些字段必须加密存储，不能用“当前能不能签到”来替代判断其有效性。

### 2. 工作 Cookie

工作 Cookie 指 `cookie_encrypted`，它是供签到、兑换码、部分资产接口直接消费的派生 Cookie 串。

维护上必须牢记：

- 工作 Cookie 不是唯一真实凭据
- 工作 Cookie 允许被根凭据自动重建
- 工作 Cookie 失效不等于必须重新登录

如果把 `cookie_status` 误当成根凭据状态，最直接的回归就是系统明明还能自愈，却过早把账号打成 `reauth_required`。

## 状态语义

- `has_high_privilege_auth`：账号是否已经接入 Passport 根凭据
- `credential_status`：根凭据层对外状态
- `cookie_status`：工作 Cookie 当前状态
- `upgrade_required`：账号是否仍停留在旧网页登录 Cookie-only 形态

当前系统要求：

- 旧网页登录账号统一显示 `upgrade_required = true`
- 工作 Cookie 失效时，先尝试 `ensure_work_cookie()`
- 根凭据也无法继续刷新时，才收口到 `credential_status = reauth_required`

## 抽卡相关边界

### UIGF 是唯一正式交换协议

当前抽卡导入导出对外正式标准为 `UIGF v4.2`。

要求如下：

- 默认导出 `v4.2`
- 导入兼容 `v4.0 / v4.1 / v4.2`
- 前端不得再把文件转换成私有 `records` 数组协议
- 历史 `/import-json`、`/export` 只保留兼容别名，不再作为正式命名宣传

### 自动导入范围

当前账号直连自动导入 v1 只支持原神：

- 支持：原神 `SToken -> authkey -> 完整 URL -> 导入`
- 不支持：星穹铁道账号直连自动导入

看到 UIGF 里存在 `hkrpg` 字段，不代表星穹铁道也已支持账号直连导入；那只是交换协议字段，不是票据链已打通的证明。

### 高敏感数据边界

- `login_ticket` 可以加密落库
- `authkey` 与拼出的完整抽卡 URL 只允许驻留内存，不落库

如果把 `authkey` 或完整 URL 写入数据库，后续排障时非常容易把短期票据当成长久凭据误用，风险高且收益极低。

## ENCRYPTION_KEY 要求

- `ENCRYPTION_KEY` 必须通过 `.env` 或环境变量显式固定
- 不允许依赖运行期随机默认值
- 一旦密钥变化，历史根凭据、工作 Cookie 与其他敏感密文都会同时失效

这里最常见的误判是把“重启后无法解密”归因成“官方登录接口失效”。两者不是一个问题，必须先确认密钥是否稳定。

## 维护红线

- 不要把网页登录 Cookie 当成 Passport 根凭据的兜底来源
- 不要让短信验证码登录直接伪造“账号已绑定成功”的 UI 结果
- 不要把 `cookie_status` 当成是否需要重新登录的唯一依据
- 不要把私有 JSON 结构重新包装成抽卡正式交换协议
- 不要把星穹铁道 UIGF 支持误扩展成“星穹铁道账号自动导入已支持”
