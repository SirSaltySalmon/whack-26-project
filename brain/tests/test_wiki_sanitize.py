from brain.research.sanitize import clean_text, parse_article, truncate_sentences

TABLE_INFOBOX_PAGE = """
<div class="mw-parser-output">
  <div class="hatnote"><p>For the old version, see Legacy.</p></div>
  <div class="infobox npc"><div class="title">Slime King</div>
    <img src="/images/Slime.png" alt="Slime">
    <table>
      <tr><th colspan="2">Statistics</th></tr>
      <tr><th>Type</th><td><span class="tag"><a href="/wiki/Boss">Boss</a></span></td></tr>
      <tr><th>Max Life</th><td><span>2000</span><span>/</span><span>2800</span></td></tr>
      <tr><th>Immune to</th><td><img src="/i/c.png" alt="Confused"></td></tr>
    </table>
    <p>Text inside the infobox</p>
  </div>
  <p>The <b>Slime King</b> is a boss.<sup class="reference">[1]</sup> It bounces&#8203;.</p>
  <script>alert("x")</script><style>p{}</style>
  <p>Second paragraph.</p>
  <h2><span class="mw-headline">Drops</span><span class="mw-editsection">edit</span></h2>
  <p>Not part of the intro.</p>
  <div class="navbox"><p>Navigation</p></div>
</div>
"""

PORTABLE_INFOBOX_PAGE = """
<div class="mw-parser-output">
  <aside class="portable-infobox">
    <h2 class="pi-title">Hornet</h2>
    <figure><img src="https://img.test/hornet.png" alt="Idle"></figure>
    <div class="pi-item pi-data"><h3 class="pi-data-label">Gender</h3>
      <div class="pi-data-value">Female</div></div>
    <div class="pi-item pi-data"><h3 class="pi-data-label">Health</h3>
      <div class="pi-data-value">225<br>900</div></div>
  </aside>
  <p>Hornet is a protector.</p>
</div>
"""


def test_reads_intro_and_table_infobox() -> None:
    article = parse_article(TABLE_INFOBOX_PAGE, "https://wiki.test/")
    assert article.paragraphs == ["The Slime King is a boss. It bounces.", "Second paragraph."]
    assert article.infobox == [
        ("Type", "Boss"),
        ("Max Life", "2000 / 2800"),
        ("Immune to", "Confused"),
    ]
    assert article.image_url == "https://wiki.test/images/Slime.png"


def test_reads_portable_infobox_and_ignores_its_heading() -> None:
    article = parse_article(PORTABLE_INFOBOX_PAGE, "https://wiki.test/")
    assert article.paragraphs == ["Hornet is a protector."]
    assert article.infobox == [("Gender", "Female"), ("Health", "225 900")]
    assert article.image_url == "https://img.test/hornet.png"


def test_rejects_non_http_image_urls() -> None:
    html = '<div class="infobox"><img src="javascript:alert(1)"></div>'
    assert parse_article(html, "https://wiki.test/").image_url is None


def test_unbalanced_html_does_not_crash() -> None:
    article = parse_article("<p>Open <b>bold</p></div></span><p>Next", "https://wiki.test/")
    assert article.paragraphs[0] == "Open bold"


def test_clean_text_strips_invisible_and_control_characters() -> None:
    assert clean_text("a‮b​c\x07  d\n e") == "abc d e"


def test_truncate_sentences() -> None:
    assert truncate_sentences("One. Two. Three.", 2, 100) == "One. Two."
    assert truncate_sentences("a long sentence without stops", 2, 12) == "a long…"
