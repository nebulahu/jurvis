# Jarvis 代码架构 Wiki

## 概述

Jarvis 是一个基于六边形架构（Hexagonal Architecture）的 AI 助手系统，采用端口-适配器模式实现关注点分离。

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Interfaces Layer                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │   CLI    │  │   API    │  │  Voice   │  │  Health  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
├───────┼──────────────┼──────────────┼──────────────┼─────────────┤
│       │      Application Layer     │              │             │
│  ┌────▼────────────────────────────▼──────────────▼─────┐      │
│  │                   JarvisAgent                        │      │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │      │
│  │  │ HistoryMgr  │ │ ReActEngine │ │  LATSEngine  │   │      │
│  │  └─────────────┘ └─────────────┘ └─────────────┘   │      │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │      │
│  │  │ToolExecutor │ │   Router    │ │   Planner   │   │      │
│  │  └─────────────┘ └─────────────┘ └─────────────┘   │      │
│  │  ┌─────────────┐ ┌─────────────┐                    │      │
│  │  │  Reflector  │ │  MemorySvc  │                    │      │
│  │  └─────────────┘ └─────────────┘                    │      │
│  └─────────────────────────────────────────────────────┘      │
├───────────────────────────────────────────────────────────────┤
│                          Ports Layer                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │  Model   │  │  Tools   │  │ Storage  │  │  Audio   │     │
│  │ Provider │  │ Registry │  │  Memory  │  │  Voice   │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
├───────────────────────────────────────────────────────────────┤
│                       Adapters Layer                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │  OpenAI  │  │ Default  │  │  SQLite  │  │  Voice   │     │
│  │Anthropic │  │  Tools   │  │ Obsidian │  │  Wake    │     │
│  │ MiniMax  │  │ Desktop  │  │          │  │          │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└───────────────────────────────────────────────────────────────┘
```

## 目录结构

```
src/jarvis/
├── __init__.py
├── __main__.py          # CLI 入口
├── bootstrap.py         # 依赖注入容器
├── config.py            # 配置管理
├── safety.py            # 安全策略
├── sensitive.py         # 敏感内容检测
├── logging_config.py    # 日志配置
├── _env.py              # 环境变量加载
│
├── ports/               # 端口定义（接口）
│   ├── model.py         # ModelProvider Protocol
│   ├── tools.py         # ToolRegistry, Tool
│   ├── storage.py       # MemoryPort, AuditPort
│   ├── models.py        # 领域模型
│   ├── audio.py         # 音频端口
│   ├── desktop.py       # 桌面操作端口
│   └── ...
│
├── application/         # 应用层（业务逻辑）
│   ├── assistant.py     # JarvisAgent 主编排器
│   ├── react_engine.py  # ReAct 循环引擎
│   ├── lats_engine.py   # LATS 求解器
│   ├── tool_executor.py # 工具执行器
│   ├── history_manager.py # 历史管理
│   ├── intent.py        # 意图分类器
│   ├── router.py        # 请求路由
│   ├── planner.py       # 任务规划
│   ├── reflection.py    # 自我反思
│   ├── tree_search.py   # MCTS 树搜索
│   ├── memory_service.py # 记忆服务
│   ├── summary.py       # 摘要服务
│   └── ...
│
├── adapters/            # 适配器层（实现）
│   ├── providers/       # 模型提供商
│   │   ├── openai.py    # OpenAI/兼容 API
│   │   └── anthropic.py # Anthropic Claude
│   ├── tools/           # 工具实现
│   │   ├── default.py   # 默认工具集
│   │   ├── filesystem.py # 文件操作
│   │   ├── memory.py    # 记忆工具
│   │   └── desktop.py   # 桌面操作
│   ├── storage/         # 存储实现
│   │   ├── sqlite.py    # SQLite 存储
│   │   └── obsidian.py  # Obsidian 笔记
│   └── ...
│
└── interfaces/          # 接口层
    ├── cli.py           # 命令行界面
    └── health.py        # 健康检查
```

## 核心模块详解

### 1. JarvisAgent（assistant.py）

主编排器，负责协调所有组件：

```python
class JarvisAgent:
    """Composes: HistoryManager, ToolExecutor, ReActEngine, LATSEngine, Router"""

    def chat(self, user_text: str, ...) -> str:
        # 1. 管理历史
        # 2. 意图路由（可选）
        # 3. ReAct 循环或 LATS 求解
        # 4. 返回响应
```

**依赖组件：**
- `HistoryManager` - 对话历史管理
- `ToolExecutor` - 工具执行与权限检查
- `ReActEngine` - ReAct 推理循环
- `LATSEngine` - 树搜索求解
- `Router` - 意图路由（可选）

### 2. ReActEngine（react_engine.py）

实现 ReAct（Reasoning + Acting）循环：

```python
class ReActEngine:
    def run(self, history, on_text_delta, on_thinking_delta) -> str:
        for _ in range(max_rounds):
            response = self._get_response(history)
            calls = extract_tool_calls(response)

            if not calls:
                return response.output_text

            self._execute_tools(calls, history)

        return "超过最大轮次"
```

**ReAct 循环流程：**
1. 模型推理 → 生成响应
2. 检查是否有工具调用
3. 无工具调用 → 返回最终答案
4. 有工具调用 → 执行工具 → 结果加入历史 → 回到步骤 1

### 3. ToolExecutor（tool_executor.py）

工具执行器，处理权限和审计：

```python
class ToolExecutor:
    def execute(self, call: ToolCall) -> ToolExecutionResult:
        # 1. 获取工具定义
        # 2. 检查权限（PermissionPolicy）
        # 3. 记录审计日志
        # 4. 执行工具
        # 5. 返回结果
```

### 4. IntentClassifier（intent.py）

多层意图分类器：

```python
class IntentClassifier:
    def classify(self, text, context) -> IntentResult:
        # Layer 1: 系统命令（/ 开头）
        # Layer 2: 记忆操作（关键词匹配）
        # Layer 3: 闲聊（短文本/关键词）
        # Layer 4: 复杂任务（多步骤指示词）
        # Layer 5: 默认 TOOL_USE
```

**意图类型：**
| 意图 | 说明 | 处理方式 |
|------|------|----------|
| SIMPLE_QA | 简单问答 | 直接回答 |
| TOOL_USE | 需要工具 | ReAct 循环 |
| COMPLEX_TASK | 复杂任务 | LATS 或 Planner |
| CHITCHAT | 闲聊 | 直接回复 |
| MEMORY_OP | 记忆操作 | MemoryHandler |
| SYSTEM_CMD | 系统命令 | 命令处理 |

### 5. LATS / TreeSearch（tree_search.py）

基于 MCTS 的树搜索求解：

```python
class LATS:
    """Monte Carlo Tree Search with UCB1"""

    def search(self, root: TreeNode, iterations: int) -> TreeNode:
        for _ in range(iterations):
            node = self._select(root)      # UCB1 选择
            child = self._expand(node)     # 扩展
            reward = self._simulate(child) # 模拟
            self._backpropagate(child, reward)  # 回传
        return root.most_visited_child()
```

**UCB1 公式：**
```
UCB1 = 平均价值 + C × √(ln(父节点访问次数) / 节点访问次数)
```

### 6. HistoryManager（history_manager.py）

对话历史管理，支持摘要压缩：

```python
class HistoryManager:
    def trim(self):
        if len(self._history) > max_items:
            # 触发摘要服务压缩历史
            summary = self._summary_service.summarize(old_history)
            self._history = [summary_message] + recent_history
```

## 数据流

### 普通对话流程

```
用户输入
    ↓
JarvisAgent.chat()
    ↓
HistoryManager.add_user_message()
    ↓
IntentClassifier.classify() → TOOL_USE
    ↓
Router.route() → ReActEngine
    ↓
ReActEngine.run()
    ├─→ ModelProvider.respond()
    ├─→ 检查 ToolCall
    ├─→ ToolExecutor.execute()
    └─→ 循环直到无 ToolCall
    ↓
HistoryManager.add_assistant_message()
    ↓
返回响应
```

### 复杂任务流程

```
用户输入
    ↓
IntentClassifier → COMPLEX_TASK
    ↓
LATSEngine.solve()
    ├─→ LATS.search()
    │   ├─→ select (UCB1)
    │   ├─→ expand
    │   ├─→ simulate
    │   └─→ backpropagate
    └─→ 返回最优解
    ↓
返回响应
```

## 关键设计模式

### 1. 端口-适配器模式

```python
# 端口定义（接口）
class ModelProvider(Protocol):
    def respond(self, ...) -> ModelResponse: ...

# 适配器实现
class OpenAIProvider:
    def respond(self, ...) -> ModelResponse:
        # 调用 OpenAI API
```

### 2. 依赖注入

```python
# bootstrap.py 组装所有依赖
def build_agent(settings: Settings) -> JarvisAgent:
    provider = build_provider(settings)
    tools = build_default_registry(...)
    memory = SQLiteStore(...)

    return JarvisAgent(
        provider=provider,
        tools=tools,
        memory=memory,
        ...
    )
```

### 3. 策略模式

```python
# 权限策略
class PermissionPolicy:
    def decide(self, tool_name, risk, arguments) -> PermissionDecision:
        if risk <= self.auto_approve_level:
            return PermissionDecision(True, "自动批准")
        return self._request_approval(...)
```

## 测试策略

- **单元测试**：测试各个组件的独立功能
- **集成测试**：测试组件间的交互
- **Mock 测试**：使用 FakeProvider 等模拟对象

```python
class FakeProvider:
    model = "fake-model"
    api_mode = "chat_completions"

    def respond(self, **kwargs):
        return ModelResponse(output_text="模拟响应")
```

## 扩展指南

### 添加新工具

```python
# 1. 定义工具
def my_tool(param: str) -> str:
    return f"结果: {param}"

# 2. 注册到 ToolRegistry
registry.register(Tool(
    name="my_tool",
    description="我的工具",
    parameters={"param": {"type": "string"}},
    risk=RiskLevel.L1,
    handler=my_tool,
))
```

### 添加新模型提供商

```python
# 实现 ModelProvider Protocol
class MyProvider:
    model = "my-model"
    api_mode = "chat_completions"

    def respond(self, *, instructions, input_items, tools, **kwargs):
        # 调用模型 API
        return ModelResponse(...)

    def health_check(self):
        return ProviderStatus(ok=True, ...)
```

## 相关文档

- [[llm-integration]] - LLM 集成详解
- [[security-model]] - 安全模型
- [[api-reference]] - API 参考
