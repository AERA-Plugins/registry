"""Presentation metadata must not change release behavior for older hosts."""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_tool import validate_catalog, verify_signature
from prepare_store import enrich


def legacy_reader(catalog):
    # Frozen schema-1 release-field requirements; unknown fields are ignored.
    assert catalog["schema"] == 1 and len(catalog["plugins"]) <= 64
    for entry in catalog["plugins"]:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", entry["id"])
        assert 0 < len(entry["name"]) <= 80 and entry["version"]
        assert len(entry["description"]) <= 320
        assert entry["manifest_url"].startswith("https://raw.githubusercontent.com/AERA-Plugins/")
        assert entry["signature_url"] == entry["manifest_url"] + ".sig"
        if any(entry.get(field) for field in ("package_url", "package_size", "package_sha256")):
            assert entry["package_url"].startswith("https://github.com/AERA-Plugins/")
            assert 0 < entry["package_size"] <= 513 * 1024 * 1024
            assert re.fullmatch(r"[0-9a-f]{64}", entry["package_sha256"])
        for localization in entry.get("localizations", {}).values():
            assert not set(localization) - {"name", "description"}


class StoreMetadataTest(unittest.TestCase):
    def test_legacy_validation_and_signatures(self):
        for name in ("catalog.json", "catalog-v3.json", "catalog-v4.json"):
            path = ROOT / name
            content = path.read_bytes()
            verify_signature(content, path.with_name(name + ".sig").read_bytes())
            legacy_reader(json.loads(content))
            self.assertLess(len(content), 1024 * 1024)

    def test_only_store_fields_change(self):
        source = json.loads((ROOT / "store-texts.json").read_text())
        self.assertEqual(len(source["descriptions"]), 33)
        for name in ("catalog.json", "catalog-v3.json", "catalog-v4.json"):
            current = json.loads((ROOT / name).read_text())
            original = copy.deepcopy(current)
            for entry in original["plugins"]:
                entry.pop("store", None)
            result = enrich(original, source)
            self.assertEqual(result, current)
            stripped = copy.deepcopy(result)
            for entry in stripped["plugins"]:
                store = entry.pop("store")
                self.assertEqual(len(store["localizations"]), 32)
                for locale, details in store["localizations"].items():
                    self.assertTrue(details["summary"], locale)
                    self.assertIn("\n\n", details["description"], locale)
                    self.assertNotIn("{font}", details["description"], locale)
            self.assertEqual(stripped, original)
            validate_catalog(original)


if __name__ == "__main__":
    unittest.main()
