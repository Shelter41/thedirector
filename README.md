<!-- HEADER:START -->
<p align="center">
  <img src="docs/images/thedirector.png" alt="The Director" width="640" />
</p>
<p align="center">
  <h1 align="center">The Director</h1>
</p>
<!-- HEADER:END -->

<p align="center">
  <strong>The Director is a personal knowledge layer that builds and curates a markdown wiki from your email, Slack, and Notion — automatically.</strong><br/>
  Persistent, file-based, and fully local. No vector DB. No graph DB. Just markdown an LLM maintains for you.
</p>

<!-- NAV:START -->
<p align="center">
  <a href="#what-is-the-director">What is it?</a>
  ·
  <a href="#quick-start">Quick start</a>
  ·
  <a href="#how-it-works">How it works</a>
  ·
  <a href="#chat-with-the-director">Chat</a>
  ·
  <a href="#configuration">Config</a>
</p>
<!-- NAV:END -->

<!-- BADGES:START -->
<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square&logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/react-19-7b9cff?style=flat-square&logo=react" alt="React" />
  <img src="https://img.shields.io/badge/llm-Claude%204.6-d97757?style=flat-square&logo=anthropic" alt="Claude" />
  <img src="https://img.shields.io/badge/storage-filesystem-4ade80?style=flat-square" alt="Storage" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License" />
</p>
<!-- BADGES:END -->

<p align="center">
  <em>Inspired by Andrej Karpathy's <a href="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f">LLM Wiki gist</a> — the idea that an LLM should curate a persistent, compounding knowledge base instead of re-deriving answers from scratch every query.</em>
</p>

## Highlights

**🧠 LLM-curated knowledge base:** the wiki is markdown the LLM writes, organizes, and maintains itself — no fixed schemas, no manual tagging.

**📥 Drop-in connectors:** Gmail, Slack, and Notion out of the box. OAuth flows for Gmail and Slack, integration token for Notion. Incremental sync for all three. Add a new source in ~150 lines.

**💸 Cost-tuned by default:** Haiku for triage and writes, Sonnet only for chat synthesis. Per-page source filtering and incremental index updates keep ingestion cheap.

**🤖 Real agent chat:** the Director isn't fed wiki content — it's given the path and three tools (`list_files`, `read_file`, `bash`) and navigates the filesystem like a developer would.

**📁 Single-folder data layout:** `data/raw/` for immutable source messages, `data/knowledgebase/` for the wiki, `data/chats/` for conversation history. Everything is `cat`-able.

**🔁 Incremental everything:** sync cursors are files. Re-running an ingest doesn't refetch what you already have. Deleting a folder triggers a clean re-fetch.


## What is The Director?

The Director is a knowledge management system that follows [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Instead of dumping your data into a vector database or graph database for retrieval, an LLM reads your raw sources and **maintains a persistent markdown wiki** that compounds knowledge over time.

You connect Gmail, Slack, and/or Notion. The Director fetches messages and pages, stores them as JSON in `data/raw/`, and triggers a triage loop. The LLM decides which wiki pages to create or update, then writes them to `data/knowledgebase/`. The LLM picks its own organization — it might use `people/`, `topics/`, `projects/`, or anything else that fits the content.

Then you talk to the Director — a chat agent that has tools (`list_files`, `read_file`, `bash`) and explores the wiki itself to answer your questions.


## Core Concepts

-   **Raw layer (`data/raw/`)**
    Immutable JSON files, one per message. Source-of-truth, dedup by source ID, append-only. Human-inspectable with `cat` and `jq`.

-   **Knowledge layer (`data/knowledgebase/`)**
    Markdown files the LLM writes and maintains. The LLM picks the directory structure and the page templates. Cross-referenced with `[[slug]]` wiki-links.

-   **Conversation layer (`data/chats/`)**
    Each chat thread gets a directory with `meta.json` and `turns.jsonl` — the user's questions, the Director's answers, and every tool call it made. Fully replayable, designed for downstream wiki enhancement.

-   **Two-phase wiki loop**
    Phase 1 (Haiku) triages new raw messages into per-page operations with source-message attribution. Phase 2 (Haiku, configurable) creates and updates pages, seeing only the messages that justified each page.

-   **Agent chat**
    The Director knows the wiki path. It navigates with `list_files`, `read_file`, and a sandboxed `bash` tool. No wiki content is pre-loaded into the prompt — the agent explores like a person would.


## Use Cases

The Director is designed for individuals (and small teams) who want a private, local, queryable memory of their professional life — without giving their data to a third-party SaaS.

-   Personal CRM built from your inbox
-   Founder briefings and weekly review prep
-   Customer-conversation knowledge base for solo consultants
-   Project memory across long-running deals
-   "Who is X?" lookups without searching email
-   Remembering commitments, follow-ups, and context across hundreds of threads
-   Auditable, file-based memory you can grep, version-control, and back up
-   A starting point for your own LLM-curated knowledge base


## Architecture

```
React SPA (Vite)                    CLI (click)
     │                                  │
     ▼                                  │
FastAPI backend ◄───────────────────────┘
     │
┌────┼─────────────┬───────────┬────────────┐
▼    ▼             ▼           ▼            ▼
api  connectors    store       wiki        prompts
├─ oauth   ├─ gmail    ├─ raw     ├─ loop     ├─ triage.md
├─ ingest  ├─ slack    ├─ wiki    ├─ agent    ├─ create_page.md
├─ status  ├─ notion   ├─ chats   ├─ dream    ├─ update_page.md
├─ wiki    └─ base     └─ dreams  ├─ tools    ├─ index.md
├─ chat                           ├─ query    ├─ query.md
├─ chats                          └─ lint     ├─ chat.md
├─ dream                                      └─ dream.md
└─ activity
     │
     ▼
Postgres (OAuth credentials + Notion token)
```

The wiki construction (raw fetch → triage → page writes) runs on Haiku. The chat and dream agent loops use tool-use, with Sonnet for chat synthesis.


## Installation

### Requirements

-   **Python 3.12+**
-   **Node.js 20+** (for the frontend)
-   **Docker + Docker Compose** (for Postgres)
-   **An Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))
-   **Google OAuth credentials** for Gmail (optional, [console.cloud.google.com](https://console.cloud.google.com))
-   **Slack OAuth credentials** (optional, [api.slack.com/apps](https://api.slack.com/apps))
-   **Notion integration token** (optional, [notion.so/my-integrations](https://www.notion.so/my-integrations)) — pasted into the UI, no env var needed


### Install

Clone and set up the Python backend:

```bash
git clone <your-fork-url> thedirector
cd thedirector
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Install the frontend:

```bash
cd frontend
npm install
cd ..
```

Start Postgres:

```bash
docker compose up -d
```

Configure environment variables — copy `.env.example` to `.env` (or create one) and fill in:

```dotenv
DATA_ROOT=./data
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173

DATABASE_URL=postgresql://thedirector:thedirector_dev@localhost:5433/thedirector

# Google OAuth (Gmail) — optional
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Slack OAuth — optional
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=

# Anthropic
ANTHROPIC_API_KEY=
```

**Notion** doesn't need any env variable — you paste the integration token into the UI when you click Connect.

Make sure your Google OAuth client has `http://localhost:8000/auth/gmail/callback` listed as an authorized redirect URI. Same for Slack if you're using it: `http://localhost:8000/auth/slack/callback`.


## Quick Start

Start the backend (in one terminal):

```bash
source .venv/bin/activate
uvicorn thedirector.main:app --reload
```

Start the frontend (in another):

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). On the **Dashboard**:

1. Connect a source:
   - **Gmail**: click *Connect*, complete the OAuth flow
   - **Slack**: click *Connect*, complete the OAuth flow, then `/invite @TheDirector` to the channels you want indexed
   - **Notion**: click *Connect*, paste your integration token, then share each page or database with the integration in Notion (page → ⋯ → *Add connections*)
2. Click an ingest button (e.g. **gmail 7d**, **notion 30d**, or **all 7d**)
3. Watch the **Activity** feed: fetch progress → raw store → triage → page writes
4. Open the **Wiki** tab to browse the pages the Director just created
5. Open the **Chat** tab and ask: *"What's in the wiki?"*

The Director will use `list_files` and `read_file` to explore your wiki, then answer with citations.


## CLI

The same operations are available from the command line:

```bash
# Initialize the data directory
thedirector init

# Fetch and process messages
thedirector ingest --source gmail --days 7
thedirector ingest --source slack --days 30
thedirector ingest --source notion --days 30
thedirector ingest --source all --days 7

# Ask a one-shot question
thedirector query "Who has been working on the Q2 launch?"

# Health-check the wiki for broken links, orphans, stale pages
thedirector lint

# Show counts, last sync, page breakdown
thedirector status
```


## Chat with the Director

The chat is a real **agent loop**, not a RAG retriever. The Director receives:

-   Your message
-   The conversation history
-   The absolute path to your wiki
-   Three tools

The tools are sandboxed to the wiki directory:

| Tool         | Purpose                                                              |
| ------------ | -------------------------------------------------------------------- |
| `list_files` | Walk the wiki to discover what's available.                          |
| `read_file`  | Open a specific markdown page and return its content.                |
| `bash`       | Run any shell command — `grep`, `find`, `wc`, `tree` — within `cwd`. |

The frontend renders each tool call as a collapsible card under the assistant turn, color-coded by tool name. You see exactly what the Director did to answer your question.

Every chat is **persisted**:

```
data/chats/
  {thread_id}/
    meta.json        # id, title, created_at, updated_at, turn_count
    turns.jsonl      # one JSON event per line
```

Conversation history shows up in a sidebar inside the Chat page. Click any past thread to load it back into the chat.


## How It Works

The full pipeline in detail:

```
User clicks "Ingest gmail 7d" (or slack, or notion, or all)
       │
       ▼
FastAPI POST /ingest spawns a background task
       │
       ▼
{Source}Connector.fetch(since_days, last_sync, ...)
       │  reads credentials from Postgres
       │  fetches new items since last_sync (cursor file on disk)
       │  Gmail: skips IDs already on disk (cheap dedup)
       │  Notion: re-fetches edited pages (mutable source)
       │  parses + normalizes to Message dataclass
       ▼
raw_store.write(..., overwrite=mutable)  →  data/raw/{source}/2026-04/{id}.json
       │
       ▼
wiki/loop.py: run()
       │
       │  Phase 1 — Triage (Haiku)
       │    batches of 15 messages
       │    + current index.md for context
       │    → returns operations with source_ids
       │
       │  Phase 2 — Execute (Haiku)
       │    for each unique page operation:
       │      filter messages by source_ids
       │      create or update the page
       │      write to data/knowledgebase/{path}.md
       │
       │  Incremental index update (Haiku)
       │    pass only the touched pages
       │    Haiku merges them into the existing index
       │
       ▼
data/knowledgebase/
  index.md
  log.md
  {whatever directories the LLM chose}/
    {whatever pages the LLM created}.md
```

When you chat:

```
User asks "Who is Alice?"
       │
       ▼
api/chat.py builds system prompt with absolute wiki path
       │
       ▼
wiki/agent.py: run_agent_stream()
       │
       │  loop iteration 1:
       │    Sonnet returns: "let me look" + tool_use(list_files, "people")
       │    → execute, append tool_result
       │
       │  loop iteration 2:
       │    Sonnet returns: tool_use(read_file, "people/alice-chen.md")
       │    → execute, append tool_result
       │
       │  loop iteration 3:
       │    Sonnet returns: "Alice Chen is..." (text only, end_turn)
       │    → done
       │
       ▼
SSE stream to frontend:
  thread → tool_call → tool_result → tool_call → tool_result → delta × N → done
       │
       ▼
Persisted to data/chats/{thread_id}/turns.jsonl
```


## Data Layout

Everything The Director knows about you lives in one folder:

```
data/
├── raw/                              # Ingested source items
│   ├── .cursor                       # Last successful wiki loop run
│   ├── gmail/
│   │   ├── .last_sync                # Per-source incremental sync cursor
│   │   └── 2026-04/
│   │       ├── 19c0929d4c840a90.json
│   │       └── ...
│   ├── slack/
│   │   ├── .last_sync
│   │   └── 2026-04/
│   │       └── 1712345678.123456.json
│   └── notion/                       # Mutable — files are overwritten on edit
│       ├── .last_sync
│       └── 2026-04/
│           └── 1f8a3c9d-...-page-id.json
│
├── knowledgebase/                    # The LLM-curated wiki
│   ├── index.md                      # Auto-generated index
│   ├── log.md                        # Append-only ingestion log
│   └── ... (LLM-chosen structure)
│
├── chats/                            # Persisted conversations
│   └── {thread_id}/
│       ├── meta.json
│       └── turns.jsonl
│
└── dreams/                           # Persisted wiki health-check sessions
    └── {dream_id}/
        ├── meta.json
        ├── events.jsonl
        └── report.md
```

**Note on mutability:** Gmail and Slack messages are immutable — once stored, they never change. Notion pages are *mutable*: when you edit a page in Notion, the next ingest overwrites the corresponding raw file and bumps `ingested_at` so the wiki loop re-processes the page on the next run.

Delete `data/raw/gmail/` and the next ingest re-fetches everything. Delete `data/knowledgebase/` and the next ingest rebuilds the wiki from scratch. Delete `data/chats/` and your conversation history is gone.


## Configuration

All settings are read from `.env`. Defaults are sensible — you only need to set the API keys and OAuth secrets to get started.

| Variable               | Default                       | Description                                       |
| ---------------------- | ----------------------------- | ------------------------------------------------- |
| `DATA_ROOT`            | `./data`                      | Where everything is stored.                       |
| `BACKEND_URL`          | `http://localhost:8000`       | Used in OAuth redirect URIs.                      |
| `FRONTEND_URL`         | `http://localhost:5173`       | CORS origin + post-OAuth redirect target.         |
| `DATABASE_URL`         | `postgresql://...localhost:5433/thedirector` | Postgres connection (OAuth tokens only). |
| `ANTHROPIC_API_KEY`    | _required_                    | Your Claude API key.                              |
| `GOOGLE_CLIENT_ID`     | _required for Gmail_          | Google OAuth client ID.                           |
| `GOOGLE_CLIENT_SECRET` | _required for Gmail_          | Google OAuth client secret.                       |
| `SLACK_CLIENT_ID`      | _optional_                    | Slack OAuth client ID.                            |
| `SLACK_CLIENT_SECRET`  | _optional_                    | Slack OAuth client secret.                        |
| `TRIAGE_MODEL`         | `claude-haiku-4-5-20251001`   | Routes messages → page operations.                |
| `WRITER_MODEL`         | `claude-haiku-4-5-20251001`   | Creates and updates wiki pages.                   |
| `INDEX_MODEL`          | `claude-haiku-4-5-20251001`   | Incremental index updates.                        |
| `QUERY_MODEL`          | `claude-sonnet-4-6`           | Chat agent + one-shot queries.                    |
| `BATCH_SIZE`           | `15`                          | Messages per triage batch.                        |


## Customizing the Prompts

All LLM prompts live as plain markdown files at `thedirector/prompts/`:

```
thedirector/prompts/
├── triage.md          # How the LLM decides what pages to create/update
├── create_page.md     # How new pages are written
├── update_page.md     # How existing pages get merged with new info
├── index.md           # How index.md is regenerated
├── query.md           # One-shot query synthesis
└── chat.md            # The Director's agent persona for chat
```

Edit any of these files and restart the backend (or call `prompts.reload()`) — the change takes effect on the next LLM call. No code changes needed.


## Running Tests

```bash
source .venv/bin/activate
pytest
```


## Project Structure

```
thedirector/
├── pyproject.toml
├── docker-compose.yml          # Postgres only
├── schema.sql                  # credentials + sync_log tables
├── requirements.txt
├── .env                        # Your secrets, not committed
│
├── thedirector/
│   ├── cli.py                  # `thedirector init/ingest/query/lint/status`
│   ├── config.py               # Pydantic settings
│   ├── main.py                 # FastAPI app
│   ├── api/                    # HTTP routes (oauth, ingest, chat, ...)
│   ├── connectors/             # Gmail, Slack, Notion fetchers
│   ├── store/                  # raw, wiki, chats
│   ├── wiki/                   # loop, agent, tools, prompts loader
│   ├── llm/                    # Anthropic client + retry
│   └── prompts/                # The .md prompt files
│
└── frontend/
    └── src/
        ├── App.tsx
        ├── lib/api.ts          # Backend client
        ├── pages/
        │   ├── Dashboard.tsx   # Connections + ingest + activity
        │   ├── Wiki.tsx        # Browse the LLM-curated wiki
        │   ├── Chat.tsx        # Talk to the Director
        │   └── Query.tsx       # One-shot Q&A
        └── components/
            ├── ConnectionCard.tsx
            ├── ActivityFeed.tsx
            └── MarkdownViewer.tsx
```


## Roadmap

-   [ ] More connectors (Notion, Linear, GitHub Issues, calendar)
-   [ ] Wiki diff view + manual edit + git versioning
-   [ ] Chat-driven wiki enhancement: feed past conversations back into the wiki
-   [ ] Tool-use for the Director to *write* to the wiki, not just read it
-   [ ] Scheduled background ingests
-   [ ] Multi-user mode (right now: single-user, single-tenant)


## Inspiration

-   [Andrej Karpathy — LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
-   Vannevar Bush's Memex (1945)
-   Every developer who has ever lost an important detail in their inbox


## Support

Open an issue on GitHub, or fork and make it your own.

**Drop a ⭐ to show support**

---

## License

MIT — see the [LICENSE](LICENSE) file for details.
