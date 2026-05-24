from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "static" / "symbols"
MAP_PATH = OUT_DIR / "symbol-map.json"
API_URL = "https://mtg.fandom.com/api.php?action=parse&page=Numbers_and_symbols&prop=text&format=json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class ImageTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attr_map = {k: (v or "") for k, v in attrs}
        src = attr_map.get("src", "").strip()
        data_src = attr_map.get("data-src", "").strip()
        resolved_src = data_src if data_src else src
        alt = attr_map.get("alt", "").strip()
        if not resolved_src:
            return
        self.images.append(
            {
                "alt": alt,
                "src": resolved_src,
                "data_image_name": attr_map.get("data-image-name", "").strip(),
            }
        )


def fetch_symbol_html() -> str:
    req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["parse"]["text"]["*"]


def clean_filename(stem: str, fallback_index: int) -> str:
    clean = stem.strip().strip("{}")
    clean = clean.replace("/", "_")
    clean = clean.replace(" ", "_")
    clean = re.sub(r"[^A-Za-z0-9_.-]", "", clean)
    clean = clean.strip("._-")
    if not clean:
        return f"symbol_{fallback_index:03d}"
    return clean.lower()


def guess_extension(image: dict[str, str]) -> str:
    data_name = image.get("data_image_name", "")
    if "." in data_name:
        return data_name.rsplit(".", 1)[-1].lower()

    src = image.get("src", "")
    src_path = urllib.parse.urlsplit(src).path
    match = re.search(r"\.([A-Za-z0-9]{2,5})(?:/|$)", src_path)
    if match:
        return match.group(1).lower()
    return "svg"


def extension_from_payload(payload: bytes, content_type: str, fallback: str) -> str:
    ctype = (content_type or "").lower()
    if "image/svg" in ctype:
        return "svg"
    if "image/webp" in ctype:
        return "webp"
    if "image/png" in ctype:
        return "png"
    if "image/jpeg" in ctype:
        return "jpg"
    if payload.startswith(b"<svg") or payload.startswith(b"<?xml"):
        return "svg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "webp"
    if payload.startswith(b"\x89PNG"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return fallback


def normalize_source_url(url: str) -> str:
    # Fandom thumbnail URLs often return WEBP previews regardless of file extension.
    # Stripping transform segments requests the original file revision.
    parsed = urllib.parse.urlsplit(url)
    path = re.sub(r"/scale-to-width-down/\d+", "", parsed.path)
    path = re.sub(r"/smart", "", path)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def fetch_image_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
    return payload, content_type


def unique_symbols(images: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_alt: set[str] = set()
    seen_src: set[str] = set()
    items: list[dict[str, str]] = []

    for image in images:
        src = image.get("src", "")
        alt = image.get("alt", "")
        if not alt:
            continue
        if alt in seen_alt or src in seen_src:
            continue
        seen_alt.add(alt)
        seen_src.add(src)
        items.append(image)

    return items


def download_symbols() -> None:
    html = fetch_symbol_html()

    parser = ImageTagParser()
    parser.feed(html)

    symbols = unique_symbols(parser.images)
    if not symbols:
        raise RuntimeError("No symbol images were found.")

        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    token_map: dict[str, str] = {}

    for idx, symbol in enumerate(symbols, start=1):
        token = symbol["alt"]
        raw_src = symbol["src"]
        src = normalize_source_url(raw_src)
        ext_hint = guess_extension(symbol)
        stem = clean_filename(token, idx)
        payload, content_type = fetch_image_bytes(src)
        ext = extension_from_payload(payload, content_type, ext_hint)

        # Fallback: if we still got a transformed thumbnail, retry unnormalized URL.
        if ext_hint == "svg" and ext == "webp" and src != raw_src:
            payload2, content_type2 = fetch_image_bytes(raw_src)
            ext2 = extension_from_payload(payload2, content_type2, ext_hint)
            if ext2 != "webp":
                payload, content_type, ext = payload2, content_type2, ext2

        filename = f"{stem}.{ext}"
        out_file = OUT_DIR / filename
        out_file.write_bytes(payload)

        token_map[token] = f"/symbols/{filename}"

    MAP_PATH.write_text(json.dumps(token_map, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Saved {len(symbols)} symbols to {OUT_DIR}")
    print(f"Wrote mapping file: {MAP_PATH}")


if __name__ == "__main__":
    download_symbols()
