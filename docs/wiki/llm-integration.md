# LLM 集成 Wiki

## 概述

Jarvis 支持多种 LLM 提供商，通过统一的 `ModelProvider` 接口实现模型无关的集成。

## 支持的模型提供商

| 提供商 | 模型 | API 模式 | 思维链支持 |
|--------|------|----------|-----------|
| OpenAI | GPT-4o, GPT-4 | responses / chat_completions | ✅ reasoning_content |
| Anthropic | Claude 3.5 | messages | ✅ thinking 标签 |
| MiniMax | MiniMax-M3 | chat_completions | ✅ `<think>` 标签 |
| 兼容 API | 各种 | chat_completions | 视实现而定 |

## 配置

### 环境变量

```bash
# 模型选择
OPENAI_MODEL=gpt-4o
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# API 配置
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODE=chat_completions  # 或 responses

# 思维链配置
OPENAI_ENABLE_THINKING=true
OPENAI_THINKING_BUDGET=10000
```

### 配置文件

```python
# jarvis/config.py
class ModelSettings:
    provider: str = "openai"
    model: str = "gpt-4o"
    api_mode: str = "chat_completions"
    enable_thinking: bool = False
    thinking_budget: int = 10000
    timeout_seconds: float = 30.0
    max_retries: int = 3
```

## ModelProvider 接口

```python
class ModelProvider(Protocol):
    model: str
    api_mode: str

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[ConversationItem],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> ModelResponse: ...

    def health_check(self) -> ProviderStatus: ...
```

### ModelResponse 结构

```python
@dataclass
class ModelResponse:
    output_items: list[ConversationItem]  # 输出项（消息、工具调用）
    output_text: str                      # 文本输出
    model: str                            # 使用的模型
    input_tokens: int                     # 输入 token 数
    output_tokens: int                    # 输出 token 数
```

## 思维链（Thinking Chain）

### 什么是思维链

思维链是模型在生成最终回答前的推理过程，帮助用户理解模型的思考逻辑。

### 支持的格式

#### 1. OpenAI Responses API

```json
{
  "output": [
    {
      "type": "reasoning",
      "reasoning": "让我分析这个问题..."
    },
    {
      "type": "message",
      "content": "最终回答"
    }
  ]
}
```

#### 2. Anthropic Messages API

```json
{
  "content": [
    {
      "type": "thinking",
      "thinking": "用户想要..."
    },
    {
      "type": "text",
      "text": "最终回答"
    }
  ]
}
```

#### 3. `<think>` 标签格式（MiniMax 等）

```
<think>
用户问的是天气问题，我需要查询天气 API。
</think>

今天北京天气晴朗，气温 25°C。
```

### 实现细节

```python
# openai.py 中的思维链解析
def _parse_thinking(content: str) -> tuple[str, str]:
    """Parse thinking from content.

    Returns:
        (thinking_text, clean_content)
    """
    # 1. 检查 `<think>` 标签
    think_match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
    if think_match:
        return think_match.group(1), content[think_match.end():].strip()

    # 2. 检查 reasoning 字段
    # 3. 返回空思考和原内容
    return "", content
```

### 流式输出

```python
# 回调函数类型
TextDeltaCallback = Callable[[str], None]
ThinkingDeltaCallback = Callable[[str], None]

# 使用示例
def on_text(delta: str):
    print(delta, end="", flush=True)

def on_thinking(delta: str):
    print(f"[思考] {delta}", end="", flush=True)

response = provider.respond(
    instructions="...",
    input_items=[...],
    tools=[...],
    on_text_delta=on_text,
    on_thinking_delta=on_thinking,
)
```

## API 模式详解

### Chat Completions 模式

标准的聊天完成 API：

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": instructions},
        *[{"role": msg.role, "content": msg.content} for msg in history],
    ],
    tools=tools,
)
```

**特点：**
- 广泛兼容
- 工具调用格式标准
- 适合大多数场景

### Responses API 模式

OpenAI 新版 API，支持更丰富的输出类型：

```python
response = client.responses.create(
    model="gpt-4o",
    instructions=instructions,
    input=[...],
    tools=tools,
)
```

**特点：**
- 支持 reasoning 输出类型
- 更结构化的响应
- 仅 OpenAI 支持

## 工具调用

### 工具定义格式

```json
{
  "type": "function",
  "name": "search_memory",
  "description": "搜索长期记忆",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "搜索关键词"
      },
      "limit": {
        "type": "integer",
        "description": "返回数量",
        "default": 5
      }
    },
    "required": ["query"],
    "additionalProperties": false
  },
  "strict": true
}
```

### 工具调用流程

```
模型输出 ToolCall
    ↓
ToolExecutor.execute()
    ├─→ 解析参数
    ├─→ 权限检查
    ├─→ 执行工具
    └─→ 返回 ToolResult
    ↓
ToolResult 加入历史
    ↓
继续 ReAct 循环
```

### 工具调用示例

```python
# 模型输出
ToolCall(
    call_id="call_123",
    name="read_file",
    arguments='{"path": "test.txt"}'
)

# 执行结果
ToolResult(
    call_id="call_123",
    output="文件内容..."
)
```

## 流式处理

### 基本流式输出

```python
def chat_stream(user_text: str):
    def on_text(delta: str):
        sys.stdout.write(delta)
        sys.stdout.flush()

    response = agent.chat(
        user_text,
        on_text_delta=on_text,
    )
    return response
```

### 思考链流式输出

```python
def chat_with_thinking(user_text: str):
    thinking_buffer = []
    text_buffer = []

    def on_thinking(delta: str):
        thinking_buffer.append(delta)
        print(f"\033[90m{delta}\033[0m", end="", flush=True)

    def on_text(delta: str):
        text_buffer.append(delta)
        print(delta, end="", flush=True)

    response = agent.chat(
        user_text,
        on_text_delta=on_text,
        on_thinking_delta=on_thinking,
    )

    return {
        "thinking": "".join(thinking_buffer),
        "text": response,
    }
```

## 错误处理

### 错误类型

```python
class ProviderRequestError(RuntimeError):
    category: str      # 错误类别
    retryable: bool    # 是否可重试
    status_code: int   # HTTP 状态码
```

### 错误类别

| 类别 | 说明 | 可重试 |
|------|------|--------|
| `rate_limit` | 请求频率限制 | ✅ |
| `timeout` | 请求超时 | ✅ |
| `auth` | 认证失败 | ❌ |
| `invalid_request` | 无效请求 | ❌ |
| `server_error` | 服务器错误 | ✅ |
| `network` | 网络错误 | ✅ |

### 重试策略

```python
# 配置
max_retries = 3
timeout_seconds = 30.0

# 重试逻辑
for attempt in range(max_retries):
    try:
        return provider.respond(...)
    except ProviderRequestError as e:
        if not e.retryable or attempt == max_retries - 1:
            raise
        wait_time = 2 ** attempt  # 指数退避
        time.sleep(wait_time)
```

## Token 计数

### Token 使用追踪

```python
response = provider.respond(...)
print(f"输入 tokens: {response.input_tokens}")
print(f"输出 tokens: {response.output_tokens}")
print(f"总计: {response.input_tokens + response.output_tokens}")
```

### 历史压缩

当历史过长时，自动触发摘要压缩：

```python
class HistoryManager:
    def trim(self):
        if len(self._history) > max_items:
            # 保留最近 N 条
            # 对更早的历史生成摘要
            summary = self._summary_service.summarize(old_items)
            self._history = [summary] + recent_items
```

## 性能优化

### 1. 流式输出

减少首字延迟，提升用户体验。

### 2. 并行工具调用

```python
# ToolExecutor 支持批量执行
results = tool_executor.execute_batch(calls)  # 并行执行
```

### 3. 缓存

- 模型响应缓存（未来）
- 工具结果缓存（未来）

### 4. 历史压缩

定期压缩历史，减少 token 使用。

## 最佳实践

### 1. 指令设计

```python
instructions = """
你是贾维斯，一个可靠、冷静而友好的中文个人助理。
规则：
- 优先使用中文回答
- 模型只能提出工具调用，不能声称执行了未调用的操作
- 读取个人偏好前，先搜索长期记忆
- 只有用户明确要求"记住"时，才保存长期记忆
- 不保存密码、API 密钥等敏感信息
"""
```

### 2. 工具设计

- 清晰的名称和描述
- 严格的参数 schema
- 合理的风险等级
- 有用的错误消息

### 3. 错误处理

- 捕获特定异常类型
- 提供有意义的错误消息
- 实现适当的重试逻辑

## 调试技巧

### 1. 查看原始请求

```python
import logging
logging.getLogger("httpx").setLevel(logging.DEBUG)
```

### 2. 查看 token 使用

```python
# /status 命令显示最近请求信息
latest = agent.model_requests.latest_model_request()
print(f"模型: {latest['model']}")
print(f"延迟: {latest['latency_ms']}ms")
print(f"Tokens: {latest['input_tokens']}/{latest['output_tokens']}")
```

### 3. 思维链调试

```bash
# 启用思维链
OPENAI_ENABLE_THINKING=true

# 查看思维过程
jarvis "你的问题"
```

## 相关文档

- [[code-architecture]] - 代码架构
- [[security-model]] - 安全模型
- [[troubleshooting]] - 故障排除
