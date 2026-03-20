# 网页登录凭据边界与密钥要求

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

## 结论

- 当前网页登录二维码链路只能作为“网页登录态”和“签到所需 Cookie”的来源。
- 不应再把它当成自动续期、App 凭据补齐、实时便笺等能力的凭据基础。
- 系统后续只承诺：
  - 登录态校验
  - 重新扫码更新网页登录态
  - 基于网页登录 Cookie 的签到与角色同步

## 产品边界

- 不再对外暴露“支持自动续期”“自动续期暂不可用”“校验并续期”等语义。
- 登录态失效后的标准处理路径只有一个：重新扫码。
- 数据库中历史保留的 `stoken_encrypted / stuid / mid` 字段仅用于兼容旧数据结构，不再作为正式功能依赖。

## ENCRYPTION_KEY 要求

- `ENCRYPTION_KEY` 必须通过 `.env` 或环境变量显式固定。
- 如果仍使用运行期随机默认值，服务每次重启都会生成不同密钥，历史 Cookie 与历史敏感密文会无法解密。
- 这会导致账号需要重新扫码，但它不是“网页扫码拿不到 stoken”的原因，两者必须分开排查。
