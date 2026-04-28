from dia_organizer import classifier
from dia_organizer.config import Config, ProfileConfig

DAY = 86_400


def _cfg():
    c = Config()
    c.profiles["Keagan"] = ProfileConfig(
        name="Keagan", junk_domains=["youtube.com"], allowlist_domains=["github.com"],
        auto_close_idle_days=14,
    )
    c.profiles["Together User"] = ProfileConfig(
        name="Together User", auto_close_disabled=True,
        allowlist_domains=["togetherplatform.com"],
    )
    return c


def _tab(**kw):
    base = {
        "archive_id": 1, "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://example.com/x", "domain": "example.com",
        "first_seen": 0, "last_seen": 0, "last_focused": None,
        "pinned": False, "selection": None,
    }
    base.update(kw)
    return base


def test_pinned_protected():
    decision = classifier.classify(_tab(pinned=True), [_tab(pinned=True)],
                                    cfg=_cfg(), now=10*DAY)
    assert decision.action == "PROTECT"


def test_allowlist_protected():
    t = _tab(domain="github.com", url="https://github.com/x")
    assert classifier.classify(t, [t], cfg=_cfg(), now=100*DAY).action == "PROTECT"


def test_recent_protected():
    now = 10 * DAY
    t = _tab(first_seen=now - 2 * DAY)
    assert classifier.classify(t, [t], cfg=_cfg(), now=now).action == "PROTECT"


def test_selection_protects():
    t = _tab(first_seen=0, selection="something")
    assert classifier.classify(t, [t], cfg=_cfg(), now=100*DAY).action == "PROTECT"


def test_dedup_closes_older_even_in_protect_window():
    now = 10 * DAY
    older = _tab(archive_id=1, first_seen=now - 1*DAY, last_seen=now - 1*DAY,
                 url="https://a.example/x")
    newer = _tab(archive_id=2, dia_tab_id="t2",
                 first_seen=now - 60, last_seen=now - 60,
                 url="https://a.example/x")
    d_old = classifier.classify(older, [older, newer], cfg=_cfg(), now=now)
    d_new = classifier.classify(newer, [older, newer], cfg=_cfg(), now=now)
    assert d_old.action == "AUTO_CLOSE" and d_old.reason == "auto:dup"
    assert d_new.action == "PROTECT"


def test_blank_tab_auto_close():
    t = _tab(first_seen=20*DAY, last_seen=20*DAY, url="about:blank", domain="")
    assert classifier.classify(t, [t], cfg=_cfg(), now=20*DAY+1).action == "AUTO_CLOSE"


def test_junk_domain_idle():
    now = 30*DAY
    t = _tab(first_seen=now - 10*DAY, last_seen=now - 3*60*60,
             url="https://youtube.com/watch?v=x", domain="youtube.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "AUTO_CLOSE" and d.reason == "auto:junk"


def test_idle_too_long():
    now = 30*DAY
    t = _tab(first_seen=now - 30*DAY, last_seen=now - 20*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "AUTO_CLOSE" and d.reason == "auto:idle"


def test_triage_at_threshold():
    now = 30*DAY
    t = _tab(first_seen=now - 30*DAY, last_seen=now - 6*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "TRIAGE"


def test_keep_otherwise():
    now = 30*DAY
    t = _tab(first_seen=now - 10*DAY, last_seen=now - 60,
             url="https://example.com/x", domain="example.com")
    assert classifier.classify(t, [t], cfg=_cfg(), now=now).action == "KEEP"


def test_together_profile_no_auto_close():
    cfg = _cfg()
    now = 100*DAY
    t = _tab(profile="Together User", first_seen=now-50*DAY, last_seen=now-30*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=cfg, now=now)
    assert d.action == "TRIAGE"
