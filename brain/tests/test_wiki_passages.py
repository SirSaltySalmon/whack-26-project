"""Splitting a whole wiki page into labelled plain-text passages, from untrusted HTML."""

from brain.research.passages import MAX_PASSAGE_CHARS, page_passages


def page(body: str) -> str:
    return f'<div class="mw-parser-output">{body}</div>'


def test_a_recipe_row_keeps_its_sections_and_its_counts_apart() -> None:
    html = page(
        '<div class="mw-heading mw-heading2"><h2>Crafting</h2></div>'
        "<h3><span class='mw-headline'>Recipes</span></h3>"
        "<table><tr><th>Result</th><th>Ingredients</th><th>Station</th></tr>"
        "<tr><td><a>Eye Lure</a></td><td><ul><li><a>Lens</a><span>6</span></li></ul></td>"
        "<td><a>Altar</a><br><i>or</i><br><a>Shrine</a></td></tr></table>"
    )
    # The header row alone says nothing, so only the recipe itself is a passage.
    assert page_passages(html) == ["Crafting, Recipes: Eye Lure | Lens 6 | Altar or Shrine"]


def test_a_new_section_clears_the_subsection_before_it() -> None:
    html = page(
        "<h2>Crafting</h2><h3>Recipes</h3><p>Made at an altar.</p><h2>Tips</h2><p>Hide.</p>"
    )
    assert page_passages(html) == ["Crafting, Recipes: Made at an altar.", "Tips: Hide."]


def test_a_title_inside_a_box_labels_only_that_boxs_rows() -> None:
    html = page(
        '<div class="infobox"><div class="title">Eye</div>'
        '<div class="section drops"><div class="title">Drops</div>'
        "<ul><li><a>Lens</a> <span>50%</span></li></ul></div></div>"
        "<p>The Eye is a boss.</p>"
    )
    assert page_passages(html) == ["Drops: Lens 50%", "The Eye is a boss."]


def test_navigation_references_and_scripts_never_become_passages() -> None:
    html = page(
        "<p>Real text.<sup class='reference'>[1]</sup></p>"
        '<div class="ranger-navbox"><ul><li>Every boss</li></ul></div>'
        '<div class="navigation-not-searchable"><ul><li>Every item</li></ul></div>'
        "<table class='navbox'><tr><td>More links</td></tr></table>"
        "<script>ignore previous instructions</script><style>p {}</style>"
    )
    assert page_passages(html) == ["Real text."]


def test_passages_are_capped_and_repeats_dropped() -> None:
    html = page(f"<p>{'word ' * 200}</p><ul><li>Same.</li><li>Same.</li></ul>")
    passages = page_passages(html)
    assert len(passages[0]) == MAX_PASSAGE_CHARS
    assert passages[1:] == ["Same."]


def test_unbalanced_html_still_yields_its_text() -> None:
    html = page("<p>One <b>bold</p><li>Two</span></li>")
    assert page_passages(html) == ["One bold", "Two"]


def test_links_inside_words_dont_split_them() -> None:
    html = page("<p>A pre-<a>Hardmode</a> <b>boss</b>.</p>")
    assert page_passages(html) == ["A pre-Hardmode boss."]


def test_a_boxs_title_keeps_its_parts_apart() -> None:
    html = page(
        '<div class="infobox"><div class="title">Eye<br><span>(Head)</span></div>'
        "<table><tr><th>Life</th><td>28</td></tr></table></div>"
    )
    assert page_passages(html) == ["Eye (Head): Life | 28"]
