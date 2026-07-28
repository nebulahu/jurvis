# Jarvis

一个从零开始构建的个人 AI 助手 MVP。当前版本 `0.6.0` 已经完成文字交互核心闭环、Windows 语音交互、流式分句朗读、播放打断、唤醒词、自动录音端点检测，以及 Computer Use 的 M1-M4 受控桌面能力。

## 当前能力

- 支持自定义 API Key、Base URL 和模型名称
- 支持 Responses API 与 Chat Completions API 两种工具调用模式
- 支持流式输出、请求超时、有限自动重试和可读错误分类
- 支持服务健康检查、请求耗时与 Token 记录
- 支持按键录音、独立 STT 服务配置和 Windows 本地 TTS
- 支持连续语音状态机、增量分句播放和 Esc 打断朗读
- 支持 openWakeWord 离线唤醒和 WebRTC VAD 自动收音
- 查询时间、读取目录和 UTF-8 文本文件
- 列出允许的 Windows 应用，并在用户确认后打开应用
- 显式开启后可列出允许窗口、识别前台窗口、读取受限 UIA 控件树、捕获目标窗口本地临时截图，并经确认聚焦窗口、调用语义控件、填写普通文本、发送受限编辑快捷键、滚动语义控件或点击绑定截图的受限坐标
- 经确认后写入文件或保存长期记忆
- 将长期记忆同步为 Obsidian Markdown
- 将对话、记忆和工具审计写入 SQLite
- 使用允许目录和四级权限策略限制工具
- 模型接口与工具注册表解耦，方便以后接入语音或其他模型

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,voice,wake]"
Copy-Item .env.example .env
```

编辑 `.env`，至少填写以下配置：

```dotenv
OPEN_API_KEY=你的密钥
OPEN_BASE_URL=https://你的服务地址/v1
OPEN_MODEL=你的模型名称
OPEN_API_MODE=chat_completions
```

如果使用官方 OpenAI Responses API，可以设置：

```dotenv
OPEN_BASE_URL=https://api.openai.com/v1
OPEN_MODEL=gpt-5.6-sol
OPEN_API_MODE=responses
OPEN_REASONING_EFFORT=medium
```

多数第三方服务和本地模型仅完整兼容 Chat Completions，此时应选择
`OPEN_API_MODE=chat_completions`。服务端还必须支持 function/tool calling，
否则贾维斯可以对话，但无法可靠地调用文件和记忆工具。

配置完成后启动：

```powershell
jarvis
```

`jarvis` 会优先使用 `JARVIS_PROJECT_ROOT`，否则从当前目录或 editable 安装的源码位置自动查找项目根目录和 `.env`。因此安装命令入口后，可以从任意目录启动。打包部署或维护多个实例时，建议显式配置：

```dotenv
JARVIS_PROJECT_ROOT=E:\AiTool\Codex\Jurvis
```

也可以不安装命令入口，直接运行：

```powershell
python -m jarvis
```

CLI 内置命令：

- `/help`：显示帮助
- `/status`：检查模型服务、模型可用性和最近请求指标
- `/clear`：清空当前会话上下文，不删除长期记忆
- `/mem 关键词`：直接搜索长期记忆
- `/voice`：进入连续语音模式，按 Enter 开始和停止录音，Esc 打断朗读
- `/wake`：进入免按键模式，唤醒后自动录音到静音结束
- `/quit`：退出

## 语音配置

录音依赖 `sounddevice`，系统朗读使用 Windows SAPI。语音识别默认复用主模型的 API Key 和 Base URL：

```dotenv
OPEN_STT_MODEL=whisper-1
OPEN_STT_LANGUAGE=zh
JARVIS_VOICE_SAMPLE_RATE=16000
JARVIS_VOICE_MAX_SECONDS=60
JARVIS_TTS_ENABLED=true
JARVIS_TTS_RATE=190
```

如果主模型服务不支持 `/audio/transcriptions`，需要为 STT 单独配置兼容服务：

```dotenv
OPEN_STT_API_KEY=你的语音服务密钥
OPEN_STT_BASE_URL=https://你的语音服务地址/v1
```

运行 `jarvis` 后输入 `/voice`。语音模式会显示录音转写结果，再交给同一个 Agent 处理，因此权限确认、工具审计和长期记忆规则与文字模式完全一致。回答生成时会按完整句子进入后台播放队列；按 Esc 会清空待播放内容、停止当前朗读，并请求取消本轮后续桌面动作，然后可以立即开始下一轮录音。Esc 不取消已经发出的模型请求，但会阻止后续桌面工具继续执行。设置 `JARVIS_TTS_ENABLED=false` 可以只录音和转写，不朗读。

## 唤醒词与自动收音

`/wake` 使用 openWakeWord 的离线模型等待唤醒，并使用 WebRTC VAD 判断讲话开始和静音结束。官方 `hey_jarvis` 模型识别英文短语 **Hey Jarvis**，模型文件需要单独下载：

```powershell
python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis'])"
```

当前网络无法访问 GitHub Release 时，可以在其他网络下载 ONNX 模型，并把 `JARVIS_WAKE_MODEL` 设置为模型绝对路径。相关配置：

```dotenv
JARVIS_WAKE_MODEL=hey_jarvis
JARVIS_WAKE_THRESHOLD=0.5
JARVIS_VAD_MODE=2
JARVIS_VAD_SILENCE_MS=900
JARVIS_VAD_START_TIMEOUT_SECONDS=8
JARVIS_VAD_MAX_SECONDS=30
JARVIS_VAD_MIN_SPEECH_MS=300
```

进入 `/wake` 后，程序会持续访问默认麦克风；等待唤醒或自动录音期间按 Esc 返回文字模式。唤醒检测完全在本机进行，只有唤醒后的命令音频会发送给配置的 STT 服务。

## 安全模型

| 等级 | 示例 | 默认行为 |
|---|---|---|
| L0 | 获取当前时间 | 自动执行 |
| L1 | 搜索记忆、读取允许目录中的文件 | 自动执行并记录 |
| L2 | 写文件、保存长期记忆、打开应用 | 每次询问 |
| L3 | 外部发送、删除等高影响操作 | 每次询问 |
| L4 | 密码、支付、关键系统安全设置 | 默认禁止 |

文件工具只能访问 `JARVIS_ALLOWED_ROOTS` 中配置的目录。即使模型生成了其他路径，执行层也会拒绝。

工具可以在执行前根据实际参数把基础风险等级向上提升，但不能降低。桌面动作的运行时分类基础已建立：普通本地动作最低为 L2，发送、提交、上传、发布和删除类目标提升为 L3，密码、支付、认证及关键安全设置归为 L4。确认框与审计使用脱敏参数预览，真实执行参数不会因此被改写。工具审计会记录风险、应用、窗口、控件、动作状态、验证状态和耗时，并对输入文本、控件文本和错误中的认证、支付或秘密内容再次脱敏。

## Windows 应用启动

助手可以列出并打开 `JARVIS_ALLOWED_APPLICATIONS` 中配置的应用。应用名称使用分号分隔：

```dotenv
JARVIS_ALLOWED_APPLICATIONS=记事本;计算器;文件资源管理器;设置;画图;终端;Obsidian;Google Chrome;Microsoft Edge;ChatGPT
```

记事本、计算器、资源管理器、设置、画图和终端使用固定系统启动方式；其他应用从 Windows 开始菜单精确解析。`ChatGPT` 同时支持 `Codex` 别名。模型不能传入可执行文件路径或命令行参数，所有应用启动都会作为 L2 操作请求确认并写入工具审计。

当前能力覆盖允许应用启动、允许窗口观察、语义化控件动作和目标窗口本地截图。尚不支持把截图发送给视觉模型、任意坐标点击或任意按键脚本。

Computer Use 基础配置默认关闭：

```dotenv
JARVIS_DESKTOP_CONTROL_ENABLED=false
JARVIS_DESKTOP_SNAPSHOT_MAX_NODES=200
JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH=8
JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH=200
JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS=30
JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS=10
JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS=10
JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS=10
JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS=10
JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH=4000
JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH=1920
JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT=1080
JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS=60
JARVIS_DESKTOP_SCREENSHOT_TEMP_DIR=
JARVIS_DESKTOP_VISION_ENABLED=false
```

其中快照节点上限、树深度和单项文本长度用于约束暴露给模型的 UI Automation 内容，快照有效期用于防止操作过期界面，观察、聚焦和动作超时分别限制窗口/UIA 读取、前台聚焦和变更动作，旧的操作超时仍作为兼容默认值，输入文本长度上限用于约束单次普通文本填写。截图配置限制目标窗口截图尺寸、临时文件有效期和临时目录；未设置临时目录时使用系统临时目录下的 `jarvis-screenshots`。`JARVIS_DESKTOP_VISION_ENABLED` 默认关闭；关闭时 Provider 会在组装网络请求前阻止任何图像输入。即使开启，每个图像输入仍必须带有本次用户授权标记，否则同样拒绝发送。保持控制开关为 `false` 不影响现有的应用启动工具。

Windows 适配层已具备只读的顶层窗口枚举、前台窗口识别和 UI Automation 控件树快照能力，只返回允许应用，并用有有效期的会话级随机标识隐藏原始窗口句柄、进程 ID 和原生控件引用。快照限制节点数、树深度和单项文本长度，不读取控件 Value，密码控件名称会被清空。

安装桌面可选依赖并将 `JARVIS_DESKTOP_CONTROL_ENABLED` 显式设为 `true` 后，模型会获得 `list_windows`、`get_active_window`、`inspect_window` 和 `capture_window_screenshot` 四个 L1 只读工具，以及 `focus_window`、`invoke_element`、`set_element_value`、`send_shortcut`、`scroll_element`、`click_coordinate` 和 `select_element` 七个需要确认的语义动作工具。截图工具只捕获允许列表中的目标窗口，默认禁止全桌面截图，生成会话内截图标识并返回本地临时 BMP 路径、窗口状态、尺寸和过期时间；默认不发送到外部服务，也不长期落盘，过期文件按清理策略删除。内部消息模型已经支持文本和本地图像引用；Responses 与 Chat Completions 适配器都能在显式开启视觉并获得本次授权时把本地图像编码为请求内容。模型服务不支持图像输入时会返回 `unsupported_feature` 降级错误，而不是误报为已完成。元素动作只能使用当前允许窗口和未过期快照中的引用，执行后旧快照立即失效。坐标点击只能使用未过期目标窗口截图内的相对坐标；执行前会验证截图属于目标窗口、坐标未越界、窗口位置和尺寸未变化且仍处于前台，点击后重新验证前台状态；疑似提交、上传、删除、购买等目标会提升为 L3。动作后会重新读取窗口或 UIA 状态作为验证证据；无法验证时返回 `ambiguous`，不声称完成；UIA 调用失败返回 `failed`。`set_element_value` 仅使用 UI Automation `ValuePattern` 向普通非敏感控件填写文本，会限制长度，并在确认预览和执行结果中记录脱敏摘要或长度而非完整输入，瞬时失败时最多重试一次。`send_shortcut` 只接受复制、剪切、粘贴、撤销、重做、全选、查找和保存等清单内快捷键，且目标窗口必须仍是前台。`scroll_element` 只通过 UIA `Scroll` 或 `ScrollItem` Pattern 滚动绑定元素。桌面控制器带有线程安全取消令牌；目标窗口关闭、用户抢回前台或语音 Esc 触发取消后，本轮后续桌面动作会返回 `cancelled`。文字、语音和唤醒词入口使用同一个 Agent 和工具注册表，因此能力与审计规则一致：

```powershell
python -m pip install -e ".[desktop]"
```

桌面控制开关默认关闭。窗口聚焦、UIA Invoke/SelectionItem、普通文本填写、受限编辑快捷键、UIA 滚动、允许窗口本地临时截图、受隐私门控的图像输入转换和绑定截图的受限坐标点击已实现；自动视觉工作流和任意按键脚本仍未实现。不会注册裸屏幕坐标点击或任意键鼠脚本工具。

Computer Use 发布门禁、记事本基准、Obsidian/浏览器边界和失败恢复演练见 [`docs/computer-use-release-checklist.md`](docs/computer-use-release-checklist.md)。真实 Windows 应用基准会操作用户桌面，必须在用户确认后执行。

## 记忆结构

结构化数据保存在 `JARVIS_DB_PATH` 指向的 SQLite 数据库。长期记忆同时写入：

```text
E:\CodexLib\Jarvis\<分类>\YYYYMMDD-HHMMSS-标题.md
```

生成的笔记包含 Obsidian properties、标签和信息 callout，可直接在 Obsidian 中搜索和修改。

## 架构

```text
interfaces/cli
 └─ application
     ├─ JarvisAgent
     ├─ VoiceSession / VoiceStateMachine
     ├─ provider-neutral conversation models
     └─ ToolRegistry
         └─ ports
             ├─ ModelProvider
             ├─ AssistantStore
             ├─ ConfirmationPort
             └─ Recorder / Transcriber / Speaker
                 └─ adapters
                     ├─ providers/openai
                     ├─ storage/sqlite + storage/obsidian
                     ├─ tools/system + filesystem + memory + desktop
                     └─ audio/sounddevice + STT + SAPI + wake + VAD

bootstrap.py 是唯一依赖装配入口；config.py 提供模型、存储、安全、语音和唤醒分组配置。
顶层 agent.py、provider.py、memory.py、tools.py、voice.py、wake.py 和 cli.py
仅保留向后兼容导入。
```

两个 Provider 都把厂商消息转换为 `ChatMessage`、`ToolCall` 和 `ToolResult`，
Agent 不保存 SDK 对象。切换模型服务不会绕过权限层：模型只能提出结构化工具调用，
执行器在真正操作前再次检查风险等级与路径。

## 模型服务兼容性

环境变量优先级如下：

| 用途 | 推荐变量 | 兼容旧变量 |
|---|---|---|
| API 密钥 | `OPEN_API_KEY` | `OPENAI_API_KEY` |
| 接口地址 | `OPEN_BASE_URL` | `OPENAI_BASE_URL` |
| 模型名称 | `OPEN_MODEL` | `JARVIS_MODEL` |
| 推理等级 | `OPEN_REASONING_EFFORT` | `JARVIS_REASONING_EFFORT` |

自定义 Base URL 时，程序默认不发送 `reasoning` 参数。只有你明确配置
`OPEN_REASONING_EFFORT` 后才会发送，以减少不同服务之间的参数兼容问题。

稳定性相关配置：

```dotenv
OPEN_TIMEOUT_SECONDS=60
OPEN_MAX_RETRIES=2
JARVIS_MAX_HISTORY_ITEMS=120
```

模型请求的耗时、状态和 Token 用量会写入 SQLite 的 `model_requests` 表。
流式服务未返回 usage 时，Token 数量会记录为 0，而不会进行不准确估算。
工具审计写入 SQLite 的 `audit_log` 表。当前 schema 会保留兼容字段，同时记录风险等级、桌面动作、应用、窗口、控件角色和名称、动作状态、验证状态、耗时和脱敏结果摘要。`/status` 会显示工具审计总数、成功率、超时率、歧义率和用户拒绝率。

## 测试

```powershell
pytest
```

测试不调用真实模型，也不会写入真实 Obsidian 目录。

## 下一阶段

1. 升级语义记忆检索和历史摘要。
2. 增加应用启动、天气、日程和 Home Assistant 技能。
3. 加入桌面悬浮窗、系统托盘、主动提醒、视觉和实体硬件。

## 项目记忆制度

每一个可独立验收的升级步骤，都必须生成对应的 Obsidian 项目记忆。只有代码、测试和项目记忆都完成后，该步骤才算完成。

项目记忆保存在：

```text
E:\CodexLib\20-项目\Jarvis\项目记忆
```

每条记忆至少包含：

- 目标与范围
- 关键设计决策
- 实现内容与改动文件
- 测试和验收结果
- 遗留问题
- 下一步及恢复工作所需上下文

索引位于 `E:\CodexLib\20-项目\Jarvis\Jarvis 项目总览.md`。

## 官方接口资料

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)
