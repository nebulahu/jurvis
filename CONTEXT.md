# Jarvis 领域上下文

本文件是 Jarvis 项目的领域词汇表和架构概览。`docs/agents/domain.md` 要求 AI agent 在探索代码前先阅读此文件。

## 词汇表

| 术语 | 定义 |
|---|---|
| **Jarvis** | 运行在 Windows 上的个人 AI 助手，支持文字和语音交互、长期记忆、受控工具调用和桌面操作 |
| **Agent** | `JarvisAgent`，应用层核心服务。持有 Provider、ToolRegistry、PermissionPolicy 和 AssistantStore，驱动对话和工具调用循环 |
| **ModelProvider** | 端口协议。抽象 LLM 服务的 `respond()` 和 `health_check()`，当前适配 OpenAI Responses API 和 Chat Completions API |
| **AssistantStore** | 端口协议。抽象持久化存储，包括对话记录、长期记忆、模型请求指标、工具审计和会话摘要 |
| **ConfirmationPort** | 端口协议。抽象用户确认交互，CLI 实现为终端 y/N 提示 |
| **ToolRegistry** | 工具注册表。管理工具定义、schema 导出、执行调度和取消回调 |
| **Tool** | 单个工具定义，包含名称、描述、JSON Schema 参数、基础风险等级、执行处理器、风险解析器和参数预览器 |
| **RiskLevel** | L0-L4 五级风险枚举。L0 自动执行，L1 记录执行，L2/L3 需确认，L4 默认禁止 |
| **PermissionPolicy** | 权限策略。根据 RiskLevel 和 auto_approve_level 决定自动批准、询问用户或拒绝 |
| **PathGuard** | 路径守卫。限制文件工具只能访问 `JARVIS_ALLOWED_ROOTS` 中的目录 |
| **DesktopActionRiskPolicy** | 桌面动作风险策略。运行时根据目标窗口、控件角色和动作类型动态提升风险等级 |
| **DesktopObserver** | 端口协议。抽象只读桌面观察：窗口枚举、前台识别、UIA 快照、截图 |
| **DesktopController** | 端口协议。扩展 DesktopObserver，增加语义动作执行：聚焦、Invoke、填写、快捷键、滚动、坐标点击 |
| **ApplicationLauncher** | 端口协议。抽象 Windows 应用启动，限制在允许列表内 |
| **Recorder / Transcriber / Speaker** | 端口协议。分别抽象录音、语音转写和语音播放 |
| **VoiceSession** | 应用层语音会话服务。管理 VoiceStateMachine 状态转换（IDLE → LISTENING → RECORDING → TRANSCRIBING → THINKING → SPEAKING） |
| **VoiceStateMachine** | 语音状态机。线程安全，定义合法状态转换，支持中断和错误恢复 |
| **SummaryService** | 摘要服务。对话历史超限时调用 LLM 生成结构化摘要，写入 AssistantStore |
| **MemoryPolicy** | 记忆保存策略。检测敏感内容（密码、支付信息），决定 ALLOW / REJECT / DOWNGRADE |
| **Ranking** | 记忆检索排序。五维评分：关键词命中、重要度、置信度、访问频率、时间衰减 |
| **Settings** | 配置聚合根。包含 ModelSettings、StorageSettings、SafetySettings、DesktopSettings、VoiceSettings、WakeSettings 子组 |
| **ChatMessage / ToolCall / ToolResult** | 应用层领域模型。厂商无关的对话项类型，Provider 适配器负责转换 |
| **ConversationItem** | `ChatMessage | ToolCall | ToolResult` 的联合类型别名 |
| **ImageContent / TextContent** | 消息内容类型。ImageContent 携带本地路径、媒体类型、授权标记和截图标识 |
| **DesktopSnapshot** | UIA 控件树快照。包含窗口引用、元素树、截断标记和有效期 |
| **DesktopScreenshot** | 窗口截图。包含本地临时 BMP 路径、尺寸、有效期，不外发不长期落盘 |
| **ElementRef** | UIA 元素引用。会话级随机标识，绑定到快照，包含角色、名称、Pattern 和敏感标记 |
| **ActionResult** | 桌面动作结果。状态为 success / failed / ambiguous / cancelled，附带验证证据 |
| **bootstrap** | 依赖装配入口。`build_agent()` 是唯一组装点，创建所有端口和适配器实例 |
| **Obsidian** | 长期记忆的 Markdown 同步目标。记忆写入 `E:\CodexLib\Jarvis\` 下的分类目录 |

## 架构概览

```
interfaces/cli          用户交互入口（CLI 命令、语音模式、唤醒模式）
 └─ application          应用服务层（不依赖外部库）
     ├─ JarvisAgent      对话编排、工具调用循环、历史管理
     ├─ VoiceSession     语音状态机和会话管理
     ├─ SummaryService   历史截断前摘要生成
     ├─ MemoryPolicy     敏感内容检测和保存决策
     ├─ Ranking          可解释记忆排序
     └─ models           厂商无关领域模型
         └─ ports        端口协议（ModelProvider, AssistantStore, ConfirmationPort,
                          DesktopObserver, DesktopController, ApplicationLauncher,
                          Recorder, Transcriber, Speaker）
             └─ adapters 适配器实现
                 ├─ providers/openai     OpenAI Responses + Chat Completions
                 ├─ storage/sqlite       SQLite FTS5 存储
                 ├─ storage/obsidian     Obsidian Markdown 同步
                 ├─ tools/               工具注册（system, filesystem, memory, desktop）
                 ├─ audio/               录音、STT、TTS、唤醒词、VAD
                 └─ desktop/             Windows UIA、窗口枚举、截图

bootstrap.py 是唯一依赖装配入口。
config.py 提供 Settings 聚合根，从 .env 加载六个配置子组。
```

依赖方向：interfaces → application → ports ← adapters。application 层不导入 adapters。
