# Git2Skills

<div align="center">

**🚀 代码仓库秒变技能文档 | Transform Git Repos into Skill Docs Instantly**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Cost](https://img.shields.io/badge/cost-~$2%20per%20100%20APIs-green.svg)](#成本优势--cost-advantage)

[English](#english) | [中文](#中文)

</div>

---

## 中文

### 📖 项目简介

**Git2Skills** 是一个智能代码分析工具，能够从 Git 仓库自动提取 API 信息，生成结构化的 Skills 技能文档。采用**规则引擎 + LLM 混合架构**，在保证提取质量的同时，大幅降低 Token 消耗成本（节省 65-70%）。

### ✨ 核心特性

#### 🎯 智能提取
- **完整参数识别**：自动解析 Java Request/DTO 类，提取参数名称、类型、是否必填、位置信息
- **高准确率**：规则引擎置信度达 0.98，确保提取结果准确可靠
- **多维度分析**：同时提取 API 路径、HTTP 方法、描述、错误码等完整信息

#### 💰 成本优化
- **混合架构**：规则引擎处理结构化提取，LLM 负责智能补充和验证
- **智能判断**：高置信度时减少 LLM 调用，降低 Token 消耗
- **透明成本**：中型项目（100个 Controller）仅需 **~$2.22 USD**
- **成本对比**：相比纯 LLM 方案节省 **65-70%** Token

#### 📝 多格式输出
- **Skills JSON**：结构化技能数据，便于程序处理和集成
- **Skills Markdown**：人类友好的文档格式，便于阅读和分享
- **API 清单**：完整的 API 端点列表，包含参数、示例和响应
- **技术文档**：项目概述、架构图、数据模型、集成指南等 9 类文档

#### ⚡ 高效便捷
- **一键分析**：支持 Git URL 或本地路径，自动克隆和分析
- **批量处理**：智能分批处理大型项目，避免超时
- **增量更新**：支持指定时间范围，只分析最近变更的代码

### 🎪 实际案例

#### 某项目测试数据

| 指标 | 数值 |
|------|------|
| 项目类型 | Java Spring Boot 后端服务 |
| 分析文件数 | 100 个 Controller 文件 |
| 提取 API 数 | 133 个完整 API |
| 生成文档数 | 9 类文档（共 378.45 KB）|
| Token 消耗 | 输入: 257,000 / 输出: 96,884 |
| 总成本 | **$2.22 USD** (约 ¥16 CNY) |
| 节省成本 | 相比纯 LLM 方案节省 **$0.36** (14%) |

**生成文档列表**：
- ✅ API 完整清单（89.6 KB）- 包含所有参数详情
- ✅ Skills JSON（195.83 KB）- 134 个可复用技能
- ✅ Skills Markdown（79.51 KB）- 易读的技能文档
- ✅ 项目概述、架构图、数据模型、集成指南等

### 🚀 快速开始

#### 环境要求

- Python 3.8+
- Claude API Key（或其他兼容的 LLM API）
- Git（用于克隆仓库）

#### 安装

```bash
# 克隆项目
git clone https://github.com/mok-cn/Git2Skills.git
cd Git2Skills

# 安装依赖（使用 uv 或 pip）
uv pip install -r requirements.txt
# 或
pip install -r requirements.txt
```

#### 配置

```bash
# 设置 API Key
export ANTHROPIC_API_KEY="your-api-key-here"

# 或在 .env 文件中配置
echo "ANTHROPIC_API_KEY=your-api-key-here" > .env
```

#### 使用方法

**方式 1：分析 Git 仓库**

```bash
python git2skills.py \
  --git-url="https://github.com/mok-cn/your-repo" \
  --output-dir="output" \
  --focus="api" \
  --depth="medium"
```

**方式 2：分析本地项目**

```bash
python git2skills.py \
  --repo-path="/path/to/your/project" \
  --output-dir="output" \
  --focus="api" \
  --depth="medium"
```

**参数说明**：

| 参数 | 说明 | 可选值 |
|------|------|--------|
| `--git-url` | Git 仓库 URL | 任何可访问的 Git URL |
| `--repo-path` | 本地项目路径 | 绝对路径或相对路径 |
| `--output-dir` | 输出目录 | 默认: `output` |
| `--focus` | 分析焦点 | `api`, `architecture`, `business`, `all` |
| `--depth` | 分析深度 | `quick`, `medium`, `deep` |
| `--git-days` | 分析最近 N 天的代码 | 数字（0=全部）|

#### 查看结果

```bash
# 输出目录结构
output/
├── api-inventory.md          # API 完整清单
├── skills/
│   ├── skills.json           # Skills JSON 格式
│   └── skills.md             # Skills Markdown 格式
├── context.md                # 项目概述
├── architecture.md           # 架构文档
├── data-models.md            # 数据模型
├── integration-guide.md      # 集成指南
├── team-info.md              # 团队信息
└── git-branches.md           # Git 分支历史
```

### 📊 成本估算

| 项目规模 | Controller 数 | API 数 | 估算成本 |
|---------|--------------|--------|---------|
| 小型项目 | 20-30 | 120-150 | **$0.65** (¥4.7) |
| 中型项目 | 50-100 | 300-500 | **$2.28** (¥16.4) |
| 大型项目 | 200-300 | 1000-1500 | **$6.45** (¥46.4) |

💡 **成本说明**：
- 基于 Claude Sonnet 3.5 定价（Input: $3/1M tokens, Output: $15/1M tokens）
- 规则引擎 + LLM 混合架构相比纯 LLM 方案节省 **65-70%**
- 详细成本分析见 [成本评估文档](docs/cost_estimation.md)

### 🏆 技术优势

#### 1. 规则引擎 + LLM 混合架构

```
代码文件 → 规则引擎提取（0 成本，高准确）
         ↓
    置信度判断（≥0.80?）
         ↓
    是：LLM 补充验证（低成本）
    否：LLM 完整分析（标准成本）
         ↓
    合并结果 → 生成文档
```

**优势**：
- ✅ 规则引擎处理结构化模式（0 Token 消耗）
- ✅ 高置信度时 LLM 仅做补充（降低 65-70% 成本）
- ✅ 低置信度时 LLM 完整分析（保证质量）
- ✅ 自动选择最优策略，无需人工干预

#### 2. Request/DTO 类解析

自动解析 Java 注解和类定义：

```java
// 自动识别
@PostMapping("/user/save")
public Result save(@RequestBody @Valid UserRequest request) {
    // ...
}

// 自动解析 UserRequest 类
public class UserRequest {
    @ApiModelProperty("用户ID")
    @NotNull(message = "用户ID不能为空")
    private Long userId;

    @ApiModelProperty("用户名称")
    @NotBlank(message = "用户名称不能为空")
    private String userName;
}
```

**提取结果**：
```json
{
  "parameters": [
    {
      "name": "userId",
      "type": "number",
      "required": true,
      "description": "用户ID",
      "in": "body"
    },
    {
      "name": "userName",
      "type": "string",
      "required": true,
      "description": "用户名称",
      "in": "body"
    }
  ]
}
```

#### 3. 智能批量处理

- **自动分批**：大型项目自动分批处理，避免超时
- **上下文传递**：规则引擎结果传递给 LLM，提供先验知识
- **并行优化**：多个批次可并行处理（未来支持）

### 🎯 适用场景

- ✅ **Spring Boot 项目**：完美支持 Spring 注解和 REST 风格
- ✅ **RESTful API 文档化**：自动生成完整的 API 文档
- ✅ **技术债务治理**：快速了解遗留项目的 API 结构
- ✅ **团队知识沉淀**：将代码转化为可复用的 Skills 库
- ✅ **微服务梳理**：批量分析多个微服务的 API
- ✅ **新人上手**：快速了解项目的 API 设计和使用方式

### 🛠️ 技术栈

- **Python 3.8+**：核心开发语言
- **Claude API**：大语言模型支持
- **正则表达式**：规则引擎的核心匹配引擎
- **Git**：仓库克隆和代码获取
- **JSON/Markdown**：输出格式

### 📈 路线图

#### 近期计划（Q1 2026）
- [x] 规则引擎 + LLM 混合架构
- [x] Request/DTO 类自动解析
- [x] Skills JSON + Markdown 输出
- [x] 成本优化和统计
- [ ] 支持更多编程语言（TypeScript, Go）
- [ ] Web UI 界面
- [ ] 批量项目分析
- [ ] 增量更新和缓存机制
- [ ] 多 LLM 支持（OpenAI, Gemini）
- [ ] API 自动测试生成
- [ ] 团队协作和共享功能
- [ ] 企业级部署方案
- [ ] Skills 知识库和搜索
- [ ] CI/CD 集成插件
- [ ] 跨项目 Skills 复用推荐

### 🤝 贡献指南

我们欢迎所有形式的贡献！

#### 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

#### 贡献类型

- 🐛 报告 Bug
- 💡 提出新功能
- 📝 改进文档
- 🧪 添加测试用例
- 🔧 修复问题

### 📄 许可证

本项目采用 Apache2.0 许可证 - 详见 (LICENSE) 文件

### 📞 联系方式

- **项目地址**：https://github.com/mok-cn/Git2Skills
- **问题反馈**：https://github.com/mok-cn/Git2Skills/issues
- **讨论区**：https://github.com/mok-cn/Git2Skills/discussions
- **wechat**：

### 🙏 致谢

感谢以下项目和工具的支持：

- [Anthropic Claude](https://www.anthropic.com/) - 强大的 LLM 支持
- [Python](https://www.python.org/) - 优秀的开发语言
- [Spring Boot](https://spring.io/projects/spring-boot) - 目标框架支持

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！**

Made with ❤️ by Git2Skills Team

</div>

---

## English

### 📖 Introduction

**Git2Skills** is an intelligent code analysis tool that automatically extracts API information from Git repositories and generates structured Skills documentation. Using a **Rule Engine + LLM Hybrid Architecture**, it ensures high-quality extraction while significantly reducing token costs (saving 65-70%).

### ✨ Key Features

#### 🎯 Intelligent Extraction
- **Complete Parameter Recognition**: Automatically parses Java Request/DTO classes to extract parameter names, types, required flags, and location info
- **High Accuracy**: Rule engine achieves 0.98 confidence, ensuring reliable extraction results
- **Multi-dimensional Analysis**: Extracts API paths, HTTP methods, descriptions, error codes, and more

#### 💰 Cost Optimization
- **Hybrid Architecture**: Rule engine handles structured extraction, LLM provides intelligent supplementation and validation
- **Smart Judgment**: Reduces LLM calls when confidence is high, lowering token consumption
- **Transparent Costs**: Medium projects (100 Controllers) cost only **~$2.22 USD**
- **Cost Comparison**: Saves **65-70%** tokens compared to pure LLM solutions

#### 📝 Multi-format Output
- **Skills JSON**: Structured skill data for programmatic processing and integration
- **Skills Markdown**: Human-friendly documentation format for reading and sharing
- **API Inventory**: Complete API endpoint list with parameters, examples, and responses
- **Technical Docs**: 9 types of documents including project overview, architecture, data models, integration guide, etc.

#### ⚡ Efficient & Convenient
- **One-click Analysis**: Supports Git URL or local path, automatic cloning and analysis
- **Batch Processing**: Intelligently batches large projects to avoid timeouts
- **Incremental Updates**: Supports time range specification to analyze only recent changes

### 🎪 Real-world Example

#### Wildgoose Project Test Data

| Metric | Value |
|--------|-------|
| Project Type | Java Spring Boot Backend Service |
| Files Analyzed | 100 Controller files |
| APIs Extracted | 133 complete APIs |
| Documents Generated | 9 types (378.45 KB total) |
| Token Usage | Input: 257,000 / Output: 96,884 |
| Total Cost | **$2.22 USD** (~¥16 CNY) |
| Cost Savings | **$0.36** (14%) vs pure LLM |

**Generated Documents**:
- ✅ Complete API Inventory (89.6 KB) - with all parameter details
- ✅ Skills JSON (195.83 KB) - 134 reusable skills
- ✅ Skills Markdown (79.51 KB) - readable skill documentation
- ✅ Project overview, architecture, data models, integration guide, etc.

### 🚀 Quick Start

#### Prerequisites

- Python 3.8+
- Claude API Key (or other compatible LLM API)
- Git (for repository cloning)

#### Installation

```bash
# Clone the project
git clone https://github.com/mok-cn/Git2Skills.git
cd Git2Skills

# Install dependencies (using uv or pip)
uv pip install -r requirements.txt
# or
pip install -r requirements.txt
```

#### Configuration

```bash
# Set API Key
export ANTHROPIC_API_KEY="your-api-key-here"

# Or configure in .env file
echo "ANTHROPIC_API_KEY=your-api-key-here" > .env
```

#### Usage

**Method 1: Analyze Git Repository**

```bash
python git2skills.py \
  --git-url="https://github.com/mok-cn/your-repo" \
  --output-dir="output" \
  --focus="api" \
  --depth="medium"
```

**Method 2: Analyze Local Project**

```bash
python git2skills.py \
  --repo-path="/path/to/your/project" \
  --output-dir="output" \
  --focus="api" \
  --depth="medium"
```

**Parameter Descriptions**:

| Parameter | Description | Options |
|-----------|-------------|---------|
| `--git-url` | Git repository URL | Any accessible Git URL |
| `--repo-path` | Local project path | Absolute or relative path |
| `--output-dir` | Output directory | Default: `output` |
| `--focus` | Analysis focus | `api`, `architecture`, `business`, `all` |
| `--depth` | Analysis depth | `quick`, `medium`, `deep` |
| `--git-days` | Analyze code from last N days | Number (0=all) |

#### View Results

```bash
# Output directory structure
output/
├── api-inventory.md          # Complete API inventory
├── skills/
│   ├── skills.json           # Skills in JSON format
│   └── skills.md             # Skills in Markdown format
├── context.md                # Project overview
├── architecture.md           # Architecture documentation
├── data-models.md            # Data models
├── integration-guide.md      # Integration guide
├── team-info.md              # Team information
└── git-branches.md           # Git branch history
```

### 📊 Cost Estimation

| Project Size | Controllers | APIs | Estimated Cost |
|--------------|-------------|------|----------------|
| Small | 20-30 | 120-150 | **$0.65** (¥4.7) |
| Medium | 50-100 | 300-500 | **$2.28** (¥16.4) |
| Large | 200-300 | 1000-1500 | **$6.45** (¥46.4) |

💡 **Cost Notes**:
- Based on Claude Sonnet 3.5 pricing (Input: $3/1M tokens, Output: $15/1M tokens)
- Rule engine + LLM hybrid saves **65-70%** compared to pure LLM solutions
- Detailed cost analysis in [Cost Estimation Doc](docs/cost_estimation.md)

### 🏆 Technical Advantages

#### 1. Rule Engine + LLM Hybrid Architecture

```
Code Files → Rule Engine Extraction (0 cost, high accuracy)
           ↓
    Confidence Check (≥0.80?)
           ↓
    Yes: LLM Supplement (low cost)
    No: LLM Full Analysis (standard cost)
           ↓
    Merge Results → Generate Docs
```

**Benefits**:
- ✅ Rule engine handles structured patterns (0 token consumption)
- ✅ LLM only supplements when high confidence (65-70% cost reduction)
- ✅ LLM full analysis when low confidence (ensures quality)
- ✅ Automatic strategy selection, no manual intervention needed

#### 2. Request/DTO Class Parsing

Automatically parses Java annotations and class definitions:

```java
// Automatically recognized
@PostMapping("/user/save")
public Result save(@RequestBody @Valid UserRequest request) {
    // ...
}

// Automatically parses UserRequest class
public class UserRequest {
    @ApiModelProperty("User ID")
    @NotNull(message = "User ID cannot be null")
    private Long userId;

    @ApiModelProperty("User Name")
    @NotBlank(message = "User name cannot be blank")
    private String userName;
}
```

**Extraction Result**:
```json
{
  "parameters": [
    {
      "name": "userId",
      "type": "number",
      "required": true,
      "description": "User ID",
      "in": "body"
    },
    {
      "name": "userName",
      "type": "string",
      "required": true,
      "description": "User Name",
      "in": "body"
    }
  ]
}
```

#### 3. Intelligent Batch Processing

- **Auto-batching**: Large projects automatically batched to avoid timeouts
- **Context Passing**: Rule engine results passed to LLM as prior knowledge
- **Parallel Optimization**: Multiple batches can be processed in parallel (future support)

### 🎯 Use Cases

- ✅ **Spring Boot Projects**: Perfect support for Spring annotations and REST style
- ✅ **RESTful API Documentation**: Automatically generate complete API docs
- ✅ **Technical Debt Management**: Quickly understand legacy project API structures
- ✅ **Team Knowledge Repository**: Transform code into reusable Skills library
- ✅ **Microservice Organization**: Batch analyze APIs across multiple microservices
- ✅ **Onboarding**: Help new team members quickly understand API design and usage

### 🛠️ Tech Stack

- **Python 3.8+**: Core development language
- **Claude API**: Large language model support
- **Regular Expressions**: Core matching engine for rule engine
- **Git**: Repository cloning and code retrieval
- **JSON/Markdown**: Output formats

### 📈 Roadmap

#### Near-term (Q1 2026)
- [x] Rule engine + LLM hybrid architecture
- [x] Automatic Request/DTO class parsing
- [x] Skills JSON + Markdown output
- [x] Cost optimization and statistics
- [ ] Support more languages (TypeScript, Go)
- [ ] Web UI interface
- [ ] Batch project analysis
- [ ] Incremental updates and caching mechanism
- [ ] Multi-LLM support (OpenAI, Gemini)
- [ ] Automatic API test generation
- [ ] Team collaboration and sharing features
- [ ] Enterprise deployment solution
- [ ] Skills knowledge base and search
- [ ] CI/CD integration plugins
- [ ] Cross-project Skills reuse recommendations

### 🤝 Contributing

We welcome all forms of contributions!

#### How to Contribute

1. Fork this repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

#### Contribution Types

- 🐛 Report Bugs
- 💡 Propose New Features
- 📝 Improve Documentation
- 🧪 Add Test Cases
- 🔧 Fix Issues

### 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details

### 📞 Contact

- **Project URL**: https://github.com/mok-cn/Git2Skills
- **Issue Tracker**: https://github.com/mok-cn/Git2Skills/issues
- **Discussions**: https://github.com/mok-cn/Git2Skills/discussions
- **Email**: 

### 🙏 Acknowledgments

Thanks to the following projects and tools:

- [Anthropic Claude](https://www.anthropic.com/) - Powerful LLM support
- [Python](https://www.python.org/) - Excellent development language
- [Spring Boot](https://spring.io/projects/spring-boot) - Target framework support

---

<div align="center">

**⭐ If this project helps you, please give us a Star!**

Made with ❤️ by Git2Skills Team

</div>
