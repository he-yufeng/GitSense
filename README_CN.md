<div align="center">

<img src="docs/banner.png" alt="GitSense — 找到你的下一个开源贡献" width="100%">

输入你的技术栈 → 全站搜索你能修的 issue → 按匹配度排序 → 再用 PR 历史评估仓库的 review / merge 友好度。

[![PyPI](https://img.shields.io/pypi/v/gitsense-radar.svg)](https://pypi.org/project/gitsense-radar/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/he-yufeng/GitSense/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/GitSense/actions)

**[English](README.md) · [中文](README_CN.md)** &nbsp;·&nbsp; [快速上手](#快速上手) · [效果演示](#效果演示) · [工作原理](#工作原理)

</div>

---

## 痛点

想给开源项目贡献代码，但找 issue 太痛苦了。翻几百个 issue，大部分要么被认领了，要么描述不清，要么超出你的能力范围。找一个靠谱的 issue 往往就花掉一个小时。

**GitSense** 帮你搜。它在 GitHub 全站搜索未认领的 open issue，然后用 LLM 按照你的技术栈匹配度排序，直接告诉你怎么上手。

新加入的 Radar 模式解决另一个更现实的问题：这个仓库到底值不值得投 PR？它会看近期 merged PR、积压 PR、超过两周没合的比例、open-to-merged PR 压力、维护者响应时间、外部贡献者合入比例、风险标记和你的技能匹配度，先帮你避开“认真做了但没人 review”的坑。

## 快速上手

```bash
pip install gitsense-radar
```

```bash
# 按技术栈找 issue，LLM 帮你排序
gitsense find --skills python,llm,cuda

# 扫描单个仓库，或提 PR 前先评估仓库
gitsense scan vllm-project/vllm --skills python,cuda
gitsense radar vllm-project/vllm microsoft/qlib --skills python,llm --out radar.md
```

## 效果演示

```bash
$ gitsense find --skills python,llm,cuda --stars 1000
```

```
找到 24 个候选 issue。
正在用 gpt-4o-mini 排序...

╭──────────── GitSense 结果 ────────────╮
│ 技术栈: python, llm, cuda             
│ 结果: 8 个 issue，按匹配度排序        
╰───────────────────────────────────────╯

  1. [9/10] vllm-project/vllm
     Fix CUDA graph memory leak in speculative decoding
     Labels: bug, good first issue
     完美匹配 — 需要 CUDA + Python + LLM 推理知识。
     怎么上手: 看 vllm/spec_decode/worker.py，graph capture
     上下文在异常路径没有释放 GPU 内存。

  2. [8/10] triton-lang/triton
     Type inference fails for constexpr in nested loops
     Labels: bug
     强匹配 — Python 编译器内部，和 GPU kernel 相关。
     怎么上手: 查 code_generator.py visit_For，和 #9547 类似。

  3. [7/10] huggingface/transformers
     ...
```

## 工作原理

![GitSense 流程](docs/architecture.png)

1. **搜索** — 根据你的技术栈构造 GitHub 搜索语句（如 `python is:issue is:open no:assignee stars:>=100`），在全站搜索，不限于你 follow 的仓库。

2. **过滤** — 去重，默认跳过归档、已认领和长期未更新的问题，也可以过滤评论过多的高噪声讨论串。

3. **排序** — 把候选列表和你的技能一起发给 LLM。LLM 给每个 issue 打 1-10 的匹配分，并解释为什么匹配、怎么上手。

4. **展示** — 用 Rich 在终端输出排序结果。

5. **Radar** — 用公开 PR 历史给目标仓库打分：近期合入量、open / stale PR backlog、open-to-merged 压力、中位合入时间、维护者响应时间、外部贡献者合入比例、风险标记、技术栈匹配度。

## 用法详解

```bash
# 全站找 issue，按技能匹配度排序
gitsense find --skills python,fastapi --stars 5000 --labels bug
gitsense find --skills python --no-llm                              # 跳过 LLM 排序（更快）
gitsense find --skills python --model anthropic/claude-sonnet-4 --limit 15

# 也可以让它读你的公开仓库，自动推断你的技能
gitsense profile torvalds
gitsense find --profile torvalds

# 扫描单个仓库里未认领的 open issue
gitsense scan pytorch/pytorch --skills python --updated-days 14

# 提 PR 前评估仓库（Markdown 或 JSON 证据）
gitsense radar vllm-project/vllm microsoft/qlib --skills python,llm --out radar.md
gitsense radar --targets targets.txt --skills python,agents --format json --out radar.json

# 预测某个 open PR 会不会被合（按公开信号打 0-100 分）
gitsense predict vllm-project/vllm#12345

# 盘点你在全站的所有 open PR，最该处理的排最前，每条给出下一步动作
gitsense triage octocat
gitsense triage octocat --shallow            # 只调一次搜索 API，不逐条查详情
gitsense triage octocat --since-last         # 只看和上次盘点相比变了什么
```

`radar` 看近期合入速度、维护者响应时间、stale PR 比例、open-to-merged 压力和外部友好度；`predict` 按某个 PR 的 review 意见、draft/冲突/CI 状态、diff 大小、是否带测试和存活时长打分；`triage` 把同一套打分套到你所有 open PR 上，每条收敛成一个下一步动作（回 review、修 CI、rebase、催合）。都是快速筛查用的启发式，不是保证。

## 配置

### GitHub Token（推荐）

没有 token 每分钟只能搜 10 次，有 token 可以 30 次：

```bash
export GITHUB_TOKEN=your-github-token
```

### LLM 服务

GitSense 用 OpenAI 兼容接口做排序。没有 API key 也能用，只是没有匹配度打分。

```bash
# OpenAI
export OPENAI_API_KEY=your-openai-key

# OpenRouter（100+ 模型）
export OPENROUTER_API_KEY=your-openrouter-key

# 本地模型（Ollama）
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
```

## 常见问题

**这能替代手动看 issue 吗？**
不能。GitSense 是第一道筛选，省去你翻几百个 issue 的时间。提 PR 之前你还是要认真看 issue 讨论和代码。

**LLM 排序准吗？**
LLM 擅长从 issue 描述里判断关键词匹配和复杂度。它不能告诉你维护者会不会 merge 你的 PR，也不了解代码库结构。当作智能排序用，不是万能预言机。

**要花钱吗？**
GitHub 搜索免费（无 token 有限流）。LLM 排序看你用什么模型，gpt-4o-mini 大概每次搜索 $0.001-0.01。用 `--no-llm` 可以完全跳过排序。

## 路线图

**已完成**：Repo Radar（提 PR 前评估维护者活跃度和仓库合入友好度）、PR 成功率预测（针对某个 draft PR 估计合入概率）、个人主页模式（读你的公开仓库推断技能，issue 搜索不用手动说明会什么）、PR 盘点（把你所有 open PR 按紧急度排序，每条给出下一步动作）。

**规划中**：

- **订阅模式**：每天/每周推送匹配你筛选条件的新 issue，让合适的 good first issue 主动找上门，而不用手动重跑。
- **难度校准**：拿 Radar 给出的难度估计和你真正关掉的 issue 对比，用得越久、分数越准。

## 贡献

欢迎贡献。如果 GitSense 帮你找到了第一个开源贡献机会，这就是最好的反馈。

## 相关项目

如果 GitSense 帮你找到了值得做的开源活，这几个我做的工具也许你也用得上：

- **[CoreCoder](https://github.com/he-yufeng/CoreCoder)** — 想真正搞懂一个 coding agent 怎么运作？读完整 ~1000 行引擎，而不是黑箱
- **[RepoWiki](https://github.com/he-yufeng/RepoWiki)** — 被丢进一个陌生代码库？给你一份带「从这里开始读」路径的 wiki（可自托管的 DeepWiki 替代）
- **[FindJobs-Agent](https://github.com/he-yufeng/FindJobs-Agent)** — 别再手刷招聘网站，它按你的简历给岗位排序、还能跑模拟面试
- **[ContractGuard](https://github.com/he-yufeng/ContractGuard)** — 签字前先揪出有风险的条款，自动读合同、标出危险点
- **[CodeABC](https://github.com/he-yufeng/CodeABC)** — 不会写代码也能看懂一个项目，专给小白做的

## 许可证

[MIT](LICENSE)
