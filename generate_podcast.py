"""
Daily Dump — Tech Edition
Uses Gemini's built-in Google Search grounding to find today's top tech news,
skips recently covered stories (unless major update), writes a punchy 5-minute
script, converts to MP3 via Edge TTS, updates the GitHub Pages RSS feed.
"""

import os
import json
import hashlib
import datetime
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────
HEADLINES_COUNT   = 5
STORY_MEMORY_DAYS = 3
OUTPUT_DIR        = "output"
FEED_DIR          = "docs"
MEMORY_FILE       = "output/story_memory.json"

PODCAST_TITLE       = "Daily Dump Tech"
PODCAST_DESCRIPTION = "Fast daily tech news. No fluff. Five minutes."
PODCAST_AUTHOR      = "Daily Dump Bot"
PODCAST_BASE_URL    = os.environ.get(
    "PODCAST_BASE_URL", "https://example.github.io/daily-dump-tech"
)
# ─────────────────────────────────────────────────────────────────────────────


# ── STORY MEMORY ─────────────────────────────────────────────────────────────

def story_key(title: str) -> str:
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]


def load_memory() -> dict:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_memory(memory: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def purge_old_memory(memory: dict, days: int = 14) -> dict:
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    return {
        k: v for k, v in memory.items()
        if datetime.date.fromisoformat(v["date"]) >= cutoff
    }


def mark_covered(titles: list, memory: dict) -> dict:
    today = datetime.date.today().isoformat()
    for title in titles:
        memory[story_key(title)] = {"title": title, "date": today}
    return memory


def recent_titles(memory: dict) -> list:
    """Return titles covered within STORY_MEMORY_DAYS for the prompt."""
    cutoff = datetime.date.today() - datetime.timedelta(days=STORY_MEMORY_DAYS)
    return [
        v["title"] for v in memory.values()
        if datetime.date.fromisoformat(v["date"]) >= cutoff
    ]

# ─────────────────────────────────────────────────────────────────────────────


def generate_script_with_search(memory: dict) -> tuple[str, list]:
    """
    Ask Gemini to search for today's top tech stories AND write the script
    in one call, using Google Search grounding for live news.
    Returns (script_text, list_of_story_titles_used).
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    today     = datetime.date.today().strftime("%B %d, %Y")
    skip_list = recent_titles(memory)
    skip_block = ""
    if skip_list:
        skip_block = (
            "\n\nDo NOT cover these stories — they were already covered recently:\n"
            + "\n".join(f"- {t}" for t in skip_list[:20])
            + "\nIf a story on this list has had a MAJOR new development today "
              "(arrest, ruling, product launch, breach, recall), you may include it.\n"
        )

    prompt = f"""Today is {today}.

You are writing a script for a daily audio tech news briefing called Daily Dump Tech.
Use your Google Search tool to find the 5 most important tech news stories from the last 24 hours.
Focus on: AI, software, hardware, big tech companies, startups, cybersecurity, science/space tech.
Avoid: opinion pieces, listicles, evergreen how-to articles.
{skip_block}
After finding the stories, write the full podcast script following these rules exactly:

SCRIPT RULES:
- Style: Fast, punchy news anchor energy. No fluff.
- No filler phrases: no "Let's dive in", "Stay tuned", "Without further ado", "Fascinating"
- Each story: 2-3 tight sentences max
- Write for the ear — short sentences, active voice
- NO bullet points, NO markdown, NO asterisks, NO headers anywhere
- Do NOT name news sources
- Do NOT start sentences with "today" or "here's"
- Target: ~650-750 words (about 5 minutes of audio)

SCRIPT STRUCTURE:
1. One cold-open sentence: date + "five stories in tech"
2. Five stories back to back, 2-3 sentences each, no "story one" or "first up" labels
3. One dry punchy sign-off sentence

After the script, on a new line write:
TITLES: title1 | title2 | title3 | title4 | title5

Write the script now:"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature":     0.7,
            "maxOutputTokens": 1500,
        },
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    full_text = data["candidates"][0]["content"]["parts"][0]["text"]

    # Split script from titles line
    script    = full_text
    titles    = []
    if "TITLES:" in full_text:
        parts  = full_text.rsplit("TITLES:", 1)
        script = parts[0].strip()
        titles = [t.strip() for t in parts[1].strip().split("|") if t.strip()]

    return script, titles


def text_to_speech(script: str, output_path: str) -> bool:
    """Convert script to MP3 using Edge TTS (free, no API key)."""
    try:
        import edge_tts
        import asyncio

        VOICE = "en-US-GuyNeural"
        RATE  = "+15%"

        async def _synth():
            communicate = edge_tts.Communicate(script, VOICE, rate=RATE)
            await communicate.save(output_path)

        asyncio.run(_synth())
        return True
    except Exception as e:
        print(f"  TTS error: {e}")
        return False


def get_mp3_duration_seconds(mp3_path: str) -> int:
    try:
        return max(1, os.path.getsize(mp3_path) // 16000)
    except Exception:
        return 300


def update_rss_feed(mp3_filename: str, title: str, description: str, mp3_path: str):
    os.makedirs(FEED_DIR, exist_ok=True)
    os.makedirs(os.path.join(FEED_DIR, "episodes"), exist_ok=True)
    feed_path = os.path.join(FEED_DIR, "feed.xml")

    mp3_url      = f"{PODCAST_BASE_URL}/episodes/{mp3_filename}"
    mp3_size     = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else 0
    duration_sec = get_mp3_duration_seconds(mp3_path)
    pub_date     = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    new_item = f"""
  <item>
    <title>{title}</title>
    <description>{description}</description>
    <pubDate>{pub_date}</pubDate>
    <enclosure url="{mp3_url}" length="{mp3_size}" type="audio/mpeg"/>
    <itunes:duration>{duration_sec}</itunes:duration>
    <guid isPermaLink="false">{mp3_url}</guid>
  </item>"""

    if os.path.exists(feed_path):
        with open(feed_path, "r", encoding="utf-8") as f:
            existing = f.read()
        updated = existing.replace(
            "  <!-- EPISODES -->", new_item + "\n  <!-- EPISODES -->"
        )
    else:
        updated = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{PODCAST_TITLE}</title>
    <link>{PODCAST_BASE_URL}</link>
    <description>{PODCAST_DESCRIPTION}</description>
    <language>en-us</language>
    <itunes:author>{PODCAST_AUTHOR}</itunes:author>
    <itunes:category text="News"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{PODCAST_BASE_URL}/cover.jpg"/>
    <!-- EPISODES -->
{new_item}
  </channel>
</rss>"""

    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"  RSS feed updated → {feed_path}")
    print(f"  Episode URL: {mp3_url}")


def main():
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    mp3_filename = f"daily-dump-tech-{today_str}.mp3"
    mp3_path     = os.path.join(OUTPUT_DIR, mp3_filename)
    script_path  = os.path.join(OUTPUT_DIR, f"daily-dump-tech-{today_str}.txt")

    print(f"[{today_str}] Loading story memory...")
    memory = load_memory()
    memory = purge_old_memory(memory, days=14)
    print(f"  {len(memory)} stories in memory")
    if memory:
        skipping = recent_titles(memory)
        if skipping:
            print(f"  Will skip {len(skipping)} recently covered stories")

    print(f"[{today_str}] Searching for today's tech news with Gemini...")
    script, titles = generate_script_with_search(memory)
    word_count = len(script.split())
    print(f"  Script: {word_count} words (~{word_count // 130} min)")
    print(f"  Stories found: {len(titles)}")
    for t in titles:
        print(f"    - {t[:70]}")

    with open(script_path, "w") as f:
        f.write(script)
    print(f"  Script saved → {script_path}")

    print(f"[{today_str}] Converting to audio...")
    success = text_to_speech(script, mp3_path)

    if success:
        size_kb = os.path.getsize(mp3_path) // 1024
        print(f"  MP3 saved → {mp3_path} ({size_kb} KB)")

        update_rss_feed(
            mp3_filename,
            title       = f"Daily Dump Tech — {today_str}",
            description = f"Five tech stories for {today_str}.",
            mp3_path    = mp3_path,
        )

        if titles:
            memory = mark_covered(titles, memory)
            save_memory(memory)
            print(f"  Memory updated → {len(memory)} stories tracked")
    else:
        print("  TTS failed — check edge-tts installation")

    print("Done.")


if __name__ == "__main__":
    main()
