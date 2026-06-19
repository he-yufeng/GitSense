<div align="center">

# GitSense

**Find your next open source contribution, then check whether the repo is worth your PR.**

Tell it your skills → it searches GitHub for open issues you can fix → ranks them by match → scores repos by maintainer responsiveness and PR merge patterns.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/he-yufeng/GitSense/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/GitSense/actions)

**[English](README.md) | [中文](README_CN.md)**

</div>

---

## The Problem

You want to contribute to open source, but finding the right issue is painful. You scroll through hundreds of issues on GitHub, most of which are either claimed, too vague, out of your skill range, or just not worth the effort. By the time you find something decent, you've burned an hour on browsing alone.

**GitSense** does the searching for you. It queries GitHub for open, unassigned issues across thousands of repos, then uses an LLM to rank them by how well they match YOUR specific skills and tell you exactly how to get started.

The new Radar mode answers the next question: is this repo actually worth your PR? It checks public PR history, stale backlog, open-to-merged PR pressure, outsider merge ratio, and maintainer response time before you invest a weekend in a repo that might ignore good work.

## Quick Start

```bash
pip install gitsense-radar
```

```bash
# Find issues matching your skills
gitsense find --skills python,llm,cuda

# Target repos with 500+ stars
gitsense find --skills rust,wasm --stars 500

# Filter by label
gitsense find --skills python --labels bug

# Prefer recently active, low-noise issues
gitsense find --skills python,llm --updated-days 30 --max-comments 10

# Scan a specific repo
gitsense scan vllm-project/vllm --skills python,cuda

# Score repos before spending a weekend on a PR
gitsense radar vllm-project/vllm microsoft/qlib --skills python,llm --out radar.md
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

2. **Filter** — Deduplicates results, skips archived / already-assigned / stale issues by default, and can drop noisy threads with too many comments.

3. **Rank** — Sends the candidates to an LLM along with your skill profile. The LLM scores each issue 1-10 on match quality and provides:
   - Why it's a good match (or not)
   - A concrete hint on how to approach the fix

4. **Display** — Renders ranked results in a clean terminal UI with Rich.

5. **Radar** — Scores target repos from public PR signals: recent merged PRs, open/stale PR backlog, open-to-merged pressure, median merge time, maintainer response time, outside contributor merge ratio, risk flags, and skill fit.

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

# Focus on fresh issues and avoid long unresolved debates
gitsense find --skills python,llm --updated-days 30 --max-comments 10

# Include assigned issues when you are intentionally scanning a repo backlog
gitsense find --skills python --include-assigned
```

### Scan a specific repo

```bash
# List all open unassigned issues
gitsense scan pytorch/pytorch

# Filter by your skills
gitsense scan HKUDS/LightRAG --skills python,rag

# Scan only recently active issues
gitsense scan vllm-project/vllm --skills python,cuda --updated-days 14
```

### Score repos before opening a PR

```bash
# Compare a few target repos
gitsense radar vllm-project/vllm microsoft/qlib MoonshotAI/kimi-cli --skills python,llm

# Use a file, one owner/repo per line
gitsense radar --targets targets.txt --skills python,agents --out radar.md

# Write machine-readable evidence for another script or handoff
gitsense radar --targets targets.txt --skills python,agents --format json --out radar.json

# Treat PRs older than two weeks as stale
gitsense radar stanfordnlp/dspy --stale-days 14
```

Radar is not a prediction oracle. It is a fast triage pass for contributors who care about ROI: recent merge velocity, maintainer response time, stale PR ratio, open-to-merged pressure, outsider-friendliness, and whether the repo matches your skill stack.

### Predict whether an open PR will merge

```bash
# Pass a PR URL...
gitsense predict https://github.com/vllm-project/vllm/pull/12345

# ...or the short owner/repo#number form
gitsense predict vllm-project/vllm#12345
```

`predict` scores a single open PR out of 100 from its public signals — review decision, draft flag, merge conflicts, CI status, diff size, whether it touches tests, and age — and shows the notes behind the score. It is a triage heuristic, not a guarantee.

## Configuration

### GitHub Token (recommended)

Without a token you get 10 requests/minute. With a token, 30/minute:

```bash
export GITHUB_TOKEN=your-github-token
```

### LLM Provider

GitSense uses an OpenAI-compatible API for ranking. Without an API key, it still works — you just don't get skill-match scoring.

```bash
# OpenAI
export OPENAI_API_KEY=your-openai-key

# OpenRouter (100+ models)
export OPENROUTER_API_KEY=your-openrouter-key

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
- [x] Repo radar: assess maintainer responsiveness before you invest time
- [x] PR success prediction: estimate merge probability for a specific draft PR

## Contributing

Contributions welcome. If GitSense helped you find your first open source contribution, that's the best feedback possible.

## Release

Releases are published through GitHub Actions with PyPI Trusted Publishing. No PyPI token is stored in the repository.

Before publishing for the first time, configure a PyPI trusted publisher for:

- project name: `gitsense-radar`
- owner: `he-yufeng`
- repository: `GitSense`
- workflow: `publish.yml`
- environment: `pypi`

Then publish a GitHub release, or run the `Publish` workflow manually. The workflow builds the package, runs `twine check`, and uploads the verified artifacts to PyPI.

## License

[MIT](LICENSE)

---

<div align="center">

**If GitSense helped you find a good issue to work on, give it a star!**

[Report a Bug](https://github.com/he-yufeng/GitSense/issues) · [Request a Feature](https://github.com/he-yufeng/GitSense/issues)

</div>
