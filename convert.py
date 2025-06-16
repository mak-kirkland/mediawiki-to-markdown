import os
import re
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from collections import defaultdict
import mwparserfromhell
import sys
import json
import requests
import yaml

# Constants
NS = "http://www.mediawiki.org/xml/export-0.11/"
def TAG(t):
    return f"{{{NS}}}{t}"
USE_PANDOC = True
IMAGE_DIR = "images"

# Pre-compiled regex patterns
INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')
HEADING_ID_REGEX = re.compile(r'^(#{1,6} .+?)\s*\{\#.*?\}', re.MULTILINE)
WIKILINK_REGEX = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
PANDOC_LINK_REGEX = re.compile(
    r'\[([^\]]+)\]\(((?:[^\(\)]+|\([^\)]*\))+)(?:\s+"wikilink")?\)'
)

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <input_xml_file> [output_dir]")
    sys.exit(1)

INPUT_XML = sys.argv[1]
OUTPUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "obsidian_vault"

os.makedirs(OUTPUT_DIR, exist_ok=True)

tag_to_pages = defaultdict(list)
filename_counts = defaultdict(int)

WIKI_DOMAIN = None

def extract_wiki_domain(tree):
    global WIKI_DOMAIN
    ns = {"ns": NS}
    base_elem = tree.find(".//ns:siteinfo/ns:base", ns)
    if base_elem is not None and base_elem.text:
        base_url = base_elem.text.strip()
        match = re.match(r"https?://([^/]+)/", base_url)
        if match:
            WIKI_DOMAIN = match.group(1)
            return
    raise ValueError("Could not extract wiki domain from <base> tag.")

def clean_filename(title):
    """Convert to safe filename with underscores"""
    return INVALID_FILENAME_CHARS.sub('_', title.strip())

def normalize_tag(tag):
    return tag.replace(" ", "_").lower()

def display_title(title):
    """Convert to human-readable title with spaces"""
    return title.replace('_', ' ')

def clean_wikilink(link_content):
    """Centralized wikilink cleaning"""
    if '|' in link_content:
        target, alias = link_content.split('|', 1)
        return f"[[{target.replace('_', ' ')}|{alias}]]"
    return f"[[{link_content.replace('_', ' ')}]]"

def fix_wikilink_spacing(text):
    """Convert underscores to spaces in wikilinks using centralized cleaner"""
    return WIKILINK_REGEX.sub(lambda m: clean_wikilink(m.group(1)), text)

def extract_categories(wikicode):
    categories = []
    for link in wikicode.ifilter_wikilinks():
        target = link.title.strip()
        if target.lower().startswith("category:"):
            cat = target[len("category:"):].strip()
            categories.append(normalize_tag(cat))
            wikicode.remove(link)
    return wikicode, categories

def extract_images(wikicode):
    images = set()
    nodes = list(wikicode.nodes)  # make a list copy because we'll modify

    for i, node in enumerate(nodes):
        if isinstance(node, mwparserfromhell.wikicode.Wikilink):
            target = node.title.strip()
            if target.lower().startswith(("file:", "image:")):
                image_name = target.split(":", 1)[1].strip()
                local_filename = download_image(image_name)

                if local_filename:
                    embed_link = f"![[{IMAGE_DIR}/{local_filename}]]"

                    # Replace the wikilink node in wikicode directly
                    wikicode.replace(node, embed_link)

                    images.add(embed_link)
    return wikicode

# Use this to retrieve image URLs from the wiki
def get_image_url(wiki_domain, filename):
    url = f"https://{wiki_domain}/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": filename,
        "iiprop": "url"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            ii = page.get("imageinfo")
            if ii:
                return ii[0]["url"]
    except Exception as e:
        print(f"❌ Failed to get image URL for {filename}: {e}")
    return None

def download_image(image_name):
    if not image_name:
        return None

    safe_name = clean_filename(image_name)
    filepath = os.path.join(OUTPUT_DIR, IMAGE_DIR, safe_name)
    if os.path.exists(filepath):
        print(f"🖼️ Skipping download (already exists): {safe_name}")
        return safe_name

    url = get_image_url(WIKI_DOMAIN, f"File:{image_name}")
    if not url:
        print(f"❌ Could not find URL for image: {image_name}")
        return None

    try:
        resp = requests.get(url, stream=True)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"📥 Downloaded image: {safe_name}")
            return safe_name
        else:
            print(f"❌ Failed to download image: {image_name} ({resp.status_code})")
            return None
    except Exception as e:
        print(f"❌ Error downloading {image_name}: {e}")
        return None

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

    # Extract the image from the infox and inline it at top of markdown
    if image_name := infobox_data.get('image'):
        image_name = image_name.strip()
        download_image(image_name)
        embed = f"![[{IMAGE_DIR}/{image_name}]]\n\n"
        wikicode.insert(0, embed)

    return wikicode, infobox_data

def sanitize_for_yaml(obj):
    if isinstance(obj, dict):
        return {sanitize_for_yaml(k): sanitize_for_yaml(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_yaml(i) for i in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)  # fallback: stringify unknown types

def extract_yaml_header(title, tags, extra_fields=None):
    header = {
        'title': display_title(title),
        'tags': tags
    }
    if extra_fields:
        header.update(sanitize_for_yaml(extra_fields))

    return f"---\n{yaml.safe_dump(header, sort_keys=False)}---\n"

def clean_heading_ids(md_text):
    return HEADING_ID_REGEX.sub(r'\1', md_text)

def extract_links_from_pandoc(md_text):
    def replacer(match):
        text = match.group(1).strip()
        target = match.group(2).replace(' "wikilink"', '').strip()

        if target.startswith(('http://', 'https://', 'mailto:')):
            return match.group(0)

        clean_target = display_title(target)
        # Only include alias if it's actually different
        if text == clean_target:
            return f"[[{clean_target}]]"
        else:
            return f"[[{clean_target}|{text}]]"
    return PANDOC_LINK_REGEX.sub(replacer, md_text)

def clean_residual_wikilink_artifacts(md_text):
    return md_text.replace(' "wikilink"', '')

def fix_image_links(md):
    return re.sub(r'\\(!\[\[)', r'\1', md)

def cleanup_markdown(md):
    md = clean_heading_ids(md)
    md = extract_links_from_pandoc(md)
    md = clean_residual_wikilink_artifacts(md)
    md = fix_wikilink_spacing(md)
    md = fix_image_links(md)
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
        return md
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Pandoc failed for '{title}'. Using raw text.")
        print(e.stderr.decode())
        return text

# Updated clean_and_convert_text
def clean_and_convert_text(raw_text, title):
    text = unescape(raw_text)
    wikicode = mwparserfromhell.parse(text)
    wikicode, tags = extract_categories(wikicode)
    wikicode = extract_images(wikicode)
    wikicode, infobox_data = extract_infobox(wikicode)

    # Conditionally infer tag
    if infobox_data.get('infobox'):
        inferred_tag = f"{infobox_data['infobox'].lower()}s"
        if inferred_tag not in tags:
            tags.append(inferred_tag)

    cleaned_text = str(wikicode).strip()
    yaml_header = extract_yaml_header(title, tags, infobox_data)

    # Track tags for index
    for tag in tags:
        tag_to_pages[tag].append(title)

    return yaml_header, cleaned_text, tags

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

        yaml_str, wikitext, tags = clean_and_convert_text(raw_text, title)

        if USE_PANDOC:
            wikitext = convert_with_pandoc(wikitext, title)

        wikitext = cleanup_markdown(wikitext)

        markdown = f"{yaml_str}\n{wikitext.strip()}\n"
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
        display_tag = display_title(tag)
        yaml_header = extract_yaml_header(
            f"Index: {display_tag}",
            tag,
        )
        lines = [f"# {display_tag.title()} Index"]
        for page in sorted(pages):
            display_page = display_title(page)
            lines.append(f"- [[{display_page}]]")
        content = yaml_header + "\n".join(lines)
        with open(os.path.join(index_dir, f"_{tag}.md"), "w", encoding="utf-8") as f:
            f.write(content)
    print("📚 Index pages created under _indexes/ with tag references")

def main():
    print("🔄 Converting MediaWiki XML to Obsidian Vault...")
    try:
        tree = ET.parse(INPUT_XML)
    except ET.ParseError as e:
        print(f"❌ Failed to parse XML: {e}")
        return

    try:
        extract_wiki_domain(tree)
    except ValueError as e:
        print(f"❌ {e}")
        return

    convert_pages(tree)
    create_tag_indexes()
    print(f"✅ All done! Markdown vault ready at: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
