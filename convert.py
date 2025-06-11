import os
import re
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from collections import defaultdict
import mwparserfromhell
import sys
import json

# Constants
NS = "http://www.mediawiki.org/xml/export-0.11/"
TAG = lambda t: f"{{{NS}}}{t}"
USE_PANDOC = True

# Pre-compiled regex patterns
INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')
HEADING_ID_REGEX = re.compile(r'^(#{1,6} .+?)\s*\{\#.*?\}', re.MULTILINE)
WIKILINK_REGEX = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
PANDOC_LINK_REGEX = re.compile(
    r'\[([^\]]+)\]\(((?:[^\(\)]+|\([^\)]*\))+)(?:\s+"wikilink")?\)'
)
YAML_FRONTMATTER_REGEX = re.compile(r'(?s)^---\n(.*?)\n---\n(.*)')

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <input_xml_file> [output_dir]")
    sys.exit(1)

INPUT_XML = sys.argv[1]
OUTPUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "obsidian_vault"

os.makedirs(OUTPUT_DIR, exist_ok=True)

tag_to_pages = defaultdict(list)
filename_counts = defaultdict(int)

def clean_filename(title):
    """Convert to safe filename with underscores"""
    return INVALID_FILENAME_CHARS.sub('_', title.strip())

def display_title(title):
    """Convert to human-readable title with spaces"""
    return title.replace('_', ' ')

def contains_wikilink(s):
    return isinstance(s, str) and ('[[' in s and ']]' in s)

def fix_wikilink_spacing(text):
    """Convert underscores to spaces in wikilinks"""
    def replacer(match):
        link_content = match.group(1)
        if '|' in link_content:
            target, alias = link_content.split('|', 1)
            return f"[[{target.replace('_', ' ')}|{alias}]]"
        return f"[[{link_content.replace('_', ' ')}]]"
    return WIKILINK_REGEX.sub(replacer, text)

def extract_categories(wikicode):
    categories = []
    for link in wikicode.ifilter_wikilinks():
        target = link.title.strip()
        if target.lower().startswith("category:"):
            cat = target[len("category:"):].strip()
            categories.append(cat)
            wikicode.remove(link)
    return wikicode, categories

def extract_infobox(wikicode):
    infobox_data = {}
    infobox_template = None

    for template in wikicode.filter_templates():
        if template.name.strip():
            infobox_template = template
            break

    if not infobox_template:
        return wikicode, {}

    raw_name = infobox_template.name.strip().lower()
    if raw_name.startswith("infobox_"):
        infobox_type = raw_name[len("infobox_"):].replace(' ', '_').title()
    else:
        infobox_type = infobox_template.name

    infobox_data['infobox'] = infobox_type

    for param in infobox_template.params:
        key = param.name.strip().replace(":", "").lower()
        val = param.value.strip()

        wikilinks = WIKILINK_REGEX.findall(val)
        if wikilinks:
            parts = []
            remaining = val
            for link in wikilinks:
                before, link_part, remaining = remaining.partition(f"[[{link}]]")
                if before.strip():
                    parts.append(before.strip())
                parts.append(f"[[{link}]]")
            if remaining.strip():
                parts.append(remaining.strip())
            infobox_data[key] = parts
        else:
            infobox_data[key] = val

    wikicode.remove(infobox_template)
    return wikicode, infobox_data

def extract_yaml_header(title, tags, extra_fields=None):
    yaml = {
        'title': display_title(title),
        'tags': [display_title(t).lower().replace(" ", "_") for t in tags]
    }
    if extra_fields:
        yaml.update(extra_fields)

    lines = ['---']
    for key, value in yaml.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if contains_wikilink(item):
                    lines.append(f'  - "{fix_wikilink_spacing(item)}"')
                else:
                    lines.append(f'  - {json.dumps(item) if isinstance(item, str) else item}')
        else:
            if contains_wikilink(value):
                lines.append(f'{key}: "{fix_wikilink_spacing(value)}"')
            else:
                lines.append(f'{key}: {json.dumps(value) if isinstance(value, str) else value}')
    lines.append('---\n')
    return "\n".join(lines)

def clean_heading_ids(md_text):
    return HEADING_ID_REGEX.sub(r'\1', md_text)

def extract_links_from_pandoc(md_text):
    def replacer(match):
        text = match.group(1).strip()
        target = match.group(2).replace(' "wikilink"', '').strip()
        if target.startswith(('http://', 'https://', 'mailto:')):
            return match.group(0)
        return f"[[{target.replace('_', ' ')}|{text}]]" if text != target else f"[[{target.replace('_', ' ')}]]"
    return PANDOC_LINK_REGEX.sub(replacer, md_text)

def clean_residual_wikilink_artifacts(md_text):
    return md_text.replace(' "wikilink"', '')

def fix_multiline_wikilinks(md_text):
    def replacer(match):
        content = match.group(1)
        clean_content = ' '.join(content.split())
        return f"[[{clean_content.replace('_', ' ')}]]"
    return WIKILINK_REGEX.sub(replacer, md_text)

def cleanup_markdown(md):
    md = fix_multiline_wikilinks(md)
    md = clean_heading_ids(md)
    md = extract_links_from_pandoc(md)
    md = clean_residual_wikilink_artifacts(md)
    md = fix_wikilink_spacing(md)
    return md

def convert_with_pandoc(text, title=""):
    try:
        result = subprocess.run(
            ['pandoc', '--from=mediawiki', '--to=markdown', '--wrap=none'],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        md = result.stdout.decode("utf-8")
        md = md.replace("\\'", "'")
        return cleanup_markdown(md)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Pandoc failed for '{title}'. Using raw text.")
        print(e.stderr.decode())
        return text

def clean_and_convert_text(raw_text, title):
    text = unescape(raw_text)
    wikicode = mwparserfromhell.parse(text)

    wikicode, tags = extract_categories(wikicode)
    wikicode, infobox_data = extract_infobox(wikicode)

    cleaned_text = str(wikicode).strip()
    yaml_header = extract_yaml_header(title, tags, infobox_data)

    for tag in tags:
        normalized_tag = tag.replace(" ", "_").lower()
        tag_to_pages[normalized_tag].append(title)

    return yaml_header + "\n" + cleaned_text + "\n", tags

def convert_pages(tree):
    ns = {"ns": NS}
    for page in tree.findall(".//ns:page", ns):
        title_elem = page.find("ns:title", ns)
        if title_elem is None or not title_elem.text:
            continue
        title = title_elem.text.strip()
        print("✅ Found page:", title)

        revision = page.find(TAG("revision"))
        if revision is None:
            print(f"⚠️ No revision for: {title}")
            continue

        text_elem = revision.find(TAG("text"))
        if text_elem is None or not text_elem.text or not text_elem.text.strip():
            print(f"⚠️ No content in: {title}")
            continue

        raw_text = text_elem.text
        markdown, tags = clean_and_convert_text(raw_text, title)

        if USE_PANDOC:
            yaml_match = YAML_FRONTMATTER_REGEX.match(markdown)
            if yaml_match:
                yaml_block, content = yaml_match.groups()
                converted_md = convert_with_pandoc(content, title)
                markdown = f"---\n{yaml_block}\n---\n{converted_md}"

        base_filename = clean_filename(title)
        count = filename_counts[base_filename]
        filename_counts[base_filename] += 1

        filename = f"{base_filename}{'_' + str(count) if count else ''}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            print(f"✍️ Writing: {filepath}")
            f.write(markdown)

    print("✅ Main articles converted.")

def create_tag_indexes():
    index_dir = os.path.join(OUTPUT_DIR, "_indexes")
    os.makedirs(index_dir, exist_ok=True)
    for tag, pages in tag_to_pages.items():
        safe_tag = clean_filename(tag)
        display_tag = display_title(tag)
        yaml_header = extract_yaml_header(
            f"Index: {display_tag}",
            [safe_tag],
        )
        lines = [f"# {display_tag.title()} Index"]
        for page in sorted(pages):
            display_page = display_title(page)
            lines.append(f"- [[{display_page}]]")
        content = yaml_header + "\n".join(lines)
        with open(os.path.join(index_dir, f"{safe_tag}.md"), "w", encoding="utf-8") as f:
            f.write(content)
    print("📚 Index pages created under _indexes/ with tag references")

def main():
    print("🔄 Converting MediaWiki XML to Obsidian Vault...")
    try:
        tree = ET.parse(INPUT_XML)
    except ET.ParseError as e:
        print(f"❌ Failed to parse XML: {e}")
        return

    convert_pages(tree)
    create_tag_indexes()
    print(f"✅ All done! Markdown vault ready at: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
