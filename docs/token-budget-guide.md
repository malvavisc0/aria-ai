# Token Budget & VRAM Configuration Guide

## How the Token Budget Works

Every LLM call has a fixed **context window** — a maximum number of tokens
the model can process at once. This window must accommodate **everything**
in a single request:

```
┌─────────────────────────────────────────────────────────┐
│                    CONTEXT WINDOW                        │
│                                                         │
│  ┌─────────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │   System     │ │  Memory  │ │     Scratchpad       │ │
│  │   Prompt     │ │ (recent  │ │  (tool calls within  │ │
│  │   + Tools    │ │  history │ │   a single agent     │ │
│  │              │ │  buffer  │ │   turn — accumulates │ │
│  │  ~8-12k     │ │  + mem   │ │   tool results)      │ │
│  │  tokens      │ │  blocks) │ │                      │ │
│  └─────────────┘ └──────────┘ └──────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │              Output Reservation (max_tokens)         ││
│  │                    8,192 tokens                      ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Components

| Component | What it is | Typical size | Configurable? |
|---|---|---|---|
| **System prompt** | Agent instructions, tool schemas, runtime extras | 8-12k tokens | Via agent markdown files |
| **Memory** | Recent history buffer + memory blocks (FactExtraction, Vector) | `CHAT_CONTEXT_SIZE × TOKEN_LIMIT_RATIO` | ✅ `TOKEN_LIMIT_RATIO` |
| **Scratchpad** | Tool call results accumulated during a single agent turn | 0 – 50k+ tokens | ❌ No limit (grows during agent loop) |
| **Output** | Tokens reserved for the model's response | 8,192 tokens | `max_tokens` in LLM factory |

### The Key Formula

```
Effective context = GPU-KV-clamped CHAT_CONTEXT_SIZE

Memory token_limit = Effective context × TOKEN_LIMIT_RATIO

Chat history buffer = token_limit × CHAT_HISTORY_TOKEN_RATIO  (~10%)
Memory blocks       = token_limit × (1 - CHAT_HISTORY_TOKEN_RATIO)  (~90%)

Available for scratchpad = Effective context
                         - Memory token_limit
                         - System prompt (~10k)
                         - Output (max_tokens = 8,192)
```

> ⚠️ **`CHAT_CONTEXT_SIZE` is a request, not a guarantee.** vLLM clamps
> it to what the GPU KV cache can hold. A large model (e.g. 30B+ on
> 24 GB VRAM) can collapse `CHAT_CONTEXT_SIZE=262,144` down to
> ~12,000 tokens — shrinking `token_limit` to ~3,000 and the buffer
> to ~300 tokens (less than one message pair). This causes **total
> amnesia**: every turn is flushed to the vector store, and the
> retrieved content is then dropped by truncation on the next turn.
> A startup warning is logged when the clamp exceeds 50%.

### How to Avoid Budget Collapse

| Symptom | Cause | Fix |
|---|---|---|
| Agent forgets the previous turn | `token_limit` < ~3k (GPU clamp) | Use a smaller model, or raise `TOKEN_LIMIT_RATIO` to prioritize memory over scratchpad |
| Buffer < 1 message pair (~500 tok) | `token_limit × CHAT_HISTORY_TOKEN_RATIO` too small | Increase `CHAT_HISTORY_TOKEN_RATIO` to 0.20–0.30, or use a smaller model |
| Retrieved context dropped entirely | Retrieved tokens > `token_limit` → `atruncate()` returns `None` | Ensure `token_limit` comfortably exceeds expected retrieval size (~5k+) |

---

## Embeddings-First Architecture

Aria uses an **embeddings-first** approach to conversation memory. Instead
of keeping large amounts of raw message text in context, it relies on
semantic retrieval:

1. Only the **3-4 most recent interactions** are kept as raw text in the
   chat history buffer (~10% of `token_limit`)
2. Older messages are **immediately flushed** to memory blocks:
   - `FactExtractionMemoryBlock` — extracts key facts from old messages
   - `VectorMemoryBlock` — stores messages in ChromaDB for semantic retrieval
3. On each `aget()`, memory blocks are queried and their content is
   injected as system messages

This means the LLM mostly sees **retrieved context** (facts + vector
matches), not raw conversation history. Old messages are never lost —
they're compressed into facts and vector embeddings.

### Why embeddings-first?

- **Predictable context usage** — the buffer stays small regardless of
  conversation length
- **More room for tool calls** — scratchpad gets ~60% of the context
  window instead of being squeezed by a large history buffer
- **Better long-term recall** — vector retrieval surfaces relevant old
  messages on demand, rather than dumping all recent text

### Configuring the buffer size

The chat history buffer size is controlled by `CHAT_HISTORY_TOKEN_RATIO`
(default `0.10`):

```bash
# In .env
CHAT_HISTORY_TOKEN_RATIO=0.10  # 10% of token_limit → ~3-4 interactions
```

- **Lower ratio** (e.g., 0.05) → Only 1-2 recent interactions kept as
  text — maximum scratchpad room
- **Higher ratio** (e.g., 0.15) → 5-6 recent interactions — slightly
  more immediate context, but less scratchpad room

---

## What is `TOKEN_LIMIT_RATIO`?

This controls how much of the context window is reserved for **Memory**
(the recent history buffer + memory blocks combined). The rest is
available for the system prompt, scratchpad (tool call accumulation),
and output.

- **Higher ratio** (e.g., 0.85) → More total memory budget → More room
  for vector retrieval results and facts
- **Lower ratio** (e.g., 0.50) → Less memory → More scratchpad room
  for complex tool-call loops

### How Memory Works

Memory uses a **waterfall** approach:

1. Recent messages stay in the **chat history buffer** (10% of
   `token_limit`, ~3-4 interactions)
2. When the buffer fills, oldest messages are **flushed to memory blocks**:
   - `FactExtractionMemoryBlock` — extracts key facts from old messages
   - `VectorMemoryBlock` — stores messages in ChromaDB for semantic retrieval
3. On each `aget()`, memory blocks are queried and their content is
   injected as system messages

This means **old messages are never lost** — they're compressed into
facts and vector embeddings. The `token_limit` controls the *total
memory budget*, while `CHAT_HISTORY_TOKEN_RATIO` controls how much of
that goes to raw recent text vs. memory blocks.

---

## VRAM Scenarios

### Understanding VRAM Usage

```
VRAM = Model Weights + KV Cache + Overhead
```

| Component | Description |
|---|---|
| **Model weights** | Fixed cost — depends on model size and quantization |
| **KV cache** | Grows with context size — this is the main variable |
| **Overhead** | CUDA kernels, activations, fragmentation (~1-2 GB) |

**KV cache formula** (approximate):

```
KV cache ≈ 2 × num_layers × num_kv_heads × head_dim × context_size × dtype_bytes
```

For Qwen3.5-9B (GPTQ 4-bit):
- Model weights: **~5.5 GB**
- KV cache per 1k tokens: **~0.5 MB** (with `auto` dtype)
- Overhead: **~1.5 GB**

---

### Scenario 1: 16 GB VRAM

**Recommended model:** Qwen3.5-9B (GPTQ 4-bit)

| Parameter | Value | Notes |
|---|---|---|
| `CHAT_CONTEXT_SIZE` | `131072` | 131k tokens — model's native max |
| `TOKEN_LIMIT_RATIO` | `0.85` | Default — large memory budget |
| `CHAT_HISTORY_TOKEN_RATIO` | `0.10` | Embeddings-first — 3-4 interactions |
| `ARIA_VLLM_GPU_MEMORY_UTILIZATION` | `0.90` | Leave 10% headroom for CUDA |

**Token budget:**

| Component | Tokens | % |
|---|---|---|
| Memory (`token_limit`) | 111,411 | 85% |
| ↳ Chat history buffer | ~11,141 | ~10% of memory |
| ↳ Memory blocks (facts + vectors) | ~100,270 | ~90% of memory |
| System prompt + tools | ~10,000 | 8% |
| Output (`max_tokens`) | 8,192 | 6% |
| **Scratchpad (available)** | **~1,469** | **1%** |

> ⚠️ With `TOKEN_LIMIT_RATIO=0.85`, scratchpad room is very limited.
> For tool-heavy workflows, lower the ratio to `0.50`:
>
> | Component | Tokens | % |
> |---|---|---|
> | Memory (`token_limit`) | 65,536 | 50% |
> | ↳ Chat history buffer | ~6,554 | ~10% of memory |
> | ↳ Memory blocks | ~58,982 | ~90% of memory |
> | System prompt + tools | ~10,000 | 8% |
> | Output (`max_tokens`) | 8,192 | 6% |
> | **Scratchpad (available)** | **~47,344** | **36%** |

**VRAM breakdown:**

| Component | Size |
|---|---|
| Model weights (GPTQ 4-bit) | ~5.5 GB |
| KV cache (131k tokens) | ~6.5 GB |
| Overhead | ~1.5 GB |
| **Total** | **~13.5 GB** ✅ fits in 16 GB |

**What to expect:**
- **3-4 recent interactions** as raw text in context
- Older context retrieved via semantic search (vector embeddings)
- Facts extracted from old messages and injected as system context
- Comfortable room for tool calls (with lower `TOKEN_LIMIT_RATIO`)

---

### Scenario 2: 24 GB VRAM

**Recommended model:** Qwen3.5-9B (GPTQ 4-bit) with extended context

| Parameter | Value | Notes |
|---|---|---|
| `CHAT_CONTEXT_SIZE` | `262144` | 262k tokens — 2× the native max |
| `TOKEN_LIMIT_RATIO` | `0.50` | Balanced — room for memory and scratchpad |
| `CHAT_HISTORY_TOKEN_RATIO` | `0.10` | Embeddings-first — 3-4 interactions |
| `ARIA_VLLM_GPU_MEMORY_UTILIZATION` | `0.92` | Slightly more aggressive |

**Token budget:**

| Component | Tokens | % |
|---|---|---|
| Memory (`token_limit`) | 131,072 | 50% |
| ↳ Chat history buffer | ~13,107 | ~10% of memory |
| ↳ Memory blocks | ~117,965 | ~90% of memory |
| System prompt + tools | ~10,000 | 4% |
| Output (`max_tokens`) | 8,192 | 3% |
| **Scratchpad (available)** | **~112,880** | **43%** |

**VRAM breakdown:**

| Component | Size |
|---|---|
| Model weights (GPTQ 4-bit) | ~5.5 GB |
| KV cache (262k tokens) | ~13.0 GB |
| Overhead | ~1.5 GB |
| **Total** | **~20.0 GB** ✅ fits in 24 GB |

**What to expect:**
- 3-4 recent interactions as raw text, extensive vector retrieval
- Very long conversations without losing context (via embeddings)
- Can handle 10-20 tool calls per agent turn comfortably
- Suitable for extended coding sessions, research, multi-file projects

**Alternative:** Use Qwen3.5-14B (GPTQ 4-bit) with 131k context for
better reasoning at the cost of shorter conversations.

---

### Scenario 3: 32 GB VRAM

**Recommended model:** Qwen3.5-14B (GPTQ 4-bit) with extended context

| Parameter | Value | Notes |
|---|---|---|
| `CHAT_CONTEXT_SIZE` | `262144` | 262k tokens |
| `TOKEN_LIMIT_RATIO` | `0.50` | Balanced |
| `CHAT_HISTORY_TOKEN_RATIO` | `0.10` | Embeddings-first — 3-4 interactions |
| `ARIA_VLLM_GPU_MEMORY_UTILIZATION` | `0.95` | Aggressive — plenty of headroom |

**Token budget:**

| Component | Tokens | % |
|---|---|---|
| Memory (`token_limit`) | 131,072 | 50% |
| ↳ Chat history buffer | ~13,107 | ~10% of memory |
| ↳ Memory blocks | ~117,965 | ~90% of memory |
| System prompt + tools | ~12,000 | 5% |
| Output (`max_tokens`) | 8,192 | 3% |
| **Scratchpad (available)** | **~110,880** | **42%** |

**VRAM breakdown (14B model):**

| Component | Size |
|---|---|
| Model weights (GPTQ 4-bit, 14B) | ~8.5 GB |
| KV cache (262k tokens) | ~16.0 GB |
| Overhead | ~2.0 GB |
| **Total** | **~26.5 GB** ✅ fits in 32 GB |

**What to expect:**
- 3-4 recent interactions as raw text, extensive vector retrieval
- Near-unlimited conversation length with memory block compression
- 14B model provides significantly better reasoning
- Can handle 15-30 tool calls per agent turn
- Suitable for complex multi-agent workflows, large codebases

**Alternative:** Use Qwen3.5-32B (GPTQ 4-bit) with 131k context for
the best reasoning, but shorter conversations.

---

## Quick Reference

| VRAM | Model | Context | `TOKEN_LIMIT_RATIO` | `CHAT_HISTORY_TOKEN_RATIO` | Buffer (interactions) | Scratchpad |
|---|---|---|---|---|---|---|
| 16 GB | 9B GPTQ | 131k | 0.50 | 0.10 | 3-4 | ~47k |
| 24 GB | 9B GPTQ | 262k | 0.50 | 0.10 | 3-4 | ~113k |
| 32 GB | 14B GPTQ | 262k | 0.50 | 0.10 | 3-4 | ~111k |

---

## Tuning Tips

### Maximizing conversation length

1. **Keep `CHAT_HISTORY_TOKEN_RATIO` low** (0.05–0.10) — rely on
   embeddings, not raw text
2. **Increase `CHAT_CONTEXT_SIZE`** — larger context = more total room
   for vector retrieval results
3. **Use `ax knowledge`** for facts worth keeping across sessions
4. **Keep messages concise** — shorter messages = better embeddings

### Maximizing tool-call capacity

1. **Lower `TOKEN_LIMIT_RATIO`** (e.g., 0.50) — less memory budget =
   more scratchpad room
2. **Keep `CHAT_HISTORY_TOKEN_RATIO` at 0.10** — minimal raw text
3. **Use chunked `read_file`** — never dump entire files into context
4. **Convert HTML to markdown** — reduces tokens by 85-90%
5. **Use `search_files` before `read_file`** — find what you need first

### Warning signs

| Symptom | Cause | Fix |
|---|---|---|
| `400: context length exceeded` | Total tokens > model limit | Lower `TOKEN_LIMIT_RATIO` or `CHAT_CONTEXT_SIZE` |
| Agent forgets the previous turn | GPU KV clamp collapsed `token_limit` below ~3k | Use a smaller model so KV cache fits; check startup warning |
| Agent loses old context | `token_limit` too small → retrieved content dropped by `atruncate()` | Increase `token_limit` (smaller model or higher `TOKEN_LIMIT_RATIO`) |
| Agent loops on tool calls | Scratchpad overflow | Lower `MAX_ITERATIONS`, add tool output truncation |
| Slow responses | Context too large for GPU | Lower `CHAT_CONTEXT_SIZE` or use smaller model |

---

## How `CHAT_CONTEXT_SIZE` Interacts with vLLM

The `CHAT_CONTEXT_SIZE` value is passed to vLLM as `--max-model-len`.
vLLM will **clamp** this to the model's actual maximum from `config.json`:

```
.env:  CHAT_CONTEXT_SIZE = 262144
  → vLLM: --max-model-len 262144
  → Model config.json: max_position_embeddings = 131072
  → vLLM clamps to: 131072
```

If you set `CHAT_CONTEXT_SIZE` higher than the model supports, vLLM
will silently cap it. Check the vLLM startup logs for the actual value:

```
INFO: max_model_len = 131072
```

**Always verify** that `CHAT_CONTEXT_SIZE` matches what vLLM actually
uses. A mismatch causes the Memory to overfill (it thinks it has more
room than the model allows).

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `CHAT_CONTEXT_SIZE` | `65536` | Total context window size (passed to vLLM as `--max-model-len`) |
| `TOKEN_LIMIT_RATIO` | `0.85` | Fraction of context window reserved for Memory (history + blocks) |
| `CHAT_HISTORY_TOKEN_RATIO` | `0.10` | Fraction of Memory budget for recent raw messages (~3-4 interactions) |
| `ARIA_VLLM_GPU_MEMORY_UTILIZATION` | `0.90` | vLLM GPU memory fraction |