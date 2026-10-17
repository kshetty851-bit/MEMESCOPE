from datetime import UTC, datetime, timedelta

from app.newsroom import briefing, news, refresh

RSS = b"""<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>SEC sues Binance over U.S. customers</title><link>https://ex.com/a</link>
<pubDate>Fri, 17 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;The regulator filed suit.&lt;/p&gt;</description>
<media:content url="https://img.ex.com/a.jpg"/></item>
<item><title>Opinion: why bitcoin wins</title><link>https://ex.com/opinion/b</link><pubDate>Fri, 17 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>no date</title><link>https://ex.com/c</link></item>
</channel></rss>"""


def test_parse_tags_and_skips_undated():
    items = news.parse("Ex", RSS)
    assert [i.title for i in items] == [
        "SEC sues Binance over U.S. customers",
        "Opinion: why bitcoin wins",
    ]
    a, b = items
    assert {"regulation", "exchanges"} <= set(a.topics) and "US" in a.regions
    assert a.summary == "The regulator filed suit." and a.image == "https://img.ex.com/a.jpg"
    assert b.kind == "commentary" and "bitcoin" in b.topics


def test_sol_needs_capitals():
    item = news.classify(
        news.Item("x", "s", "https://x", "Console sold out", "", datetime.now(UTC))
    )
    assert "solana" not in item.topics


def test_same_story_from_two_publishers_groups():
    t = datetime(2026, 10, 17, tzinfo=UTC)
    mk = lambda src, title, h: news.Item(
        f"{src}:{h}", src, f"https://{src}/{h}", title, "", t + timedelta(hours=h)
    )
    groups = news.cluster(
        [
            mk("A", "Binance hit with SEC lawsuit over customer funds", 0),
            mk("B", "SEC lawsuit hits Binance over customer funds handling", 1),
            mk("C", "Ether rallies as ETF inflows jump", 2),
        ]
    )
    assert sorted(len(g) for g in groups) == [1, 2]
    stories = refresh.stories_from([i for g in groups for i in g], t)
    two = next(s for s in stories if s["sources"] == 2)
    assert two["kind"] == "confirmed" and len(two["timeline"]) == 2


def test_briefing_only_says_what_the_data_says():
    b = briefing.write({"market": None, "stories": [], "lead": None})
    assert b["what"] == [] and "not proof of cause" in b["note"]
