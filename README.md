<div align="center">

# GitSense

**Find your next open source contribution, powered by AI.**

Tell it your skills → it searches GitHub for open issues you can fix → ranks them by match and tells you how to start.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/he-yufeng/GitSense/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/GitSense/actions)

**[English](README.md) | [中文](README_CN.md)**

</div>

---

## The Problem

You want to contribute to open source, but finding the right issue is painful. You scroll through hundreds of issues on GitHub, most of which are either claimed, too vague, out of your skill range, or just not worth the effort. By the time you find something decent, you've burned an hour on browsing alone.

**GitSense** does the searching for you. It queries GitHub for open, unassigned issues across thousands of repos, then uses an LLM to rank them by how well they match YOUR specific skills and tell you exactly how to get started.

## Quick Start

```bash
pip install gitsense
```

```bash
# Find issues matching your skills
gitsense find --skills python,llm,cuda

# Target repos with 500+ stars
gitsense find --skills rust,wasm --stars 500

# Filter by label
gitsense find --skills python --labels bug

# Scan a specific repo
gitsense scan vllm-project/vllm --skills python,cuda
```

## Demo

```bash
$ gitsense find --skills python,llm,cuda --stars 1000
```

```
Found 24 candidates.
Ranking with gpt-4o-mini...

╭──────────── GitSense Results ────────────╮
│ Skills: python, llm, cuda                │
│ Results: 8 issues ranked by match        │
╰──────────────────────────────────────────╯

  1. [9/10] vllm-project/vllm
     Fix CUDA graph memory leak in speculative decoding
     https://github.com/vllm-project/vllm/issues/36200
     Labels: bug, good first issue
     Perfect match — requires CUDA + Python + LLM inference knowledge.
     How to start: Look at vllm/spec_decode/worker.py, the graph
     capture context isn't releasing GPU memory on exception paths.

  2. [8/10] triton-lang/triton
     Type inference fails for constexpr in nested loops
     https://github.com/triton-lang/triton/issues/9650
     Labels: bug
     Strong match — Python compiler internals, related to GPU kernels.
     How to start: Check code_generator.py visit_For, similar to #9547.

  3. [7/10] huggingface/transformers
     ...
```

## How It Works

1. **Search** — Builds targeted GitHub search queries from your skills (e.g. `python is:issue is:open no:assignee stars:>=100`). Searches across all of GitHub, not just repos you follow.

2. **Filter** — Deduplicates results, extracts metadata (repo stars, labels, age, comment count), and prepares a condensed candidate list.

3. **Rank** — Sends the candidates to an LLM along with your skill profile. The LLM scores each issue 1-10 on match quality and provides:
   - Why it's a good match (or not)
   - A concrete hint on how to approach the fix

4. **Display** — Renders ranked results in a clean terminal UI with Rich.

## Usage

### Find across all of GitHub

```bash
# Basic — search by skills
gitsense find --skills python,fastapi,postgres

# High-star repos only
gitsense find --skills go,kubernetes --stars 5000

# Bug fixes only
gitsense find --skills typescript,react --labels bug

# Skip LLM ranking (faster, just raw results)
gitsense find --skills python --no-llm

# Use a specific model
gitsense find --skills python --model anthropic/claude-sonnet-4

# Show more results
gitsense find --skills python --limit 15
```

### Scan a specific repo

```bash
# List all open unassigned issues
gitsense scan pytorch/pytorch

# Filter by your skills
gitsense scan HKUDS/LightRAG --skills python,rag
```

## Configuration

### GitHub Token (recommended)

Without a token you get 10 requests/minute. With a token, 30/minute:

```bash
export GITHUB_TOKEN=ghp_...
```

### LLM Provider

GitSense uses an OpenAI-compatible API for ranking. Without an API key, it still works — you just don't get skill-match scoring.

```bash
# OpenAI
export OPENAI_API_KEY=sk-...

# OpenRouter (100+ models)
export OPENROUTER_API_KEY=sk-or-...

# Local (Ollama)
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
```

## Who Is This For?

- **Developers building their open source resume** — Find high-impact issues in popular repos that match your skills, so your contributions actually get noticed.
- **Job seekers targeting specific companies** — `gitsense scan microsoft/autogen --skills python,agents` to find issues in repos you want on your resume.
- **Hackathon participants** — Quickly find bugs you can fix in a few hours.
- **Experienced developers looking for side projects** — Discover interesting challenges across the ecosystem that match your expertise.

## FAQ

**Does this replace looking at issues manually?**
No. GitSense is a first-pass filter that saves you the time of scrolling through hundreds of issues. You should still read the issue thread and understand the codebase before committing to a contribution.

**How accurate is the LLM ranking?**
The LLM is good at matching keywords and assessing complexity from issue descriptions. It can't tell you whether the maintainers will actually merge your PR or how the codebase is structured. Think of it as a smart sort, not an oracle.

**Does this cost money?**
GitHub search is free (rate-limited without a token). LLM ranking costs whatever your provider charges per call — typically $0.001-0.01 per search with gpt-4o-mini. Use `--no-llm` to skip ranking entirely.

## Roadmap

- [ ] Profile mode: read your GitHub profile to auto-detect skills
- [ ] Watch mode: get daily/weekly digests of new matching issues
- [ ] PR success prediction: estimate merge probability based on repo patterns
- [ ] Repo health check: assess how responsive maintainers are before you invest time

## Contributing

Contributions welcome. If GitSense helped you find your first open source contribution, that's the best feedback possible.

## License

[MIT](LICENSE)

---

<div align="center">

**If GitSense helped you find a good issue to work on, give it a star!**

[Report a Bug](https://github.com/he-yufeng/GitSense/issues) · [Request a Feature](https://github.com/he-yufeng/GitSense/issues)

</div>
