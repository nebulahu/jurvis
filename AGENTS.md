# 项目约定

- 所有文本文件使用 UTF-8 编码且不包含 BOM。
- Obsidian 的 ChatGPT 记忆 Vault 根目录为 `E:\CodexLib`；Jarvis 运行时长期记忆当前写入其下的 `Jarvis` 子目录。
- 涉及外部写入、破坏性操作或高风险系统操作时，必须先获得用户确认。
- 每完成一个可独立验收的升级步骤，必须在 `E:\CodexLib\20-项目\Jarvis\项目记忆` 新建或更新对应的项目记忆，然后才视为该步骤完成。
- 项目记忆至少记录：目标与范围、关键决策、实现内容、改动文件、验证结果、遗留问题和下一步。
- 项目总览索引为 `E:\CodexLib\20-项目\Jarvis\Jarvis 项目总览.md`；新增记忆后必须同步更新索引。

## 分支策略

- 主分支：`main`，保持可运行状态。
- 开发分支：`codex/<功能名>`，从 `main` 创建。
- 合并方式：功能完成后 squash merge 到 `main`，保持主分支历史干净。
- 命名约定：`codex/memo-2.0`、`codex/cu-015` 等，小写英文加连字符。

## 提交规范

- 使用 Conventional Commits 格式：`<type>(<scope>): <description>`
- 常用 type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore`
- scope 使用模块名：`memory` / `desktop` / `voice` / `config` / `safety` 等
- description 用英文，祈使句，首字母小写，不加句号
- 示例：`feat(memory): add FTS5 search with LIKE fallback`

## 代码风格

- Python 3.11+，使用 `from __future__ import annotations`
- 类型注解必须完整，不使用 `Any` 除非外部 API 强制要求
- 数据模型使用 `@dataclass(frozen=True, slots=True)`
- 端口使用 `typing.Protocol`，不引入 ABC
- 适配器实现端口协议，不继承抽象基类
- 命名：模块级函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`
- 中文注释和用户可见文本，英文代码标识符

## 测试规范

- 运行命令：`pytest`（配置在 `pyproject.toml`，自动发现 `tests/`）
- 测试不调用真实模型，不写入真实 Obsidian 目录
- 每个新功能至少一个对应测试文件 `tests/test_<module>.py`
- 现有测试 20 个文件，覆盖 agent、config、desktop、memory、provider、safety、summary、tools、voice、wake
- 编译检查：`python -m compileall -q src tests`
- UTF-8 无 BOM 检查：覆盖仓库文本文件和 `E:\CodexLib\20-项目\Jarvis` 下的项目文档

## PR 流程

- 功能开发完成后，在 PR 描述中包含：目标、关键决策、改动文件列表、测试结果
- PR 前必须通过：`pytest` + `python -m compileall -q src tests` + `git diff --check`
- 使用 GitHub Issues 跟踪需求，PR 关联对应 issue 编号

## Agent skills

### Issue tracker

GitHub Issues (nebulahu/jurvis). See `docs/agents/issue-tracker.md`.

### Triage labels

五标签：needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`. Read `CONTEXT.md` before exploring code.
