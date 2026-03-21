# 网页登录链路的历史边界

## 目的

这份文档只回答一个问题：为什么“网页登录二维码”不再被当成当前系统的正式登录底座。

当前正式能力已经切换到官方 `Passport/HoyoPlay` 高权限登录，见：

- [passport-high-privilege-login.md](C:/Dev/miyoushe-tool/docs/maintenance/passport-high-privilege-login.md)

因此这里记录的是历史诊断结论和误用风险，而不是现行产品协议。

## 直接证据

2026-03-20 的 fresh 网页扫码诊断已经确认，当前网页登录链路原始 Cookie 中可稳定看到：

- `cookie_token / cookie_token_v2`
- `ltoken / ltoken_v2`
- `ltuid / ltuid_v2`
- `account_id / account_id_v2`
- `account_mid_v2 / ltmid_v2`

同一次 fresh 扫码中，没有看到：

- `stoken / stoken_v2`
- `login_ticket`
- `game_token`

## 维护结论

- 网页登录二维码链路只能作为“网页登录态”和“可直接消费的工作 Cookie”来源。
- 它不能稳定提供 Passport 根凭据，因此不应再被当成自动续期、票据换取、实时便笺或自动抽卡票据链的基础。
- 继续把网页登录 Cookie 包装成“高权限登录”的最常见后果不是立刻报错，而是账号在部分接口上看似可用、真正需要高权限票据时才暴露隐蔽故障。

## 对当前系统意味着什么

- 当前账号正式登录链路只认官方 `Passport/HoyoPlay`。
- 旧网页登录 Cookie-only 账号会被统一标记为 `upgrade_required`。
- “校验登录态”对这类旧账号不会再承诺自动补齐高权限能力，而是明确要求重新登录升级。
- 后续若有人尝试恢复网页链路，必须先回答“如何稳定获得 `stoken/login_ticket`”这个问题；在没有新证据前，不允许把它重新接回正式产品能力。

## 与 ENCRYPTION_KEY 的关系

- `ENCRYPTION_KEY` 必须通过 `.env` 或环境变量显式固定。
- 如果仍使用运行期随机默认值，服务每次重启都会生成不同密钥，历史高权限根凭据、历史工作 Cookie 与其他敏感密文都会无法解密。
- 这会导致账号需要重新登录，但它不是“网页登录拿不到高权限根凭据”的原因，两者必须分开排查。
