import { request } from './request'

export const FileKind = {
  Image: 'image',
  Document: 'document',
  Audio: 'audio',
} as const
export type FileKind = (typeof FileKind)[keyof typeof FileKind]

/** 文档业务类型：仅文档上传有意义 */
export const DocCategory = {
  Resume: 'resume',
  StudyMaterial: 'study_material',
  General: 'general',
} as const
export type DocCategory = (typeof DocCategory)[keyof typeof DocCategory]

export interface UploadOptions {
  /** 上传用途：0=普通资源，1=用户头像 */
  uploadPurpose?: 0 | 1
  /** 存储场景：0=长期，1=短期，2=只提取内容 */
  storageScene?: 0 | 1 | 2
  /** 文档业务类型；文档必传，音频/头像忽略 */
  docCategory?: DocCategory
}

export interface UploadedFile {
  url: string
  md5: string
  size: number
  kind: FileKind
  resource_id: number
  storage_path: string
  expire_time: string | null
  doc_category: DocCategory | null
  /** 是否复用了该用户已上传的同内容资源 */
  reused: boolean
}

/**
 * 通用文件上传：必须已登录。
 * 后端自动识别类型：uploadPurpose=1 的图片会同时更新当前用户头像。
 */
export function uploadFile(
  file: File,
  options: UploadOptions = {},
): Promise<UploadedFile> {
  const body = new FormData()
  body.append('file', file)
  body.append('upload_purpose', String(options.uploadPurpose ?? 0))
  body.append('storage_scene', String(options.storageScene ?? 0))
  if (options.docCategory) {
    body.append('doc_category', options.docCategory)
  }
  return request<UploadedFile>('/files', { method: 'POST', body })
}
