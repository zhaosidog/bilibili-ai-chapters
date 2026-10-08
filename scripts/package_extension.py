"""Build a clean ZIP for loading the unpacked browser extension."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "content.css",
    "options.html",
    "options.css",
    "options.js",
    "lib/core.js",
    "README.md",
    "helper/server.py",
    "helper/requirements.txt",
    "helper/start.ps1",
    "helper/README.md",
)


def main() -> None:
    version = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist" / "bilibili-ai-chapters.zip"
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for name in FILES:
                archive.write(ROOT / name, name)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Built {output} (version {version})")


if __name__ == "__main__":
    main()
