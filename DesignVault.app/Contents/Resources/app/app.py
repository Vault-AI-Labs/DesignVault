"""DesignVault — Design inspiration curation for AI-assisted development."""

import io
import json
import os
import queue
import shutil
import signal
import socket
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path.home() / ".design-vault"
ITEMS_DIR = DATA_DIR / "items"
COLLECTIONS_FILE = DATA_DIR / "collections.json"
PORT_FILE = DATA_DIR / "port"
ITEMS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory job registry (same pattern as VideoTranscriber)
# ---------------------------------------------------------------------------
jobs: dict[str, queue.Queue] = {}

# ---------------------------------------------------------------------------
# Collections helpers
# ---------------------------------------------------------------------------

def load_collections() -> list:
    if COLLECTIONS_FILE.exists():
        return json.loads(COLLECTIONS_FILE.read_text())
    return []


def save_collections(cols: list):
    COLLECTIONS_FILE.write_text(json.dumps(cols, indent=2))

# ---------------------------------------------------------------------------
# Item helpers
# ---------------------------------------------------------------------------

def load_item(item_id: str) -> dict | None:
    meta = ITEMS_DIR / item_id / "metadata.json"
    if meta.exists():
        return json.loads(meta.read_text())
    return None


def save_item(item_id: str, data: dict):
    meta = ITEMS_DIR / item_id / "metadata.json"
    meta.write_text(json.dumps(data, indent=2))


def load_all_items(collection=None, tag=None, status=None, q=None) -> list:
    items = []
    if not ITEMS_DIR.exists():
        return items
    for d in ITEMS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta = d / "metadata.json"
        if not meta.exists():
            continue
        try:
            item = json.loads(meta.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # Filters
        if collection and collection not in item.get("collection_ids", []):
            continue
        if tag and tag not in item.get("tags", []):
            continue
        if status and item.get("status") != status:
            continue
        if status is None and item.get("status") == "archived":
            continue
        if q:
            q_lower = q.lower()
            searchable = " ".join([
                item.get("title", ""),
                item.get("source_url", ""),
                item.get("notes", ""),
                item.get("page_description", ""),
                " ".join(item.get("tags", [])),
            ]).lower()
            if q_lower not in searchable:
                continue
        item["_mtime"] = meta.stat().st_mtime
        items.append(item)
    items.sort(key=lambda x: (
        0 if x.get("status") == "starred" else 1,
        -x.get("_mtime", 0),
    ))
    for it in items:
        it.pop("_mtime", None)
    return items[:200]

# ---------------------------------------------------------------------------
# Color extraction
# ---------------------------------------------------------------------------

def extract_colors(img_path: Path, n: int = 5) -> list[str]:
    try:
        img = Image.open(img_path).convert("RGB")
        small = img.resize((150, 150))
        quantized = small.quantize(colors=n + 3, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        color_counts = Counter(quantized.getdata())
        most_common = color_counts.most_common(n + 3)
        colors = []
        for idx, _count in most_common:
            r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            colors.append(hex_color)
            if len(colors) >= n:
                break
        return colors
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Thumbnail generation
# ---------------------------------------------------------------------------

def make_thumbnail(src: Path, dst: Path, width: int = 400):
    img = Image.open(src)
    ratio = width / img.width
    new_height = int(img.height * ratio)
    img = img.resize((width, new_height), Image.Resampling.LANCZOS)
    img.convert("RGB").save(dst, "JPEG", quality=85)

# ---------------------------------------------------------------------------
# URL capture (runs in background thread)
# ---------------------------------------------------------------------------

def process_capture(job_id: str, url: str, animate: bool = False):
    q = jobs[job_id]
    item_dir = ITEMS_DIR / job_id
    item_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = item_dir / "screenshot.png"
    thumbnail_path = item_dir / "thumbnail.jpg"
    animation_path = item_dir / "animation.gif"

    try:
        # Step 1: Screenshot
        q.put({"status": "screenshotting", "message": "Taking screenshot..."})
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                try:
                    page.goto(url, wait_until="load", timeout=15000)
                except Exception as e:
                    q.put({"status": "error", "message": f"Failed to load URL: {e}"})
                    browser.close()
                    return
            time.sleep(1)  # let animations settle
            page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title() or ""
            description = ""
            try:
                desc_el = page.locator('meta[name="description"]')
                description = desc_el.get_attribute("content") or ""
            except Exception:
                pass

            # Step 2: Animation (optional)
            has_animation = False
            if animate:
                q.put({"status": "animating", "message": "Recording scroll animation..."})
                try:
                    frames = []
                    page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(0.3)
                    viewport_h = page.viewport_size["height"]
                    for _ in range(20):
                        buf = page.screenshot(type="jpeg", quality=60)
                        frame = Image.open(io.BytesIO(buf))
                        frames.append(frame.copy())
                        page.evaluate(f"window.scrollBy(0, {int(viewport_h * 0.4)})")
                        time.sleep(0.15)
                    if frames:
                        frames[0].save(
                            str(animation_path),
                            save_all=True,
                            append_images=frames[1:],
                            optimize=True,
                            duration=150,
                            loop=0,
                        )
                        has_animation = True
                except Exception:
                    pass  # animation is optional, don't fail the whole capture

            browser.close()

        # Step 3: Thumbnail + colors
        q.put({"status": "processing", "message": "Extracting colors..."})
        make_thumbnail(screenshot_path, thumbnail_path)
        colors = extract_colors(screenshot_path)

        # Step 4: Save metadata
        metadata = {
            "item_id": job_id,
            "title": title or _title_from_url(url),
            "source_url": url,
            "source_type": "url",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": "new",
            "collection_ids": [],
            "tags": [],
            "notes": "",
            "colors": colors,
            "has_animation": has_animation,
            "page_description": description,
        }
        save_item(job_id, metadata)
        q.put({"status": "complete", "message": "Done", "data": metadata})

    except Exception as e:
        q.put({"status": "error", "message": str(e)})


def _title_from_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.hostname or url
    if domain.startswith("www."):
        domain = domain[4:]
    return domain

# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")

# ---------------------------------------------------------------------------
# Routes — Capture & Upload
# ---------------------------------------------------------------------------

@app.route("/api/capture", methods=["POST"])
def capture():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    animate = data.get("animate", False)
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = queue.Queue()
    t = threading.Thread(target=process_capture, args=(job_id, url, animate), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/stream/<job_id>")
def stream(job_id):
    q = jobs.get(job_id)
    if not q:
        return jsonify({"error": "Unknown job"}), 404

    def generate():
        while True:
            try:
                event = q.get(timeout=120)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("complete", "error"):
                    jobs.pop(job_id, None)
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'status': 'heartbeat', 'message': 'Still working...'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    files = request.files.getlist("file")
    results = []
    for f in files:
        if not f.filename:
            continue
        item_id = uuid.uuid4().hex[:8]
        item_dir = ITEMS_DIR / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = item_dir / "screenshot.png"
        thumbnail_path = item_dir / "thumbnail.jpg"
        # Save uploaded image
        img = Image.open(f.stream)
        img.save(str(screenshot_path), "PNG")
        # Generate thumbnail + extract colors
        make_thumbnail(screenshot_path, thumbnail_path)
        colors = extract_colors(screenshot_path)
        metadata = {
            "item_id": item_id,
            "title": Path(f.filename).stem.replace("-", " ").replace("_", " ").title(),
            "source_url": "",
            "source_type": "local",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": "new",
            "collection_ids": [],
            "tags": [],
            "notes": "",
            "colors": colors,
            "has_animation": False,
            "page_description": "",
        }
        save_item(item_id, metadata)
        results.append(metadata)
    return jsonify({"items": results})

# ---------------------------------------------------------------------------
# Routes — Items
# ---------------------------------------------------------------------------

@app.route("/api/items")
def list_items():
    items = load_all_items(
        collection=request.args.get("collection"),
        tag=request.args.get("tag"),
        status=request.args.get("status"),
        q=request.args.get("q"),
    )
    return jsonify(items)


@app.route("/api/items/<item_id>", methods=["GET", "PUT", "DELETE"])
def item_detail(item_id):
    if request.method == "GET":
        item = load_item(item_id)
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item)

    elif request.method == "PUT":
        item = load_item(item_id)
        if not item:
            return jsonify({"error": "Not found"}), 404
        updates = request.get_json()
        for key in ("title", "tags", "notes", "collection_ids", "status"):
            if key in updates:
                item[key] = updates[key]
        if "status" in updates:
            item["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_item(item_id, item)
        return jsonify(item)

    elif request.method == "DELETE":
        item_dir = ITEMS_DIR / item_id
        if item_dir.exists():
            shutil.rmtree(item_dir)
        return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Routes — Files
# ---------------------------------------------------------------------------

@app.route("/api/files/<item_id>/<filename>")
def serve_item_file(item_id, filename):
    safe_name = Path(filename).name
    file_path = ITEMS_DIR / item_id / safe_name
    if not file_path.exists():
        return "", 404
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }.get(file_path.suffix.lower(), "application/octet-stream")
    return send_file(file_path, mimetype=mime)

# ---------------------------------------------------------------------------
# Routes — Collections
# ---------------------------------------------------------------------------

@app.route("/api/collections", methods=["GET", "POST"])
def collections():
    if request.method == "GET":
        return jsonify(load_collections())
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    cols = load_collections()
    col_id = name.lower().replace(" ", "-")
    # Ensure unique ID
    existing_ids = {c["id"] for c in cols}
    base_id = col_id
    counter = 2
    while col_id in existing_ids:
        col_id = f"{base_id}-{counter}"
        counter += 1
    col = {
        "id": col_id,
        "name": name,
        "color": data.get("color", "#6d5acd"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    cols.append(col)
    save_collections(cols)
    return jsonify(col), 201


@app.route("/api/collections/<col_id>", methods=["DELETE"])
def delete_collection(col_id):
    cols = load_collections()
    cols = [c for c in cols if c["id"] != col_id]
    save_collections(cols)
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Routes — Export
# ---------------------------------------------------------------------------

@app.route("/api/export/claude", methods=["POST"])
def export_claude():
    data = request.get_json()
    item_ids = data.get("item_ids", [])
    if not item_ids:
        return jsonify({"error": "No items selected"}), 400

    items = [load_item(iid) for iid in item_ids]
    items = [i for i in items if i]
    if not items:
        return jsonify({"error": "No valid items found"}), 404

    collections = {c["id"]: c["name"] for c in load_collections()}
    lines = [
        "I'm building a website and want you to analyze these design references.",
        "For each item, use the Read tool to view the screenshot at the path shown,",
        "then synthesize a DESIGN.md-style analysis covering: color palette,",
        "typographic hierarchy, layout structure, spacing rhythm, and standout UI patterns.",
        "",
    ]

    for i, item in enumerate(items, 1):
        item_dir = ITEMS_DIR / item["item_id"]
        screenshot = item_dir / "screenshot.png"
        lines.append("---")
        lines.append("")
        lines.append(f"## Reference {i}: {item.get('title', 'Untitled')}")
        if item.get("source_url"):
            lines.append(f"URL: {item['source_url']}")
        col_names = [collections.get(cid, cid) for cid in item.get("collection_ids", [])]
        if col_names:
            lines.append(f"Collection: {', '.join(col_names)}")
        if item.get("tags"):
            lines.append(f"Tags: {', '.join(item['tags'])}")
        lines.append(f"Screenshot: `{screenshot}`")
        lines.append("")
        if item.get("colors"):
            lines.append("Color Palette:")
            for color in item["colors"]:
                lines.append(f"- {color}")
            lines.append("")
        if item.get("notes"):
            lines.append(f"Notes: {item['notes']}")
            lines.append("")

    prompt = "\n".join(lines)
    return jsonify({"prompt": prompt})


@app.route("/api/export/design-md/<col_id>")
def export_design_md(col_id):
    cols = load_collections()
    col = next((c for c in cols if c["id"] == col_id), None)
    col_name = col["name"] if col else col_id

    items = load_all_items(collection=col_id, status="all")
    if not items:
        items = load_all_items(collection=col_id)

    # Cross-collection color analysis
    all_colors = Counter()
    for item in items:
        for c in item.get("colors", []):
            all_colors[c] += 1

    lines = [
        f"# Design System Analysis — {col_name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## Color Palette (cross-collection)",
        "Most frequent colors across all references:",
        "",
    ]
    for color, count in all_colors.most_common(10):
        lines.append(f"- `{color}` (used {count}x)")
    lines.append("")
    lines.append("## References")
    lines.append("")

    for i, item in enumerate(items, 1):
        lines.append(f"### {i}. {item.get('title', 'Untitled')}")
        if item.get("source_url"):
            lines.append(f"**Source:** {item['source_url']}")
        lines.append(f"**Captured:** {item.get('created_at', 'unknown')}")
        if item.get("tags"):
            lines.append(f"**Tags:** {', '.join(item['tags'])}")
        if item.get("colors"):
            lines.append(f"**Colors:** {' '.join('`' + c + '`' for c in item['colors'])}")
        if item.get("notes"):
            lines.append(f"**Notes:** {item['notes']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    buf = io.BytesIO(content.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/markdown",
        as_attachment=True,
        download_name=f"DESIGN-{col_id}.md",
    )

# ---------------------------------------------------------------------------
# Port management + startup (identical to VideoTranscriber)
# ---------------------------------------------------------------------------

def find_port(preferred: int = 7750) -> int:
    for port in range(preferred, preferred + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    # Fallback: OS-assigned
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cleanup(signum=None, frame=None):
    try:
        PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    port = find_port()
    PORT_FILE.write_text(str(port))
    print(f"DesignVault running at http://localhost:{port}")
    import webbrowser
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
