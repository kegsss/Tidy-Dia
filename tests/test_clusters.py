# tests/test_clusters.py
from dia_organizer import clusters

DAY = 86_400


def _t(archive_id, domain, first_seen, title, profile="Keagan"):
    return {
        "archive_id": archive_id, "profile": profile, "domain": domain,
        "first_seen": first_seen, "title": title, "referrer": None,
    }


def test_groups_same_domain_in_2h_window():
    tabs = [
        _t(1, "tailwindcss.com", 0, "Tailwind A"),
        _t(2, "tailwindcss.com", 1800, "Tailwind B"),
        _t(3, "tailwindcss.com", 3600, "Tailwind C"),
        _t(4, "github.com", 5*DAY, "Repo"),  # different domain, different time
    ]
    groups = clusters.group(tabs)
    sizes = sorted(len(g["tabs"]) for g in groups)
    assert sizes == [1, 3]


def test_singletons_remain_singletons():
    tabs = [_t(1, "a.com", 0, "X"), _t(2, "b.com", 5*DAY, "Y")]
    groups = clusters.group(tabs)
    assert all(len(g["tabs"]) == 1 for g in groups)


def test_label_uses_domain_and_date():
    tabs = [_t(1, "tailwindcss.com", 0, "A"), _t(2, "tailwindcss.com", 600, "B")]
    groups = clusters.group(tabs)
    g = next(g for g in groups if len(g["tabs"]) > 1)
    assert "tailwindcss.com" in g["label"]
