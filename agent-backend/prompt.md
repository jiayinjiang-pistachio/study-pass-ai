# 初始化项目
根据{{FastAPI}}初始化项目代码，要求如下：
1,需要创建虚拟环境并激活，安装相关依赖：
2.按路由层、校验层、业务层、数据库层四层组织代码：
了。数据库层仅用内存字典模拟，不连接真实数据库：
4.实现用户信息增删改查接口，用户包含{id}}、{{username}}、
5.密码使用{passlib[bcrypt]}做哈希加密，存储时不保留明文：
6.复用{Pydantic(v2)}}做请求/响应参数校验；
7.代码简洁高效，并合理添加注释：

## 生成{{FastAPI}}统一错误处理代码
### 核心目标
报错前端中文可读、后端可定位
### 关键要求
1.自定义业务/系统两类异常类
2.标准化响应模型（含code/message/detail)
3。注册全局异常处理器
4,在用户信息接口中加上错误处理功能
### 实现步骤
自定义异常→响应模型→日志配置→全局处理器业务示例

# 用FastAPI+·SQLALchemy2.0+MySQL实现用户信息数据建模：
1. 定义User表(id自增主键、username添加唯一索引、password、create_time自动填充当前时间)
2. 配置MySQL连接串{{mysql_UrL}}，从env中导入环境变量
3. 集成ALembic管理表结构变更，支持修改表结构后一键同步到数据库

# 实现环境变量分层管理和日志体系
1,环境变量分层：支持开发/生产。
2,敏感信息只走环境变量/配置层，不写死在业务代码。
3.建立日志体系：日志文件用于留痕与排障，避免多余日志。
4.最后补齐忽略规则

# 在项目里完善稳定性保证：
实现健康检查接口，并补齐基础冒烟测试。
要求：
1. 健康检查：实现
`/hea1th`接口，校验服务存活及数据库连通性，异常返回503。
2. 冒烟测试：用`pytest`+`httpx`编写用户接口测试用例。
3. 交付：说明改动文件及运行测试命令(`pytest tests/test_smoke.py-v`)。

# 实现登录接口：
JWT鉴权全流程，包括：
登录时使用PyJWT性成访问令牌(Access Token)和刷新令牌(Refresh Token)。
使用鉴权保护接口，验证请求的有效性。
当访问令牌过期时，自动使用刷新令牌获取新的访问令牌，并重试原请求，无需用户手动操作。
token密钥必须通过环境变量进行安全存储。

# 安全实现注册接口，保持代码简洁：
I.注册接口：新增/auth/register,复用UserService.create_user
2,密码加密：bcrypt哈希，禁止明文入库
3。弱密码校验：黑名单+必须字母+数字+禁止包含用户名
4.接口限流：固定窗口+IP维度，限制最多注册5次/min

# 实现前端登录功能：
1.引入axios并二次封装(请求头带token,401自动刷新并重试，失败清理token并跳
登录)。
2,统一错误提示：全局捕获axios错误信息；
3,调用接口文档中的登录注册接口，处理登录和注册逻辑。
4,路由前置守卫拦截未登录：在路由守卫中检查token,未登录则跳转到登录页。
5.登录成功后，保存token到LocalStorage。
6,头部按钮支持退出登录：添加退出登录按钮，点击后清理token并跳转到登录页。

# 用户注册时，实现头像上传功能
1,用户选择头像时，只在本地预览，不上传。
2,点击注册时，先用文本信息创建账号，成功后自动登录以获取Token。
3.登录成功后，再发起已认证的头像上传请求。”
4."使用Pinia全局管理用户信息”


# 创健一个需认证的通用文件上传接口。该接口需自动判断文件类型：
如果是图片，则保存文件并更新用户数据库中的avatar字段。
如果是文档，则只保存文件。
存储逻辑：文件保存在按用户ID划分的目录中，并使用文件内容的MD5哈希值作为文件名以实现去重。


# 创建资源元数据表：统一管理音频、文件、图片，MD5实现用户级去重
CREATE TABLE `resources` (
`id` bigint NOT NULL AUTO_INCREMENT COMMENT '资源主键ID',
`resource_type` tinyint NOT NULL COMMENT '资源类型：0=文件，1=图片，2=音频'，
`storage_scene` tinyint NOT NULL DEFAULT '0' COMMENT '存储场景：0=长过期时间
(1个月)，1=短过期时间(2小时)；2=只提取内容不存原文件/音频'，
`upload_purpose` tinyint NOT NULL DEFAULT '0' COMMENT '上传用途：0=普通资源，
1=用户头像'，
`file_name` varchar(255) NOT NULL COMMENT '用户上传原始文件名'，
`file_hash`varchar(64) NOT NULL COMMENT '文件MD5, 去重核心字段'，
`storage_path` varchar(512) NOT NULL COMMENT 'MinIO对象存储路径'，
`user_id` bigint NOT NULL COMMENT '上传用户ID',
`expire_time` datetime DEFAULT NULL COMMENT '资源过期时间'，
`create time` datetime DEFAULT CURRENT TIMESTAMP COMMENT '创建时间'，
PRIMARY_KEY (id'),
UNIQUE_KEY `uk_file_hash_user_id` (`file_hash`, `user_id`) COMMENT '用户+MD5联合去重'
) ENGINE=InnoDB DEFAULT CHARSET =utf8mb4 COMMENT ='资源元数据表';

#请按“元数据与文件解耦”架构，完成MinIO对象存储改造。
目标：
MySQL resources 存元数据；
MinIO 存原文件；
/upload/file接口路径不变。

要求：
1.保留去重规则：UNIQUE(file_hash,user_id)(代码层可预查，数据库兜底)
2.上传改为 MinIO put_object; storage_path格式：minio:/{bucket}/{object_key}。
3.storage_scene=2 只写资源记录，不上传原文件。
4.新增 upload_purpose 入参(0=general,1=avatar),仅upload_purpose=1且图片类型时更新users.avatar。
5.创建 MinIO 客户端并在环境变量中配置连接变量。
6.教学/运行分离：
- upload_service.py保留旧本地逻辑（不运行）；
- 新建upload_service_minio.py作为运行逻辑；
- /upload/file路由切到upload_service_minio.py。
7.新增过期清理：每天03:00扫描expire_time,先删MinIO对象，再删元数据；
8.更新requirements(minio依赖)。
9.代码简洁：职责单一、注释清晰、无冗余分支。