# DesignVault

**Capture design inspiration. Feed it to Claude.**

A free, open-source local tool that screenshots any website, extracts its color palette, and organizes everything into a visual gallery you can browse, tag, and export as AI-ready prompts.

---

## Why This Exists

You're browsing the web and spot a landing page with perfect dark mode colors, a hero section that actually looks designed, or an animation that makes you stop scrolling. You bookmark it. Then it sits in a folder you never open.

**DesignVault closes that gap.** Paste a URL, get a full-page screenshot with extracted colors, organize it into collections, and when you're ready to build — hit **"Copy for Claude"** and paste a structured design brief straight into Claude Code or claude.ai.

### Real-World Workflow

1. See a landing page you love (Linear, Stripe, Vercel, anything)
2. Paste the URL into DesignVault
3. It screenshots the page, extracts the color palette, and files it
4. Tag it, add notes, drop it into a collection like "Dark Themes" or "Hero Sections"
5. When you're building, select your references and hit **"Copy for Claude"**
6. Claude reads every screenshot, analyzes the design language, and builds to match
7. Ship something that actually looks designed

## Features

- **URL Capture** — Paste any URL, get a full-page screenshot via headless Chromium
- **Scroll Animations** — Optional GIF recording of the page scrolling (toggle the GIF checkbox)
- **Color Extraction** — Automatic dominant color palette from every screenshot
- **Drag & Drop** — Drop local images directly into the gallery
- **Collections** — Organize into named boards (Hero Sections, Dark Themes, SaaS, etc.)
- **Tags** — Free-form tagging with a filterable tag cloud
- **Masonry Gallery** — Visual-first browsing, Pinterest-style layout
- **Star / Archive** — Lightweight status workflow to keep things tidy
- **Copy for Claude** — One click exports selected items as a structured prompt with screenshot paths, color palettes, and notes
- **DESIGN.md Export** — Download a markdown design system analysis per collection
- **100% Local** — Everything runs on your machine. Nothing leaves your computer.
- **Zero Setup** — Single `uv run` command, no virtual environments, no build step

## Quick Start

### Prerequisites

Install via Homebrew:

```bash
brew install uv
```

Playwright's Chromium browser is installed automatically on first launch.

### Run

```bash
git clone https://github.com/Vault-AI-Labs/DesignVault.git
cd DesignVault
./start.sh
```

Opens at `http://localhost:7750`. Paste a URL and go.

### macOS Desktop App

Double-click `DesignVault.app` in the repo or copy it to `/Applications`. The launcher:

- Finds `uv` wherever it's installed
- Starts the server in the background
- Sniffs the port file to open the correct URL
- If already running, just opens the browser (no duplicate servers)

First launch of an unsigned app: right-click → Open to clear Gatekeeper.

## How It Works

1. **Capture** — Paste a URL → Playwright takes a full-page screenshot (1440×900 viewport, 2× retina)
2. **Thumbnail** — Pillow generates a 400px-wide JPEG thumbnail
3. **Colors** — Pillow quantizes the screenshot to extract the 5 dominant colors
4. **Animation** (optional) — 20 scroll frames stitched into a GIF at 8fps
5. **Organize** — Assign to collections, add tags, write notes
6. **Export** — "Copy for Claude" builds a prompt with verified absolute file paths

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python Flask (single file `app.py`) |
| Frontend | Vanilla HTML/JS (`templates/index.html`), no build step |
| Screenshots | Playwright (headless Chromium) |
| Image processing | Pillow (thumbnails, color extraction, GIF stitching) |
| Dependencies | `uv run --with flask --with pillow --with playwright` (zero venv) |

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Web UI |
| POST | `/api/capture` | Capture URL, returns `job_id` |
| GET | `/api/stream/<job_id>` | SSE processing progress |
| POST | `/api/upload` | Upload local images |
| GET | `/api/items` | List items (filterable by collection, tag, status) |
| GET/PUT/DELETE | `/api/items/<id>` | Single item CRUD |
| GET | `/api/files/<id>/<file>` | Serve screenshot/thumbnail/GIF |
| GET/POST | `/api/collections` | List/create collections |
| DELETE | `/api/collections/<id>` | Delete collection |
| POST | `/api/export/claude` | Generate Claude prompt |
| GET | `/api/export/design-md/<id>` | Download DESIGN.md |

## Project Structure

```
~/.design-vault/                # Runtime data
  ├── port                      # Current port
  ├── collections.json          # Collection definitions
  └── items/<item_id>/          # Persisted results
      ├── metadata.json         # All item data
      ├── screenshot.png        # Full-page screenshot
      ├── thumbnail.jpg         # 400px gallery thumbnail
      └── animation.gif         # Optional scroll recording
```

## Contributing

PRs welcome. Keep it simple — this is a single-file Flask app by design.

## License

MIT

---

Built by [VaultAI](https://vaultai.us)
