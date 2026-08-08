# 安全模型 Wiki

## 概述

Jarvis 采用多层安全模型，通过风险分级、权限控制和敏感内容检测来保护用户数据和系统安全。

## 风险等级

```python
class RiskLevel(IntEnum):
    L0 = 0  # 只读、无副作用
    L1 = 1  # 低风险、可逆操作
    L2 = 2  # 中等风险、需要确认
    L3 = 3  # 高风险、敏感操作
    L4 = 4  # 禁止操作
```

### 风险等级说明

| 等级 | 说明 | 示例 | 处理方式 |
|------|------|------|----------|
| L0 | 只读操作 | 搜索记忆、读取文件 | 自动批准 |
| L1 | 低风险操作 | 创建文件、记录记忆 | 自动批准 |
| L2 | 中等风险 | 修改文件、执行命令 | 需要确认 |
| L3 | 高风险 | 删除文件、系统操作 | 需要确认 |
| L4 | 禁止操作 | 访问敏感数据 | 默认拒绝 |

## 权限策略

### PermissionPolicy

```python
class PermissionPolicy:
    def __init__(
        self,
        auto_approve_level: int = 1,
        approval_callback: ApprovalCallback | None = None,
    ):
        self.auto_approve_level = RiskLevel(auto_approve_level)
        self.approval_callback = approval_callback

    def decide(
        self,
        tool_name: str,
        risk: RiskLevel,
        arguments: dict[str, object],
    ) -> PermissionDecision:
        # L4 默认拒绝
        if risk is RiskLevel.L4:
            return PermissionDecision(False, "L4 操作默认禁止")

        # 低于自动批准级别
        if risk <= self.auto_approve_level:
            return PermissionDecision(True, "自动批准")

        # 需要用户确认
        if self.approval_callback is None:
            return PermissionDecision(False, "无确认通道")

        approved = self.approval_callback(tool_name, risk, arguments)
        return PermissionDecision(
            approved,
            "用户已确认" if approved else "用户已拒绝"
        )
```

### 配置示例

```python
# 自动批准 L0 和 L1
policy = PermissionPolicy(auto_approve_level=1)

# 带确认回调
def confirm_callback(tool_name, risk, arguments):
    print(f"工具 {tool_name} 需要确认")
    return input("允许？(y/n): ") == "y"

policy = PermissionPolicy(
    auto_approve_level=1,
    approval_callback=confirm_callback,
)
```

## 路径安全

### PathGuard

限制文件操作只能在允许的目录内：

```python
class PathGuard:
    def __init__(self, allowed_roots: Iterable[Path]):
        self.allowed_roots = tuple(
            Path(root).expanduser().resolve()
            for root in allowed_roots
        )

    def resolve(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser().resolve()

        # 检查路径是否在允许的目录内
        if any(
            path == root or path.is_relative_to(root)
            for root in self.allowed_roots
        ):
            return path

        raise PermissionError(
            f"路径 {path} 不在允许目录中"
        )
```

### 使用示例

```python
# 只允许访问工作目录和文档目录
guard = PathGuard([
    Path.home() / "Documents",
    Path.cwd(),
])

# 安全解析路径
safe_path = guard.resolve(user_input_path)
```

## 敏感内容检测

### 敏感词分类

```python
# L3 级别敏感词（需要确认）
L3_TARGET_TERMS = {
    "密码", "password", "secret",
    "token", "api_key", "private_key",
}

# L4 级别敏感词（禁止操作）
L4_TARGET_TERMS = {
    "系统文件", "注册表", "system32",
    "/etc/passwd", "/etc/shadow",
}
```

### 检测逻辑

```python
def contains_sensitive_text(text: str) -> bool:
    """检测文本是否包含敏感内容"""
    text_lower = text.lower()

    # 检查 L4 敏感词
    for term in L4_TARGET_TERMS:
        if term in text_lower:
            return True

    # 检查密钥格式
    if re.search(r'sk-[a-zA-Z0-9]{20,}', text):
        return True

    return False
```

## 工具审计

### 审计记录

```python
@dataclass
class AuditRecord:
    tool_name: str
    arguments: dict[str, Any]
    allowed: bool
    reason: str
    result: str
    risk_level: int
    timestamp: str
```

### 审计指标

```python
def audit_metrics(self) -> dict[str, Any]:
    return {
        "total": 100,
        "success_rate": 0.95,
        "timeout_rate": 0.02,
        "ambiguous_rate": 0.01,
        "user_rejection_rate": 0.02,
    }
```

## 桌面操作安全

### DesktopActionRiskPolicy

```python
class DesktopActionRiskPolicy:
    def classify(self, context: DesktopActionContext) -> RiskLevel:
        # 检查目标是否敏感
        if context.target_is_sensitive:
            return RiskLevel.L4

        # 检查是否包含敏感词
        target = f"{context.application} {context.window_title}"
        if contains_term(target, L4_TARGET_TERMS):
            return RiskLevel.L4

        # 高影响操作 + 敏感目标 = L3
        high_impact = context.action_kind in {
            DesktopActionKind.INVOKE,
            DesktopActionKind.SEND_KEYS,
        }
        if high_impact and contains_term(target, L3_TARGET_TERMS):
            return RiskLevel.L3

        return RiskLevel.L2
```

### 确认预览

```python
def confirmation_preview(
    self, context: DesktopActionContext
) -> dict[str, object]:
    return {
        "action": context.action_kind.value,
        "application": context.application,
        "window": context.window_title,
        "text_summary": "[敏感内容已隐藏]"
            if context.target_is_sensitive
            else context.payload_text[:80],
    }
```

## 安全最佳实践

### 1. 最小权限原则

```python
# 只授予必要的权限
policy = PermissionPolicy(auto_approve_level=0)  # 默认需要确认
```

### 2. 路径白名单

```python
# 限制文件访问范围
guard = PathGuard([
    project_dir,
    documents_dir,
])
```

### 3. 敏感数据保护

```python
# 不保存敏感信息
MEMORY_KEYWORDS = {"记住", "记录", "保存"}
SENSITIVE_PATTERNS = [r'密码', r'key', r'token']

def should_save_memory(text: str) -> bool:
    # 检查是否包含敏感信息
    if any(re.search(p, text) for p in SENSITIVE_PATTERNS):
        return False
    return True
```

### 4. 审计日志

```python
# 记录所有工具调用
audit.add_audit(
    tool_name=tool.name,
    arguments=arguments,
    allowed=decision.allowed,
    reason=decision.reason,
    result=result,
    risk_level=int(risk),
)
```

## 安全配置

### 推荐配置

```yaml
# 生产环境
safety:
  auto_approve_level: 0  # 所有操作都需要确认
  max_tool_rounds: 6
  enable_audit: true

# 开发环境
safety:
  auto_approve_level: 1  # L0 和 L1 自动批准
  max_tool_rounds: 10
  enable_audit: true
```

### 环境变量

```bash
JARVIS_AUTO_APPROVE_LEVEL=1
JARVIS_MAX_TOOL_ROUNDS=6
```

## 安全事件处理

### 1. 权限拒绝

```python
if not decision.allowed:
    logger.warning(
        "工具调用被拒绝",
        tool=tool_name,
        risk=risk.name,
        reason=decision.reason,
    )
    return ToolExecutionResult(
        error=f"操作被拒绝: {decision.reason}",
        ...
    )
```

### 2. 敏感内容检测

```python
if contains_sensitive_text(payload):
    logger.warning("检测到敏感内容", text_preview=payload[:50])
    return RiskLevel.L4  # 禁止操作
```

### 3. 路径越界

```python
try:
    safe_path = guard.resolve(user_path)
except PermissionError as e:
    logger.warning("路径越界尝试", path=user_path)
    return ToolExecutionResult(error=str(e))
```

## 相关文档

- [[code-architecture]] - 代码架构
- [[llm-integration]] - LLM 集成
- [[troubleshooting]] - 故障排除
