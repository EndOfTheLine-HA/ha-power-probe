"""Repository checks: metadata, translations, services, icons and house rules."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from custom_components.power_probe import START_SCHEMA
from custom_components.power_probe.const import (
    DOMAIN,
    PANEL_ELEMENT,
    STATES,
    SUPPORTED_DOMAINS,
    VERSION,
)
from custom_components.power_probe.panel import MODULE_FILE

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / DOMAIN


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_metadata():
    manifest = load(INTEGRATION / "manifest.json")
    hacs = load(ROOT / "hacs.json")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert manifest["domain"] == DOMAIN == "power_probe"
    assert manifest["config_flow"] is True
    assert manifest["single_config_entry"] is True
    assert manifest["requirements"] == []
    assert set(manifest["dependencies"]) == {"http", "panel_custom", "websocket_api"}
    assert manifest["version"] == VERSION
    assert f'version = "{VERSION}"' in pyproject
    assert hacs["homeassistant"] == "2026.10.2"


def test_english_translation_matches_source_strings():
    strings = load(INTEGRATION / "strings.json")
    english = load(INTEGRATION / "translations" / "en.json")
    assert english == strings


def test_services_yaml_matches_strings_and_schema():
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text("utf-8"))
    strings = load(INTEGRATION / "strings.json")["services"]
    assert set(services) == set(strings) == {"start_measurement", "cancel_measurement"}
    fields = set(services["start_measurement"]["fields"])
    assert fields == set(strings["start_measurement"]["fields"])
    assert fields == {str(key) for key in START_SCHEMA.schema}
    picker = services["start_measurement"]["fields"]["entity_id"]
    assert picker["selector"]["entity"]["domain"] == list(SUPPORTED_DOMAINS)


def test_icons_cover_every_translation_key_and_status():
    icons = load(INTEGRATION / "icons.json")
    strings = load(INTEGRATION / "strings.json")
    for platform, keys in icons["entity"].items():
        for key, icon in keys.items():
            assert key in strings["entity"][platform], f"{platform}.{key}"
            assert icon["default"].startswith("mdi:")
    assert set(icons["entity"]["sensor"]["status"]["state"]) == set(STATES)
    assert set(strings["entity"]["sensor"]["status"]["state"]) == set(STATES)
    assert set(icons["services"]) == set(strings["services"])


def test_every_error_code_has_text_in_python_and_in_the_panel():
    """A raised code with no message would show the user a bare key."""
    exceptions = set(load(INTEGRATION / "strings.json")["exceptions"])
    # The config flow's translation keys are for selectors, not errors.
    sources = [p for p in INTEGRATION.glob("*.py") if p.name != "config_flow.py"]
    source = "\n".join(path.read_text("utf-8") for path in sources)
    for code in exceptions:
        assert f'"{code}"' in source, f"{code} is never used"
    raised = set(re.findall(r'ProbeError\(\s*"([a-z_]+)"', source))
    raised |= set(re.findall(r'translation_key="([a-z_]+)"', source))
    raised |= {"command_failed", "unknown"}
    assert raised <= exceptions, raised - exceptions

    script = (INTEGRATION / "frontend" / MODULE_FILE).read_text("utf-8")
    block = script[script.index("const ERRORS") : script.index("const ACTIVITY")]
    in_panel = set(re.findall(r"^\s{2}([a-z_]+):", block, flags=re.MULTILINE))
    # The panel is admin-only and loads after setup, so it never sees this one.
    assert in_panel == exceptions - {"not_set_up"}


def test_panel_script_defines_the_element_the_backend_registers():
    script = (INTEGRATION / "frontend" / MODULE_FILE).read_text("utf-8")
    assert f'customElements.define("{PANEL_ELEMENT}"' in script
    for command in ("info", "start", "cancel", "delete", "subscribe"):
        assert f"{DOMAIN}/{command}" in script


def test_selectors_translate_every_profile():
    from custom_components.power_probe.const import PROFILES

    strings = load(INTEGRATION / "strings.json")
    assert set(strings["selector"]["timing_profile"]["options"]) == set(PROFILES)


# SHA-256 fingerprints of private identifiers (domains, host names, a private
# address prefix) from CJ's own setup. Stored as fingerprints so the check can
# run in public without publishing what it looks for. Each entry is (length in
# characters, hex digest). Same list as the other repos in this organisation.
PRIVATE_FINGERPRINTS = (
    (13, "8fa6e03d9863d3c9e6d6a41afe3be4927193b6189a23dcf4632056257d6f3529"),
    (10, "954dd25e1d8195046f139dfc17136464497396929fdcc4b40e69b173f4297594"),
    (15, "9ddec89909d8dcba13431fcff71969f9ac20736b4a9a4dc1fb05df64e5dd5ba6"),
    (10, "f926d9dafbd8ee102c1fafaf3f291b26a31faca3d8e691333131354ee1a0b44f"),
    (13, "460294b4cf9573b278b690eee05c3aac4dea55eef1a90df4577bd7479d37fbe9"),
    (7, "649b6b6eed65bd13da8bd84faebc193a0a4f49f11a5dbdd1b39bc9e45effcc49"),
    (8, "89717ddba1be520eed9b14a8bacfa507b79608b04b7e1b1360a18183cdab4c1d"),
)
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".toml", ".lock", ".ps1"}
TEXT_SUFFIXES |= {".svg", ".txt", ".js"}
SKIP_DIRS = {".venv", ".git", ".pytest_cache", ".ruff_cache", "__pycache__"}


def repo_text_files():
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIP_DIRS.intersection(path.parts)
    ]


def find_fingerprints(text: str) -> set[int]:
    """Indexes of PRIVATE_FINGERPRINTS that occur anywhere in text."""
    found = set()
    for index, (length, digest) in enumerate(PRIVATE_FINGERPRINTS):
        for start in range(len(text) - length + 1):
            window = text[start : start + length].encode()
            if hashlib.sha256(window).hexdigest() == digest:
                found.add(index)
                break
    return found


def test_fingerprint_check_detects_a_known_value():
    """Guards the guard: a fingerprinted value must be caught."""
    # Assembled at runtime so this file never contains the value whole.
    planted = "prefix " + ".".join(["192", "168", ""]) + " suffix"
    assert find_fingerprints(planted) == {6}
    assert find_fingerprints("nothing private here") == set()


def test_no_private_identifiers():
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in repo_text_files()
    ).lower()
    assert find_fingerprints(text) == set()


def test_no_em_dashes():
    """House rule: no em dashes in code, docs or strings."""
    dash = chr(0x2014)
    offenders = [
        str(path.relative_to(ROOT))
        for path in repo_text_files()
        if dash in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header, without an imaging library."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_brand_images_are_present_and_the_right_size():
    """HACS and Home Assistant read the icon from the integration's brand folder."""
    brand = INTEGRATION / "brand"
    assert png_size(brand / "icon.png") == (256, 256)
    assert png_size(brand / "icon@2x.png") == (512, 512)
    assert (brand / "icon.svg").read_text(encoding="utf-8").lstrip().startswith("<svg")
