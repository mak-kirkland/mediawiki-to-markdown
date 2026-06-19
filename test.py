"""Unit tests for convert.py.

Pandoc link post-processing tests reflect output from Pandoc 3.9.0.2.
"""

import pytest
import mwparserfromhell
from convert import (
    clean_heading_ids,
    fix_links_from_pandoc,
    extract_yaml_header,
    extract_infobox,
    clean_and_convert_text,
)

# Test 1: Heading cleanup
def test_clean_heading_ids():
    md = "# Heading 1 {#heading1}\n## Heading 2 {#heading2}"
    expected = "# Heading 1\n## Heading 2"
    assert clean_heading_ids(md) == expected

# Test 2: Pandoc-style link cleanup
def test_fix_links_from_pandoc_internal():
    md = 'This is a [Foo Bar](Foo_Bar "Foo Bar"){.wikilink} and [Alias](Target_Page "Alias"){.wikilink}.'
    expected = 'This is a [[Foo Bar]] and [[Target Page|Alias]].'
    assert fix_links_from_pandoc(md) == expected

def test_fix_links_from_pandoc_external():
    md = 'Visit [Google](https://google.com) or contact [me](mailto:test@example.com).'
    assert fix_links_from_pandoc(md) == md  # Should remain unchanged

# Test 3: YAML frontmatter generation
def test_extract_yaml_header_basic():
    title = "Sample_Page Title"
    tags = ["category_one", "tag_two"]
    yaml = extract_yaml_header(title, tags)
    assert "---" in yaml
    assert "title: Sample_Page Title" in yaml # Spaces Shouldn't be converted into underscores
    assert "tags:" in yaml
    assert "- category_one" in yaml
    assert "- tag_two" in yaml

# Test 4: Infobox parsing and tag inference
def test_extract_infobox_and_tags():
    wikitext = """
{{Infobox_character
| name = Aragorn
| race = [[Human]]
| weapon = [[Andúril]]
}}
[[Category:Characters]]
"""
    wikicode = mwparserfromhell.parse(wikitext)
    cleaned_wikicode, infobox = extract_infobox(wikicode)

    assert infobox["infobox"] == "Character"
    assert "name" in infobox
    assert "race" in infobox
    assert infobox["weapon"] == ["[[Andúril]]"]

def test_clean_and_convert_text_adds_infobox_tag():
    wikitext = """
{{Infobox_artifact
| name = One Ring
| creator = [[Sauron]]
}}
[[Category:Items]]
"""
    yaml, text, tags = clean_and_convert_text(wikitext, "One_Ring")
    assert "artifacts" in [t.lower() for t in tags]
    assert "items" in [t.lower() for t in tags]
    assert "---" in yaml
