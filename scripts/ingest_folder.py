"""Load a whole folder of documents (txt, md, csv, json, log, text PDF) into a company's memory through the app's own endpoint.

    python backend/app.py
    python scripts/ingest_folder.py path/to/folder                      # the demo company, as the guest
    python scripts/ingest_folder.py path/to/folder COMPANY-CODE me@company.com

Each file goes through the same path as a document dropped in the chat: extracted, cut into sections, retained with its name and author.
A cloned GitHub repository of runbooks or reports works the same way: point this at the clone. Pictures are skipped (they need a caption).
"""
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
OK = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".pdf"}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    with httpx.Client(base_url=BASE, timeout=300) as c:
        if len(sys.argv) >= 4:
            tok = c.post("/api/workspace/join", json={"code": sys.argv[2], "email": sys.argv[3]}).json()["token"]
        else:
            tok = c.post("/api/workspace/guest").json()["token"]
        c.headers["Authorization"] = "Bearer " + tok
        have = {d["name"] for d in c.get("/api/docs").json()}
        done = skipped = 0
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in OK or ".git" in f.parts:
                continue
            if f.name in have:
                skipped += 1
                continue
            r = c.post("/api/docs", files={"file": (f.name, f.read_bytes())}, data={"author": "Imported"})
            print("ok  " if r.status_code == 200 else "FAIL", f.relative_to(root), "" if r.status_code == 200 else r.json().get("detail", ""))
            done += r.status_code == 200
        print(f"added {done}, already there {skipped}")


if __name__ == "__main__":
    main()
