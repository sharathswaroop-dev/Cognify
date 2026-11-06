"""Mechanical checks for the submission rules. Run before pushing or publishing:

    python scripts/check_content.py

Fails (exit 1) if: the banned event-type word appears anywhere in tracked text or commit messages; a secret is tracked;
the article is outside 800-1500 words or misses a required link; the LinkedIn post is over 799 characters, has links or
hashtags in its first two lines, hashtags anywhere but the last line, or the wrong number of hashtags; unreplaced
{{placeholders}} remain.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = "hack" + "athon"   # spelled in two parts so this file does not trip its own check
TEXT_EXT = {".md", ".txt", ".html", ".py", ".json", ".svg", ".bat", ".sh", ".yml", ".yaml", ".example", ".css", ".js"}
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache"}
REQUIRED_LINKS = ["github.com/vectorize-io/hindsight", "hindsight.vectorize.io", "vectorize.io/what-is-agent-memory"]
failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print("FAIL:", msg)


def ok(msg: str) -> None:
    print("ok:  ", msg)


def tracked_files() -> list[Path]:
    # committed files plus new files that are not git-ignored (everything that would be pushed)
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split("\n")
    files = [ROOT / f for f in out if f]
    return files or [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.parts) & SKIP_DIRS)]


files = [f for f in tracked_files() if f.exists()]

# 1) banned word in tracked text and in commit messages
hits = []
for f in files:
    if f.suffix.lower() in TEXT_EXT or f.name.startswith(".env"):
        try:
            if BANNED in f.read_text(encoding="utf-8", errors="ignore").lower():
                hits.append(str(f.relative_to(ROOT)))
        except OSError:
            pass
log = subprocess.run(["git", "log", "--format=%B"], cwd=ROOT, capture_output=True, text=True).stdout.lower()
if BANNED in log:
    hits.append("(git commit messages)")
fail(f"banned word found in: {hits}") if hits else ok("banned event-type word absent from tracked files and commit messages")

# 2) secrets
tracked = {str(f.relative_to(ROOT)).replace("\\", "/") for f in files}
if ".env" in tracked:
    fail(".env is tracked")
leaks = [str(f.relative_to(ROOT)) for f in files if f.suffix.lower() in TEXT_EXT and re.search(
    r"gsk_[A-Za-z0-9]{20,}|hsk_[A-Za-z0-9_]{20,}|BAND_KEY_\w+=\S{10,}", f.read_text(encoding="utf-8", errors="ignore"))]
fail(f"key-shaped strings in: {leaks}") if leaks else ok(".env not tracked, no key-shaped strings in tracked files")

# 3) article
art = ROOT / "docs" / "ARTICLE.md"
if art.exists():
    raw = art.read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    body = re.sub(r"```.*?```", "", body, flags=re.S)  # code does not count as prose
    words = len(re.findall(r"\b[\w'-]+\b", re.sub(r"!\[[^\]]*\]\([^)]*\)|\([^)]*\)", "", body)))
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), "")
    ok(f"article prose is {words} words") if 800 <= words <= 1500 else fail(f"article is {words} words (need 800-1500)")
    ok(f"article title '{title}' is {len(title.split())} words") if 0 < len(title.split()) <= 10 and "hindsight" in title.lower() \
        else fail(f"article title must be at most 10 words and mention Hindsight: '{title}'")
    for link in REQUIRED_LINKS:
        ok(f"article links {link}") if link in raw else fail(f"article is missing link {link}")
    if "```" not in raw:
        fail("article needs at least one code snippet")

# 4) LinkedIn post
post_file = ROOT / "docs" / "LINKEDIN_POST.md"
if post_file.exists():
    m = re.search(r"<!-- POST-START -->\n(.*?)\n<!-- POST-END -->", post_file.read_text(encoding="utf-8"), re.S)
    if not m:
        fail("LinkedIn post markers not found")
    else:
        post = m.group(1).strip()
        lines = post.splitlines()
        ok(f"post is {len(post)} characters") if len(post) < 800 else fail(f"post is {len(post)} characters (limit 799)")
        head = " ".join(lines[:2])
        fail("links or hashtags in the first two lines") if re.search(r"https?://|www\.|\.com|#\w", head) else ok("first two lines are link- and hashtag-free")
        tags = re.findall(r"#\w+", post)
        last = lines[-1]
        fail("hashtags must be on the last line only") if any("#" in l for l in lines[:-1]) else ok("hashtags only on the last line")
        ok(f"{len(tags)} hashtags") if 3 <= len(tags) <= 5 else fail(f"{len(tags)} hashtags (need 3-5)")
        fail("repo link missing from the post") if "github.com/" not in post else ok("repo link present")
        fail("must tag Code.in") if "Code.in" not in post else ok("tags Code.in")
        bullets = sum(1 for l in lines if l.lstrip().startswith(("•", "-", "*")))
        ok(f"{bullets} takeaways") if 3 <= bullets <= 7 else fail(f"{bullets} takeaways (need 3-7)")

# 5) placeholders
left = [str(f.relative_to(ROOT)) for f in files if f.suffix == ".md" and re.search(r"\{\{[A-Z_]+\}\}|EVAL_SECTION", f.read_text(encoding="utf-8", errors="ignore"))]
fail(f"unreplaced placeholders in: {left}") if left else ok("no unreplaced placeholders")

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED")
sys.exit(1 if failures else 0)
