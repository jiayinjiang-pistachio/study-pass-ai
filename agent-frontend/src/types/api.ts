/** 后端统一分页结构 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
