/**
 * 开发期 Mock：Mock.js 通过替换全局 XMLHttpRequest 拦截请求。
 * 请求层（src/api/request.ts）固定 axios adapter: 'xhr'，因此 Mock 对 axios 同样生效；
 * 若改用 axios 的 fetch 适配器，这里的拦截会失效。
 *
 * 会话 / 消息 / 面试已接入真实后端，这里只保留笔记模块的 Mock。
 */
import './notes'
