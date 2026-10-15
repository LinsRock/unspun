"""Recover observed public text from the existing local R0 archive, without network calls."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

import feedparser
import trafilatura
from lxml import html

ROOT = Path(__file__).resolve().parent
RESEARCH = ROOT.parent.parent / "research/r0-2026-10-15"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def text_node(node):
    node = copy.deepcopy(node)
    for element in node.xpath(".//script|.//style|.//noscript"):
        element.drop_tree()
    normalized = clean(node.text_content())
    for element in node.iter():
        if element.tag in {"p", "div", "br", "li", "h1", "h2", "h3", "blockquote", "section"}:
            element.text = "\n" + (element.text or "")
            element.tail = "\n" + (element.tail or "")
    paragraphs = [clean(line) for line in node.text_content().splitlines() if clean(line)]
    # Block boundaries may add whitespace, but must never add or omit source characters.
    if re.sub(r"\s+", "", "".join(paragraphs)) != re.sub(r"\s+", "", normalized):
        paragraphs = [normalized]
    return normalized, paragraphs


def prepare(archive, output):
    snapshot_bytes = (RESEARCH / "candidates.json").read_bytes()
    candidates = json.loads(snapshot_bytes)["candidates"]
    observations = json.loads((RESEARCH / "observations.json").read_text())["observations"]
    by_observation = {item["observation_id"]: item for item in observations}
    by_probe = {item["id"]: item for item in observations if item["environment"] == "agent_host"}

    def read_observation(observation):
        raw = (archive / f'{observation["id"]}.body').read_bytes()
        if digest(raw) != observation["sha256"]:
            raise ValueError(f'Archived response fingerprint mismatch: {observation["id"]}')
        return raw

    feed_sources = {
        "C23": ("route-36kr-flashes", 0), "C27": ("route-zhihu-hot", 0),
        "C28": ("route-zhihu-hot", 1), "C31": ("route-fortune", 1),
        "C32": ("route-fortune", 2), "C43": ("route-fortune-business", 0),
    }
    materials = {}
    missing = []
    for candidate in candidates:
        candidate_id = candidate["id"]
        if not candidate["material_sha256"]:
            continue
        try:
            observation = by_observation[candidate["observations"][0]]
            raw = read_observation(observation)
            extraction_observation = observation
            selector = candidate["material_selector"]
            if candidate_id in feed_sources:
                probe, index = feed_sources[candidate_id]
                feed_observation = by_probe[probe]
                extraction_observation = feed_observation
                feed = feedparser.parse(read_observation(feed_observation))
                text, paragraphs = text_node(html.fromstring(feed.entries[index].get("summary", "")))
            elif candidate_id == "C22":
                extraction_observation = by_probe["tencent-curated-api"]
                api = json.loads(read_observation(extraction_observation))
                text = clean(api["data"]["articleList"][0]["video_info"]["desc"])
                paragraphs = [text]
            elif selector == "json.body":
                text, paragraphs = text_node(html.fromstring(json.loads(raw)["body"]))
            elif selector.startswith("//"):
                text, paragraphs = text_node(html.fromstring(raw.decode()).xpath(selector)[0])
            elif candidate_id == "C03":
                text, paragraphs = text_node(html.fromstring(raw.decode()).xpath('//*[@id="detailContent"]')[0])
            elif selector.startswith("trafilatura"):
                text = trafilatura.extract(raw.decode(), include_comments=False) or ""
                paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
            else:
                raise ValueError(f"Unsupported selector: {selector}")
            if digest(text.encode()) != candidate["material_sha256"]:
                raise ValueError(f"Observed text fingerprint mismatch: {candidate_id}")
            materials[candidate_id] = {
                "text": text, "paragraphs": paragraphs, "sha256": digest(text.encode()),
                "observation_id": observation["observation_id"],
                "extraction_observation_id": extraction_observation["observation_id"],
                "extraction_response_sha256": extraction_observation["sha256"],
                "observed_at": observation["observed_at"], "source_url": candidate["url"],
                "material_status": candidate["material_status"],
            }
        except FileNotFoundError:
            missing.append(candidate_id)
    result = {
        "schema_version": "unspun-r0-local-materials-v1",
        "dataset_sha256": digest(snapshot_bytes), "archive_available": archive.is_dir(),
        "materials": materials, "missing_archive_ids": missing,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verified_materials": len(materials), "missing": missing, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "materials.local.json")
    arguments = parser.parse_args()
    prepare(arguments.archive, arguments.output)
