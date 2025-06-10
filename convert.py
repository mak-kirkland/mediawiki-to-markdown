import os
import re
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from collections import defaultdict
import mwparserfromhell
import sys

NS = "http://www.mediawiki.org/xml/export-0.11/"
TAG = lambda t: f"{{{NS}}}{t}"
USE_PANDOC = True

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <input_xml_file> [output_dir]")
    sys.exit(1)

INPUT_XML = sys.argv[1]
OUTPUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "obsidian_vault"

os.makedirs(OUTPUT_DIR, exist_ok=True)

tag_to_pages = defaultdict(list)
filename_counts = defaultdict(int)

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', '_', title.strip())

def extract_categories(text):
    wikicode = mwparserfromhell.parse(text)
    categories = []
    for link in wikicode.ifilter_wikilinks():
        target = str(link.title).strip()
        if target.lower().startswith("category:"):
            cat = target[len("category:"):].strip()
            categories.append(cat)
            wikicode.remove(link)
    return str(wikicode).strip(), categories

def extract_infobox_to_yaml(text):
    wikicode = mwparserfromhell.parse(text)
    infobox_data = {}
    infobox_template = None

    for template in wikicode.filter_templates():
        if str(template.name).strip().lower():
            infobox_template = template
            break

    if not infobox_template:
        return str(wikicode), {}

    raw_name = str(infobox_template.name).strip().lower()
    if raw_name.startswith("infobox_"):
        infobox_type = raw_name[len("infobox_"):].replace(' ', '_').title()
    else:
        infobox_type = infobox_template.name

    infobox_data['infobox'] = infobox_type

    for param in infobox_template.params:
        key = str(param.name).strip().replace(":", "").lower()
        val = str(param.value).strip()

        # Split values containing wikilinks into lists
        wikilinks = re.findall(r'\[\[([^\]]+)\]\]', val)
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
    return str(wikicode).strip(), infobox_data

def extract_yaml_header(title, tags, extra_fields=None):
    yaml = {'title': title, 'tags': [t.replace(" ", "_").lower() for t in tags]}
    if extra_fields:
        yaml.update(extra_fields)

    lines = ['---']
    for key, value in yaml.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                # Always quote list items that contain square brackets (Obsidian links)
                if isinstance(item, str) and ('[[' in item or ']]' in item):
                    lines.append(f'  - "{item}"')
                else:
                    lines.append(f'  - "{item}"' if isinstance(item, str) else f'  - {item}')
        else:
            # Always quote values containing square brackets (Obsidian links)
            if isinstance(value, str) and ('[[' in value or ']]' in value):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f'{key}: "{value}"' if isinstance(value, str) else f'{key}: {value}')
    lines.append('---\n')
    return "\n".join(lines)

def unwrap_text_paragraphs(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]

    unwrapped = []
    buffer = []
    in_code_block = False

    def flush_buffer():
        if buffer:
            paragraph = " ".join(buffer)
            unwrapped.append(paragraph)
            buffer.clear()

    for line in lines:
        stripped = line.strip()

        # detect fenced code block start/end
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_buffer()
            in_code_block = not in_code_block
            unwrapped.append(line)
            continue

        if in_code_block:
            unwrapped.append(line)
            continue

        if not stripped:
            flush_buffer()
            unwrapped.append("")
        elif re.match(r'^(\s*[-*+]\s+|\s*#)', line):
            flush_buffer()
            unwrapped.append(line)
        else:
            buffer.append(stripped)

    flush_buffer()
    return "\n".join(unwrapped)

def clean_heading_ids(md_text):
    # Remove {#id} fragments after headers, e.g. ## Title {#id} -> ## Title
    return re.sub(r'^(#{1,6} .+?)\s*\{\#.*?\}', r'\1', md_text, flags=re.MULTILINE)

def extract_links_from_pandoc(md_text):
    """
    Convert all [text](target) and [text](target "wikilink") to [[target|text]].
    Handles parentheses in targets (e.g., "Sofia(town)").
    """
    # Regex to match [text](target) or [text](target "wikilink")
    pattern = re.compile(
        r'\[([^\]]+)\]\(([^\)]+?(?:\([^\)]*\))?(?:\s+"wikilink")?)\)'
    )

    def replacer(match):
        text = match.group(1).strip()
        target = match.group(2).replace(' "wikilink"', '').strip()
        return f"[[{target}|{text}]]" if text != target else f"[[{target}]]"

    return pattern.sub(replacer, md_text)

def clean_residual_wikilink_artifacts(md_text):
    """Clean up any remaining "wikilink" strings that weren't caught earlier."""
    return md_text.replace(' "wikilink"', '')

def fix_multiline_wikilinks(md_text):
    pattern = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
    def replacer(match):
        content = match.group(1)
        clean_content = ' '.join(content.split())
        return f"[[{clean_content}]]"
    return pattern.sub(replacer, md_text)

def convert_with_pandoc(text):
    try:
        result = subprocess.run(
            ['pandoc', '--from=mediawiki', '--to=markdown'],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        md = result.stdout.decode("utf-8")

        # Fix common Pandoc artifacts
        md = md.replace("\\'", "'")
        md = fix_multiline_wikilinks(md)
        md = clean_heading_ids(md)
        md = extract_links_from_pandoc(md)      # Handle wikilinks
        md = clean_residual_wikilink_artifacts(md)  # Clean leftovers
        return md
    except subprocess.CalledProcessError as e:
        print("⚠️ Pandoc conversion failed. Using unconverted text.")
        print(e.stderr.decode())
        return text

def clean_and_convert_text(raw_text, title):
    text = unescape(raw_text)
    text, tags = extract_categories(text)
    text, infobox_data = extract_infobox_to_yaml(text)
    yaml_header = extract_yaml_header(title, tags, infobox_data)

    for tag in tags:
        normalized_tag = tag.replace(" ", "_").lower()
        tag_to_pages[normalized_tag].append(title)

    return yaml_header + "\n" + text.strip() + "\n", tags

def convert_pages(tree):
    ns = {"ns": NS}
    for page in tree.findall(".//ns:page", ns):
        title_elem = page.find("ns:title", ns)
        if title_elem is None:
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
            yaml_match = re.match(r'(?s)^---\n(.*?)\n---\n(.*)', markdown)
            if yaml_match:
                yaml_block, content = yaml_match.groups()
                converted_md = unwrap_text_paragraphs(content)
                converted_md = convert_with_pandoc(converted_md)
                converted_md = unwrap_text_paragraphs(converted_md)

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
        lines = [f"# {tag.replace('_', ' ').title()} Index\n"]
        for page in sorted(pages):
            lines.append(f"- [[{page}]]")
        with open(os.path.join(index_dir, f"{safe_tag}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    print("📚 Index pages created under _indexes/")

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
