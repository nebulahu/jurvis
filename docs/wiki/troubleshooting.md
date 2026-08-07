# 故障排除 Wiki

## 常见问题

### 1. 模型连接问题

#### 问题：API 超时

```
ProviderRequestError: 请求超时
```

**解决方案：**

```bash
# 增加超时时间
OPENAI_TIMEOUT_SECONDS=60

# 增加重试次数
OPENAI_MAX_RETRIES=5
```

#### 问题：认证失败

```
ProviderRequestError: 认证失败 (401)
```

**解决方案：**

```bash
# 检查 API 密钥
echo $OPENAI_API_KEY

# 确保密钥有效且未过期
# 重新生成密钥并更新环境变量
```

#### 问题：频率限制

```
ProviderRequestError: 请求频率限制 (429)
```

**解决方案：**

```bash
# 等待一段时间后重试
# 或升级 API 计划
# 或配置多个 API 密钥轮换
```

### 2. 思维链不显示

#### 问题：MiniMax 模型没有思维链输出

**原因：** MiniMax 使用 `<think>` 标签格式，而不是单独的字段。

**解决方案：**

```bash
# 确保 API 模式正确
OPENAI_API_MODE=chat_completions

# 启用思维链解析
OPENAI_ENABLE_THINKING=true
```

**验证：**

```python
# 检查响应内容是否包含 `<think>` 标签
response = provider.respond(...)
print(response.output_text)
# 应该看到: <think>...</think>最终回答
```

#### 问题：OpenAI 思维链不显示

**原因：** 需要使用 Responses API 模式。

**解决方案：**

```bash
# 切换到 Responses API
OPENAI_API_MODE=responses

# 启用思维链
OPENAI_ENABLE_THINKING=true
```

### 3. 工具执行问题

#### 问题：工具调用被拒绝

```
操作被拒绝: 该操作需要确认，但当前没有确认通道
```

**解决方案：**

```python
# 提供确认回调
def confirm_callback(tool_name, risk, arguments):
    return input(f"允许 {tool_name}？(y/n): ") == "y"

agent = build_agent(
    settings,
    approval_callback=confirm_callback,
)
```

#### 问题：路径不在允许目录中

```
PermissionError: 路径 /xxx 不在允许目录中
```

**解决方案：**

```python
# 添加允许的目录
guard = PathGuard([
    Path.home() / "Documents",
    Path.cwd(),
    Path("/additional/allowed/path"),
])
```

#### 问题：工具执行超时

**解决方案：**

```bash
# 增加工具超时时间（如果支持）
JARVIS_TOOL_TIMEOUT=60
```

### 4. 历史管理问题

#### 问题：对话历史过长导致 token 超限

**解决方案：**

```bash
# 减少最大历史项数
JARVIS_MAX_HISTORY_ITEMS=80

# 或配置摘要服务自动压缩
```

#### 问题：摘要服务不可用

**原因：** 摘要服务需要模型支持。

**解决方案：**

```python
# 确保摘要服务已配置
summary_service = SummaryService(
    provider=provider,
    max_tokens=500,
)

agent = JarvisAgent(
    ...,
    summary_service=summary_service,
)
```

### 5. 意图识别问题

#### 问题：意图识别不准确

**解决方案：**

```python
# 自定义关键词
from jarvis.application.intent import IntentClassifier

classifier = IntentClassifier()
classifier._MEMORY_KEYWORDS.add("自定义关键词")
```

#### 问题：误分类为 CHITCHAT

**原因：** 短文本默认分类为闲聊。

**解决方案：**

```python
# 调整阈值
classifier = IntentClassifier()
classifier._CHITCHAT_LENGTH_THRESHOLD = 3  # 默认是 5
```

### 6. LATS 树搜索问题

#### 问题：LATS 求解超时

**原因：** 迭代次数过多。

**解决方案：**

```python
# 减少迭代次数
result = lats_engine.solve(task, budget=5)  # 默认是 10
```

#### 问题：LATS 求解质量差

**解决方案：**

```python
# 增加迭代次数和探索常数
lats = LATS(
    model_provider=provider,
    exploration_constant=2.0,  # 增加探索
    max_depth=10,              # 增加深度
    max_children=5,            # 增加分支
)
```

## 调试技巧

### 1. 启用详细日志

```bash
# 设置日志级别
JARVIS_LOG_LEVEL=DEBUG

# 或在代码中
import logging
logging.getLogger("jarvis").setLevel(logging.DEBUG)
```

### 2. 查看模型请求

```python
# /status 命令
latest = agent.model_requests.latest_model_request()
print(json.dumps(latest, indent=2))
```

### 3. 查看工具调用历史

```python
# /audit 命令
metrics = agent.audit.audit_metrics()
print(f"总调用: {metrics['total']}")
print(f"成功率: {metrics['success_rate']:.0%}")
```

### 4. 测试单个组件

```python
# 测试意图分类
from jarvis.application.intent import IntentClassifier

classifier = IntentClassifier()
result = classifier.classify("记住我喜欢咖啡")
print(result)  # IntentResult(intent=MEMORY_OP, ...)
```

### 5. 使用 FakeProvider 测试

```python
class FakeProvider:
    model = "fake-model"
    api_mode = "chat_completions"

    def respond(self, **kwargs):
        return ModelResponse(
            output_text="测试响应",
            output_items=[],
        )

# 测试不依赖真实 API
agent = JarvisAgent(provider=FakeProvider(), ...)
```

## 日志分析

### 日志格式

```
2026-08-07T13:39:13.379189Z [info] 思维链已启用 api_mode=chat_completions model=MiniMax-M3
```

### 关键日志事件

| 事件 | 级别 | 说明 |
|------|------|------|
| `思维链已启用` | info | 思维链配置 |
| `意图路由` | info | 意图分类结果 |
| `工具调用被拒绝` | warning | 权限拒绝 |
| `路径越界尝试` | warning | 安全违规 |
| `反思重试` | info | Reflexion 重试 |
| `模型请求失败` | error | API 错误 |

### 日志查询

```bash
# 查看错误日志
grep "[error]" jarvis.log

# 查看安全事件
grep "拒绝\|越界\|敏感" jarvis.log

# 查看性能问题
grep "超时\|timeout" jarvis.log
```

## 性能优化

### 1. 减少 token 使用

```bash
# 减少历史长度
JARVIS_MAX_HISTORY_ITEMS=60

# 使用更短的指令
# 精简工具描述
```

### 2. 提升响应速度

```bash
# 使用更快的模型
OPENAI_MODEL=gpt-4o-mini

# 减少最大工具轮次
JARVIS_MAX_TOOL_ROUNDS=3
```

### 3. 并行工具调用

```python
# 确保工具支持并行执行
results = tool_executor.execute_batch(calls)  # 并行
```

## 获取帮助

### 1. 查看文档

- [[code-architecture]] - 代码架构
- [[llm-integration]] - LLM 集成
- [[security-model]] - 安全模型

### 2. 运行测试

```bash
# 运行所有测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_agent.py -v
```

### 3. 检查配置

```bash
# 查看当前配置
jarvis --config

# 验证配置
jarvis --validate
```

### 4. 报告问题

1. 收集日志
2. 复现步骤
3. 环境信息
4. 提交 Issue

## 相关文档

- [[code-architecture]] - 代码架构
- [[llm-integration]] - LLM 集成
- [[security-model]] - 安全模型
