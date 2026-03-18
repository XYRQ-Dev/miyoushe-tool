/**
 * 统一写入 Bearer Token 到请求头。
 * - Axios 1.x 在浏览器端可能把 headers 实例化为 AxiosHeaders，而不是普通对象。
 * - 这类对象应优先使用 set() 写入；如果直接做属性赋值，某些运行时下请求头不会真正发出去，
 *   最终表现为“本地 token 明明存在，但所有受保护接口仍然 401”。
 * - 这里保留对普通对象头的兼容分支，避免后续切换适配器或测试桩时再次出现环境相关差异。
 */
export function applyAuthorizationHeader<
  TConfig extends {
    headers?: Record<string, unknown> | { set?: (name: string, value: string) => void } | undefined
  },
>(config: TConfig, token: string) {
  const authorization = `Bearer ${token}`

  if (config.headers && typeof config.headers === 'object' && 'set' in config.headers) {
    const setHeader = config.headers.set
    if (typeof setHeader === 'function') {
      setHeader.call(config.headers, 'Authorization', authorization)
      return config
    }
  }

  config.headers = {
    ...(config.headers ?? {}),
    Authorization: authorization,
  }

  return config
}
