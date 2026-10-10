"""The NSE Lab card parser, on a small made-up page shaped like screener.in's."""
# ruff: noqa: E501  (an HTML fixture reads better unwrapped)

from app.labs.nse_desk.screener import has_numbers, match, parse

PAGE = """
<h1 class="h2"><span class="square"><img alt=""></span><span class="min-width-0">Acme Industries Ltd</span></h1>
<div class="sub show-more-box about" data-x="1"><p>Acme makes widgets.</p></div>
<ul id="top-ratios">
 <li class="flex"><span class="name"> Market Cap </span><span class="nowrap value">&#8377; <span class="number">1,234</span> Cr. </span></li>
 <li class="flex"><span class="name"> Stock P/E </span><span class="nowrap value"> <span class="number">21.2</span> </span></li>
</ul>
<table class="ranges-table"><tr><th colspan="2">Compounded Sales Growth</th></tr>
<tr><td>5 Years:</td><td>18%</td></tr><tr><td>TTM:</td><td>15%</td></tr></table>
<div class="pros"><p class="title">Pros</p><ul><li>Debt free</li></ul></div>
<div class="cons"><p class="title">Cons</p><ul><li>Low ROE</li></ul></div>
<section id="quarters"><table><tr><th></th><th>Mar 2026</th><th>Jun 2026</th></tr>
<tr><td>Sales +</td><td>100</td><td>120</td></tr><tr><td>Net Profit +</td><td>10</td><td>12</td></tr></table></section>
<section id="balance-sheet"><table><tr><th></th><th>Mar 2025</th><th>Mar 2026</th></tr>
<tr><td>Borrowings +</td><td>50</td><td>40</td></tr></table></section>
<section id="shareholding"><table><tr><th></th><th>Mar 2026</th><th>Jun 2026</th></tr>
<tr><td>Promoters +</td><td>50.1%</td><td>50.3%</td></tr></table></section>
"""


def test_the_card_reads_every_section():
    c = parse(PAGE)
    assert c["name"] == "Acme Industries Ltd" and c["about"] == "Acme makes widgets."
    assert c["ratios"][0] == {"name": "Market Cap", "value": "₹ 1,234 Cr."}
    assert c["growth"][0] == {"title": "Compounded Sales Growth", "rows": [["5 Years:", "18%"], ["TTM:", "15%"]]}
    assert c["quarters"]["Net Profit"] == {"periods": ["Mar 2026", "Jun 2026"], "values": ["10", "12"]}
    assert c["borrowings"]["values"] == ["50", "40"]
    assert c["promoters"]["values"] == ["50.1%", "50.3%"]
    assert c["pros"] == ["Debt free"] and c["cons"] == ["Low ROE"]


def test_a_missing_section_is_empty_not_an_error():
    c = parse("<h1>Only a name</h1>")
    assert c["name"] == "Only a name" and c["ratios"] == [] and c["borrowings"] is None


def test_names_are_matched_to_nse_symbols():
    listed = [("RELIANCE", "Reliance Industries Limited"), ("RELINFRA", "Reliance Infrastructure Limited"),
              ("TCS", "Tata Consultancy Services Limited")]
    assert match("tcs", listed) == "TCS"
    assert match("Reliance Industries", listed) == "RELIANCE"
    assert match("reliance", listed) == "RELIANCE"          # shortest name wins
    assert match("nothing like this", listed) is None


def test_an_empty_consolidated_page_is_spotted():
    empty = PAGE.replace("1,234", "").replace("21.2", "")
    assert has_numbers(parse(PAGE)) and not has_numbers(parse(empty))
