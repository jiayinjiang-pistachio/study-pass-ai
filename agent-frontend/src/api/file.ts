import { request } from './request'

export const FileKind = {
  Image: 'image',
  Document: 'document',
} as const
export type FileKind = (typeof FileKind)[keyof typeof FileKind]

export interface UploadedFile {
  url: string
  md5: string
  size: number
  kind: FileKind
}

/**
 * 通用文件上传：必须已登录。
 * 后端自动识别类型：图片会同时更新当前用户头像，文档只落盘。
 */
export function uploadFile(file: File): Promise<UploadedFile> {
  const body = new FormData()
  body.append('file', file)
  return request<UploadedFile>('/files', { method: 'POST', body })
}
