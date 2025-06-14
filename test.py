import pytest
import mwparserfromhell
from convert import (
    clean_wikilink,
    fix_wikilink_spacing,
    clean_heading_ids,
    extract_links_from_pandoc,
    extract_yaml_header,
    extract_infobox,
    clean_and_convert_text,
)

# Test 1: Wikilink formatting
def test_clean_wikilink_simple():
    assert clean_wikilink("Foo_Bar") == "[[Foo Bar]]"

def test_clean_wikilink_with_alias():
    assert clean_wikilink("Foo_Bar|Alias") == "[[Foo Bar|Alias]]"

def test_fix_wikilink_spacing():
    text = "This is a [[Foo_Bar]] and a [[Baz_Bat|Alias]] link."
    result = fix_wikilink_spacing(text)
    assert result == "This is a [[Foo Bar]] and a [[Baz Bat|Alias]] link."

# Test 2: Heading cleanup
def test_clean_heading_ids():
    md = "# Heading 1 {#heading1}\n## Heading 2 {#heading2}"
    expected = "# Heading 1\n## Heading 2"
    assert clean_heading_ids(md) == expected

# Test 3: Pandoc-style link cleanup
def test_extract_links_from_pandoc_internal():
    md = 'This is a [Foo Bar](Foo_Bar "wikilink") and [Alias](Target_Page "wikilink").'
    expected = 'This is a [[Foo Bar]] and [[Target Page|Alias]].'
    assert extract_links_from_pandoc(md) == expected

def test_extract_links_from_pandoc_external():
    md = 'Visit [Google](https://google.com) or contact [me](mailto:test@example.com).'
    assert extract_links_from_pandoc(md) == md  # Should remain unchanged

# Test 4: YAML frontmatter generation
def test_extract_yaml_header_basic():
    title = "Sample_Page"
    tags = ["Category One", "Tag Two"]
    yaml = extract_yaml_header(title, tags)
    assert "---" in yaml
    assert "title: \"Sample Page\"" in yaml
    assert "tags:" in yaml
    assert "  - \"category_one\"" in yaml
    assert "  - \"tag_two\"" in yaml

# Test 5: Infobox parsing and tag inference
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
