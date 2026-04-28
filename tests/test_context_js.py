import json
from dia_organizer import context_js


def test_payload_is_one_line():
    js = context_js.PAYLOAD
    assert "\n" not in js


def test_parse_valid_payload():
    raw = json.dumps({
        "metaDesc": "x", "ogTitle": "y", "ogDesc": "z",
        "h1": "head", "selection": "sel", "scrollPct": 42,
        "textSample": "body", "referrer": "ref",
    })
    parsed = context_js.parse(raw)
    assert parsed.meta_desc == "x"
    assert parsed.scroll_pct == 42
    assert parsed.referrer == "ref"


def test_parse_handles_empty():
    parsed = context_js.parse("")
    assert parsed.meta_desc is None
    assert parsed.scroll_pct == 0


def test_parse_handles_garbage():
    parsed = context_js.parse("not json")
    assert parsed.meta_desc is None
