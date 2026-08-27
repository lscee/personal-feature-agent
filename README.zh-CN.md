# Personal Feature Agent

[English](README.md)

Personal Feature Agent 是一个同时适用于 Codex 和 Claude Code 的插件。它在现有代码仓库中，把一段简单的新功能描述逐步落地为：经过用户校对的需求文档、可工作的代码，以及完成自测的开发环境。

它在“需求规划”和“修改代码”之间设置了明确的工作流门禁：Agent 可以查看仓库、分析现有实现并修改需求文档，但文档规定只有当用户批准当前需求文档的准确 SHA-256 摘要后，才允许修改产品代码。这是面向守约 Agent 的可审计协作规则，不是安全边界。

## 它会做什么

```text
简单功能描述
    -> 根据仓库证据分析项目
    -> 生成 .feature-agent/requirement.md
    -> 按用户要求局部修改需求
    -> 用户批准当前需求摘要
    -> 实现功能
    -> 使用仓库已有命令编译和测试
    -> 启动本地或 Docker 开发环境
    -> Agent 自行冒烟测试
    -> 返回环境验收回执
```

这个流程面向个人开发者落地范围清晰的新功能。需求文档保持轻量，审批可以审计，执行证据保存在目标项目中，不依赖 Agent 是否还记得之前的对话。

## 它不会做什么

- 不处理 Bug 修复、线上故障或生产环境部署。
- 不代替产品调研、架构评审、安全评审和人工 QA。
- 不对接 Jira，也不依赖 Jenkins、托管服务或专用 UI。
- 不自动提交、推送、合并、发布或部署到生产环境。
- 不猜测编译命令，也不会在没有证据时声称成功。

## 审批门禁

需求文档具有内容摘要。用户的批准只对 Agent 展示的那个准确摘要有效；批准后再次修改需求文档会改变摘要，原批准随即失效。

这个门禁保留了“先校对需求，再开发已批准范围”的产品流程，并留下可审计的批准记录。它不是沙箱、访问控制、数字签名、用户身份凭证或授权令牌。SHA-256 只能标识文档字节，不能证明操作安全，也不会授予执行权限。已经拥有文件系统或工具权限的恶意、被入侵、配置错误或不遵守指令的 Agent，仍可能绕过辅助脚本直接修改代码。如果需要真正的安全边界，应另外使用宿主权限、沙箱、隔离检出目录、分支保护和代码评审等独立强制措施。

批准之前，工作流只能：

- 读取仓库；
- 从已有文件中识别项目命令；
- 创建或修改 `.feature-agent/requirement.md`；
- 说明范围、验收条件、假设和风险。

只有批准后，工作流才允许修改产品代码、安装依赖、编译、测试或启动环境。破坏性操作、提权操作、网络访问和生产相关操作仍然受宿主 Agent 的权限控制以及用户指令约束；需求摘要的批准本身并不代表用户批准了这些操作。

## 支持的仓库

内置项目探测器可以识别以下项目证据：

- Node.js；
- Python；
- Rust；
- Go；
- 使用 Maven 或 Gradle 的 Java 项目；
- 使用 Make 的项目；
- Docker 和 Docker Compose 项目。

项目识别以证据为准。只有目标仓库中已经存在对应的包清单、锁文件、构建文件或容器配置时，Agent 才会提出相应命令。仓库也可以通过自身文档和 Agent 指令明确提供命令。“检测到”只表示命令有仓库证据，并不表示命令或仓库可信、安全。构建脚本、包管理钩子、Make 目标、测试运行器和可执行文件都能运行任意代码；即使辅助脚本通过参数数组并设置 `shell=False` 调用它们，也仍然如此。识别到项目文件同样不代表本机必然具备对应运行时、凭据、依赖和外部服务。

## 安装

前置条件：

- Codex 或 Claude Code；
- Python 3.10 或更高版本，用于运行内置的确定性辅助脚本；
- Git；
- 目标项目需要的开发工具链；
- 仅当目标项目通过 Docker 运行时才需要 Docker。

### Codex

把 GitHub 仓库注册为 marketplace，然后安装插件：

```bash
codex plugin marketplace add lscee/personal-feature-agent
codex plugin add personal-feature-agent@personal-feature-agent
```

安装后新建一个 Codex 任务，使新 Skill 被正确加载。

### Claude Code

直接从 GitHub 安装：

```bash
claude plugin marketplace add lscee/personal-feature-agent
claude plugin install personal-feature-agent@personal-feature-agent
```

本地开发时，可以克隆仓库后直接加载插件目录：

```bash
git clone https://github.com/lscee/personal-feature-agent.git
cd personal-feature-agent
claude --plugin-dir "$PWD/plugins/personal-feature-agent"
```

在 Windows 上，如果系统没有 `python3` 命令，请使用 `python`。

## 使用方式

进入需要开发功能的目标仓库。在 Codex 中要求使用 `feature-dev` Skill；在 Claude Code 中可以通过 `/personal-feature-agent:feature-dev` 调用插件 Skill。

示例需求：

```text
使用 feature-dev 增加一个 JSON 健康检查接口，返回应用版本和服务状态。
先生成需求文档，在我批准准确的需求摘要之前不要实现。
```

Agent 分析仓库并生成 `.feature-agent/requirement.md`。校对时可以直接提出局部修改：

```text
把验收条件中的接口从 /health 改为 /api/health，其他章节保持不变。
```

文档确认无误后，批准 Agent 返回的准确摘要：

```text
我批准需求 SHA-256 <Agent 返回的摘要>，继续。
```

随后 Agent 才会实现已批准范围，运行检测到的编译和测试命令，在条件允许时启动开发环境，执行冒烟测试并生成环境验收回执。如果环境无法启动或验证，它会返回失败原因和证据，而不是宣称任务已经完成。

## 生成的工件

目标仓库中会生成本地工作目录：

```text
.feature-agent/
├── requirement.md          # 已校对的新功能需求
├── state.json              # 工作流状态与已批准摘要
├── environment.json        # 机器可读的验证结果
├── environment.md          # 便于阅读的环境交付说明
└── runs/                   # 命令输出与执行证据
```

这些工件放在代码旁边，因此新的会话也能恢复工作流状态。辅助脚本会拒绝这个工作区中的符号链接；在支持有效 POSIX 权限位的文件系统上，目录使用 `0700`、证据文件使用 `0600`。如果证据只需保留在本地，请把 `.feature-agent/` 加入目标仓库的忽略规则；如果需求文档对团队有价值，也可以选择提交其中一部分。应把整个目录视为可能含有敏感信息：命令参数、标准输出和错误输出、本地路径、环境细节及验证 URL 都可能被记录。结构化证据会遮蔽常见秘密参数和 URL 查询值，但无法可靠清洗任意日志。不要把凭据放进提示词、命令行参数或 URL，分享或提交前应逐项检查工件。

## 运行时辅助脚本

通常由 Skill 自动调用这些脚本。维护者或高级用户也可以直接查看状态：

```bash
python3 plugins/personal-feature-agent/skills/feature-dev/scripts/state.py \
  --root /path/to/target-project show

python3 plugins/personal-feature-agent/skills/feature-dev/scripts/detect_project.py \
  --root /path/to/target-project
```

运行时还包含带有工作流检查的命令执行和环境验证辅助脚本。默认拒绝执行无法从仓库证据推导的未知命令；只有明确选择后才允许执行。进入 `built` 会复核当前 build/test 记录，进入 `running` 会绑定一份准确的成功启动结果，进入 `verified` 会再次校验该结果以及可追溯的 HTTP 或测试证据；只手写几个成功字段的回执会被拒绝。这些检查可以降低守约 Agent 误操作的概率，但不会让仓库定义的命令自动变得安全，也不能阻止有能力的 Agent 使用环境中其他可用工具。

## 仓库结构

```text
.
├── .agents/plugins/marketplace.json       # Codex marketplace
├── .claude-plugin/marketplace.json         # Claude Code marketplace
├── plugins/personal-feature-agent/
│   ├── .codex-plugin/plugin.json
│   ├── .claude-plugin/plugin.json
│   └── skills/feature-dev/
│       ├── SKILL.md
│       ├── assets/
│       ├── references/
│       └── scripts/
└── tests/
```

两个平台共享同一套工作流指令、模板和确定性脚本，只有平台清单和安装入口不同。因此不需要维护两个独立 Agent，也能让 Codex 与 Claude Code 的关键行为保持一致。

## 本地验证

在本仓库根目录运行仓库校验和测试：

```bash
make check
```

如果没有 `make`，依次运行 `python3 scripts/check_repo.py` 和 `python3 -m unittest discover -s tests -v`。

运行 `make package` 可以生成独立发布 ZIP，产物位于 `dist/`。

如果本机已经安装 Claude Code，可以验证清单并测试加载：

```bash
claude plugin validate ./plugins/personal-feature-agent --strict
claude --plugin-dir ./plugins/personal-feature-agent
```

测试 Codex 时，添加本地 marketplace 并使用安装后的插件新建任务。请使用可丢弃的示例仓库测试完整流程，不要用生产代码检出目录调试插件。

## 隐私与安全

插件自身不包含 Jira、Jenkins、遥测、分析或外部服务集成。它通过当前环境中的编码 Agent 和本地工具执行工作。不过，Codex 或 Claude Code 的配置、模型提供方、Shell 命令、包管理器和项目依赖仍可能访问网络，或者按照各自条款处理仓库内容。

- 批准前检查需求内容和摘要。
- 不要把密钥写入功能描述或准备提交的 `.feature-agent/` 工件。
- 使用最小权限凭据和可丢弃的开发环境。
- 把仓库定义的安装、编译、测试和启动命令都视为任意代码并在执行前检查；`shell=False` 只能避免 Shell 插值，不能保证被调用程序安全。
- 假设日志、命令参数和验证 URL 可能包含敏感信息；不要在参数和 URL 中放置秘密，分享前检查 `.feature-agent/`。
- 对提权、破坏性或联网命令，执行前检查具体内容。
- 不要在这个工作流中使用生产凭据和生产部署目标。
- 提交或发布前人工审查所有生成代码和执行证据。

漏洞报告方式请参阅 [SECURITY.md](SECURITY.md)。

## 参与贡献

欢迎贡献。提交 Pull Request 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。适合贡献的方向包括：更多项目探测器测试样例、更安全的执行规则、更清晰的需求模板、跨平台测试和文档改进。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
