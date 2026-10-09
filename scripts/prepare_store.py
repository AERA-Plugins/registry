#!/usr/bin/env python3
"""Prepare optional store metadata without changing signed plugin releases."""
import argparse
import copy
import json
from pathlib import Path
from catalog_tool import ROOT, validate_catalog, sign, verify_signature


def enrich(catalog, source):
    result = copy.deepcopy(catalog)
    for entry in result["plugins"]:
        plugin_id = entry["id"]
        category = source["categories"].get(plugin_id)
        if category is None:
            continue
        template = "font" if plugin_id.startswith("font-") else plugin_id
        store = copy.deepcopy(entry.get("store", {}))
        store["category"] = category
        localized = {}
        for language, descriptions in source["descriptions"].items():
            text = descriptions[template].replace("{font}", entry["name"])
            summary = text.split("\n\n", 1)[0]
            if language == "en":
                store["summary"], store["description"] = summary, text
            else:
                localized[language] = {"summary": summary, "description": text}
        store["localizations"] = localized
        entry["store"] = store
    # Nothing outside the optional store block may change, including manifests,
    # package URLs/hashes, names, versions and their existing localizations.
    original = copy.deepcopy(catalog)
    comparable = copy.deepcopy(result)
    for document in (original, comparable):
        for entry in document["plugins"]:
            entry.pop("store", None)
    if original != comparable:
        raise ValueError("store metadata changed a release field")
    validate_catalog(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--key", type=Path)
    args = parser.parse_args()
    if args.apply and not args.key:
        parser.error("--apply requires --key; unsigned catalogs are never written")
    source = json.loads((ROOT / "store-texts.json").read_text(encoding="utf-8"))
    if source.get("schema") != 1 or "en" not in source.get("descriptions", {}):
        raise ValueError("store-texts.json must contain English source descriptions")
    for name in ("catalog.json", "catalog-v3.json", "catalog-v4.json"):
        path = ROOT / name
        signature_path = path.with_name(path.name + ".sig")
        verify_signature(path.read_bytes(), signature_path.read_bytes())
        result = enrich(json.loads(path.read_text(encoding="utf-8")), source)
        content = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if len(content) > 1024 * 1024:
            raise ValueError("catalog exceeds the limit used by older recoveries")
        if args.apply:
            signature = sign(content, args.key.resolve(strict=True))
            verify_signature(content, signature)
            temporary = path.with_name(path.name + ".new")
            temporary_signature = signature_path.with_name(signature_path.name + ".new")
            temporary.write_bytes(content)
            temporary_signature.write_bytes(signature)
            temporary.replace(path)
            temporary_signature.replace(signature_path)
        print(f"{name}: {len(result['plugins'])} entries, {len(content)} bytes, release fields unchanged")


if __name__ == "__main__":
    main()
