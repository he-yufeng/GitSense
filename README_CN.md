<div align="center">

# GitSense

**AI 驱动的开源贡献机会发现器。**

输入你的技术栈 → 在 GitHub 全站搜索你能修的 issue → 按匹配度排序，告诉你怎么下手。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/he-yufeng/GitSense/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/GitSense/actions)

**[English](README.md) | [中文](README_CN.md)**

</div>

---

## 痛点

想给开源项目贡献代码，但找 issue 太痛苦了。翻几百个 issue，大部分要么被认领了，要么描述不清，要么超出你的能力范围。找一个靠谱的 issue 往往就花掉一个小时。

**GitSense** 帮你搜。它在 GitHub 全站搜索未认领的 open issue，然后用 LLM 按照你的技术栈匹配度排序，直接告诉你怎么上手。

## 快速上手

```bash
pip install gitsense
```

```bash
# 按技术栈找 issue
gitsense find --skills python,llm,cuda

# 只看 500 star 以上的仓库
gitsense find --skills rust,wasm --stars 500

# 只看 bug 标签
gitsense find --skills python --labels bug

# 优先看近期活跃、讨论噪声低的问题
gitsense find --skills python,llm --updated-days 30 --max-comments 10

# 扫描某个特定仓库
gitsense scan vllm-project/vllm --skills python,cuda
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

1. **搜索** — 根据你的技术栈构造 GitHub 搜索语句（如 `python is:issue is:open no:assignee stars:>=100`），在全站搜索，不限于你 follow 的仓库。

2. **过滤** — 去重，默认跳过归档、已认领和长期未更新的问题，也可以过滤评论过多的高噪声讨论串。

3. **排序** — 把候选列表和你的技能一起发给 LLM。LLM 给每个 issue 打 1-10 的匹配分，并解释为什么匹配、怎么上手。

4. **展示** — 用 Rich 在终端输出排序结果。

## 用法详解

### 全站搜索

```bash
# 基本用法
gitsense find --skills python,fastapi,postgres

# 只看高 star 仓库
gitsense find --skills go,kubernetes --stars 5000

# 只看 bug
gitsense find --skills typescript,react --labels bug

# 跳过 LLM 排序（更快，只看原始结果）
gitsense find --skills python --no-llm

# 指定模型
gitsense find --skills python --model anthropic/claude-sonnet-4

# 显示更多结果
gitsense find --skills python --limit 15

# 聚焦近期活跃的问题，避开长期争论串
gitsense find --skills python,llm --updated-days 30 --max-comments 10

# 主动扫描 backlog 时，也可以包含已认领 issue
gitsense find --skills python --include-assigned
```

### 扫描特定仓库

```bash
# 列出所有未认领的 open issue
gitsense scan pytorch/pytorch

# 按技术栈过滤
gitsense scan HKUDS/LightRAG --skills python,rag

# 只看最近活跃的问题
gitsense scan vllm-project/vllm --skills python,cuda --updated-days 14
```

## 配置

### GitHub Token（推荐）

没有 token 每分钟只能搜 10 次，有 token 可以 30 次：

```bash
export GITHUB_TOKEN=ghp_...
```

### LLM 服务

GitSense 用 OpenAI 兼容接口做排序。没有 API key 也能用，只是没有匹配度打分。

```bash
# OpenAI
export OPENAI_API_KEY=sk-...

# OpenRouter（100+ 模型）
export OPENROUTER_API_KEY=sk-or-...

# 本地模型（Ollama）
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
```

## 适合谁用

- **想积累开源经历的开发者** — 找高 star 仓库里匹配你技能的 issue，让贡献被看到
- **针对特定公司的求职者** — `gitsense scan microsoft/autogen --skills python,agents` 找目标公司仓库的 issue
- **Hackathon 参赛者** — 快速找到几小时能修完的 bug
- **想找有趣挑战的资深开发者** — 发现整个生态里匹配你专长的问题

## 常见问题

**这能替代手动看 issue 吗？**
不能。GitSense 是第一道筛选，省去你翻几百个 issue 的时间。提 PR 之前你还是要认真看 issue 讨论和代码。

**LLM 排序准吗？**
LLM 擅长从 issue 描述里判断关键词匹配和复杂度。它不能告诉你维护者会不会 merge 你的 PR，也不了解代码库结构。当作智能排序用，不是万能预言机。

**要花钱吗？**
GitHub 搜索免费（无 token 有限流）。LLM 排序看你用什么模型，gpt-4o-mini 大概每次搜索 $0.001-0.01。用 `--no-llm` 可以完全跳过排序。

## 路线图

- [ ] 个人主页模式：读你的 GitHub profile 自动检测技能
- [ ] 订阅模式：每天/每周推送新的匹配 issue
- [ ] PR 成功率预测：根据仓库历史估计 merge 概率
- [ ] 仓库健康检查：提 PR 之前评估维护者活跃度

## 贡献

欢迎贡献。如果 GitSense 帮你找到了第一个开源贡献机会，这就是最好的反馈。

## 许可证

[MIT](LICENSE)

---

<div align="center">

**如果 GitSense 帮你找到了好 issue，给个 star！**

[报告问题](https://github.com/he-yufeng/GitSense/issues) · [功能建议](https://github.com/he-yufeng/GitSense/issues)

</div>
