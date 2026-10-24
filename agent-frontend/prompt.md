# 生成全局规则 
@agent-frontend/                                                   
这是该项目的前端项目，请为该前端项目编写全局'规则'文件，当不同团队成员开发时都能自动引用该'规则'，请用中文编写'规则'  

# 拆分组件结构
## 1. 学习室、面试间
[Image #1] 需要你帮我拆分页面结构，进行组件拆分，并列出交互逻辑清单 

保存到文档docs

## 2. 笔记本
需要实现笔记本页面，笔记本页面主内容区域是一个富文
本编辑器，底部没有聊天输入框，选择wantEditor富文本
编辑器，另外学习室页面需要生成，它跟面试间页面很相
似，复用相关组件

# 按照docs生成代码
@docs 在当前项目下，项目中多余的代码需要你删除，然后根据页面
结构拆分结果文档，帮我高度还原这个页面，只预留轻
量化交互功能，组件库使用element plus,样式使用
scss预编译

# 实现聊天页面会话管理，对话数据回显：
- 会话管理支持会话列表分页(GET/sessions`)、新建(`POST / sessions`)、编辑标题(PUT/sessions/{session_id)`)、删除(`DELETE/
sessions/{id}`,操作后刷新并切换会话)。
- 聊天信息：按会话ID分页获取消息(`GET/sessions/{session_id}/
messages`),正文渲染`request_text/response_text`,附件渲染`request_segments/response_segments`(只含`file/image/audio`,字段容
错，结构为`type/name/url/resource_id`)
- 消息区：正文与附件分区显示，附件用独立组件（如`MsgFile.vue`),图片失败显示占位图，音频失败有提示。
- 消息加载：上拉分页（距离顶部10px触发），loading锁防重入，增量追加，按
`created_at`排序。
- 面试卡片：`status=1`时显示卡片，点击调用`GET/interviews/{interview_id)`,弹窗展示`qa_object`。


# 请在前端Vue项目中开发通用型AI对话答案Markdown渲染美化方案，**独立封装markdownUtil.tS工具文件**，核心功能如下：
I.基于MarkdownIt解析Markdown,兼容基础语法；
2,集成Prism.js实现代码高亮，代码块带语言标识；
3.美化表格；
支持横向滚动、斑马纹、悬浮高亮；
4 支持代码主题高亮显示；
5,代码低耦合，可直接迁移至任意系统。


