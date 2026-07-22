# Aria

A fully local AI agent — vLLM inference, SQLite knowledge base, Chroma memory, no cloud calls.

### Capabilities

| | Capability | Examples |
|---|---|---|
| 🔍 | **Web & research** | Search, browse (headless browser), fetch/download, YouTube transcripts |
| 💹 | **Finance & entertainment** | Stock prices, company info, ticker news, IMDb lookups |
| 🧠 | **Long-term memory** | Persistent knowledge store (SQLite) that survives across sessions |
| 📁 | **Files & code** | Read/write/edit files, run Python in a sandbox, execute shell commands |
| ⚙️ | **Background processes** | Start, monitor, and stop long-running jobs |
| 🎯 | **Worker delegation** | Spawns background worker agents for multi-step tasks, with logs and status |
| 🔒 | **Fully local** | Runs on your GPU via vLLM — nothing leaves your machine |

### Powered by vLLM

Aria runs quantized models (GPTQ/AWQ) locally via [vLLM](https://github.com/vllm-project/vllm) — 8 GB+ VRAM required, no API keys, no cloud.

---

[GitHub](https://github.com/malvavisc0/aria-ai) · Private by default · Runs on your machine