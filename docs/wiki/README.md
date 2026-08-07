# Jarvis Wiki

欢迎来到 Jarvis AI 助手的文档中心。

## 文档目录

### 📚 架构与设计

- [[code-architecture]] - 代码架构详解
  - 六边形架构设计
  - 目录结构说明
  - 核心模块详解
  - 数据流和设计模式

### 🤖 LLM 集成

- [[llm-integration]] - LLM 集成指南
  - 支持的模型提供商
  - 思维链（Thinking Chain）配置
  - API 模式详解
  - 工具调用机制
  - 流式处理和错误处理

### 🔒 安全模型

- [[security-model]] - 安全策略
  - 风险等级分类
  - 权限控制机制
  - 路径安全保护
  - 敏感内容检测
  - 工具审计日志

### 🔧 故障排除

- [[troubleshooting]] - 常见问题解决
  - 模型连接问题
  - 思维链不显示
  - 工具执行问题
  - 性能优化建议
  - 调试技巧

## 快速开始

### 安装

```bash
pip install -e .
```

### 配置

```bash
# 设置环境变量
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4o"
export OPENAI_API_MODE="chat_completions"
```

### 运行

```bash
# 交互模式
jarvis

# 单次查询
jarvis "今天天气怎么样？"

# 启用思维链
OPENAI_ENABLE_THINKING=true jarvis "解释量子计算"
```

## 核心概念

### 1. ReAct 架构

Jarvis 使用 ReAct（Reasoning + Acting）架构：

```
用户输入 → 模型推理 → 工具调用 → 结果反馈 → 最终回答
```

### 2. 意图路由

智能识别用户意图，选择最佳处理方式：

- **简单问答** → 直接回答
- **工具使用** → ReAct 循环
- **复杂任务** → LATS 树搜索
- **闲聊** → 直接回复
- **记忆操作** → 记忆服务

### 3. 安全优先

所有操作都经过安全检查：

- 风险分级（L0-L4）
- 权限确认
- 路径保护
- 敏感内容检测
- 审计日志

## 开发指南

### 添加新工具

```python
from jarvis.ports.tools import Tool, ToolRegistry
from jarvis.safety import RiskLevel

def my_tool(param: str) -> str:
    return f"结果: {param}"

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
from jarvis.ports.model import ModelProvider, ProviderStatus
from jarvis.ports.models import ModelResponse

class MyProvider:
    model = "my-model"
    api_mode = "chat_completions"

    def respond(self, **kwargs):
        # 调用模型 API
        return ModelResponse(...)

    def health_check(self):
        return ProviderStatus(ok=True, ...)
```

### 运行测试

```bash
# 运行所有测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_agent.py -v

# 查看覆盖率
python -m pytest tests/ --cov=jarvis
```

## 项目结构

```
jarvis/
├── src/jarvis/           # 源代码
│   ├── ports/            # 端口定义
│   ├── application/      # 应用层
│   ├── adapters/         # 适配器实现
│   └── interfaces/       # 接口层
├── tests/                # 测试代码
├── docs/                 # 文档
│   └── wiki/             # Wiki 文档
├── CLAUDE.md             # Claude 配置
├── AGENTS.md             # 代理配置
└── pyproject.toml        # 项目配置
```

## 相关链接

- [GitHub 仓库](https://github.com/your-org/jarvis)
- [API 文档](https://api.jarvis.dev)
- [在线演示](https://demo.jarvis.dev)

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 许可证

MIT License

---

**文档维护者：** Jarvis 开发团队
**最后更新：** 2026-08-07
