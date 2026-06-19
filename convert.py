import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from collections import defaultdict
import mwparserfromhell
import sys
import json
import requests
import yaml
import argparse
import inflect
import logging
from tqdm import tqdm

p = inflect.engine()

# Constants
NS = "http://www.mediawiki.org/xml/export-0.11/"
IMAGE_DIR = "images"


def TAG(t):
    return f"{{{NS}}}{t}"


def parse_args():
    parser = argparse.ArgumentParser(description="Convert MediaWiki XML to Obsidian Vault")
    parser.add_argument("input_xml", help="Input XML file")
    parser.add_argument("output_dir", nargs="?", default="obsidian_vault", help="Output directory")
    parser.add_argument("--skip-redirects", action="store_true", help="Skip redirect pages")
    parser.add_argument(
        "--skip-pandoc", action="store_true", help="Skip Pandoc conversion even if available"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--cookies",
        help="Cookie header value for API/image requests (e.g. 'name=value; other=value')",
    )
    return parser.parse_args()


args = parse_args()

logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)

INPUT_XML = args.input_xml
OUTPUT_DIR = args.output_dir
SKIP_REDIRECTS = args.skip_redirects
SKIP_PANDOC = args.skip_pandoc
COOKIES = args.cookies
PANDOC_AVAILABLE = shutil.which("pandoc") is not None

if not SKIP_PANDOC and not PANDOC_AVAILABLE:
    logging.warning(
        "⚠️ Pandoc not found on PATH. Wikitext will be kept as-is. "
        "Install Pandoc (https://pandoc.org/installing.html) or pass --skip-pandoc."
    )

os.makedirs(OUTPUT_DIR, exist_ok=True)

tag_to_pages = defaultdict(list)
filename_counts = defaultdict(int)

WIKI_URL = None


def extract_wiki_url(tree):
    global WIKI_URL
    ns = {"ns": NS}
    base_elem = tree.find(".//ns:siteinfo/ns:base", ns)
    if base_elem is not None and base_elem.text:
        base_url = base_elem.text.strip()
        WIKI_URL = re.match(r"(https?://[^/]+)/", base_url).group(1)
        if WIKI_URL:
            return
    raise ValueError("Could not extract wiki domain from <base> tag.")


def clean_filename(title):
    """Convert to safe filename with underscores"""
    return re.compile(r'[\\/*?:"<>|{}]').sub('_', title.strip())


def normalize_tag(tag):
    return tag.replace(" ", "_").lower()


def extract_categories(wikicode):
    categories = []
    for link in wikicode.ifilter_wikilinks():
        target = link.title.strip()
        if target.lower().startswith("category:"):
            cat = target[len("category:") :].strip()
            categories.append(normalize_tag(cat))
            wikicode.remove(link)
    return wikicode, categories


def extract_images(wikicode):
    images = set()
    nodes = list(wikicode.nodes)  # make a list copy because we'll modify

    for i, node in enumerate(nodes):
        if isinstance(node, mwparserfromhell.wikicode.Wikilink):
            target = node.title.strip()
            if target.lower().startswith(("file:", "image:", "media:")):
                image_name = target.split(":", 1)[1].strip()
                local_filename = download_image(image_name)

                if local_filename:
                    embed_link = f"![[{IMAGE_DIR}/{local_filename}]]"

                    # Replace the wikilink node in wikicode directly
                    wikicode.replace(node, embed_link)

                    images.add(embed_link)
    return wikicode


def get_image_url(filename):
    url = f"{WIKI_URL}/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": filename,
        "iiprop": "url",
    }
    try:
        resp = requests.get(
            url, params=params, timeout=10, headers={"Cookie": COOKIES} if COOKIES else None
        )
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            ii = page.get("imageinfo")
            if ii:
                return ii[0]["url"]
    except Exception as e:
        logging.error(f"❌ Failed to get image URL for {filename}: {e}")
    return None


def download_image(image_name):
    if not image_name:
        return None

    safe_name = clean_filename(image_name)
    filepath = os.path.join(OUTPUT_DIR, IMAGE_DIR, safe_name)
    if os.path.exists(filepath):
        logging.debug(f"🖼️ Skipping download (already exists): {safe_name}")
        return safe_name

    url = get_image_url(f"File:{image_name}")
    if not url:
        logging.warning(f"❌ Could not find URL for image: {image_name}")
        return None

    try:
        resp = requests.get(url, stream=True, headers={"Cookie": COOKIES} if COOKIES else None)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logging.debug(f"📥 Downloaded image: {safe_name}")
            return safe_name
        else:
            logging.error(f"❌ Failed to download image: {image_name} ({resp.status_code})")
            return None
    except Exception as e:
        logging.error(f"❌ Error downloading {image_name}: {e}")
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
        infobox_type = raw_name[len("infobox_") :].replace(' ', '_').title()
    else:
        infobox_type = infobox_template.name

    infobox_data['infobox'] = infobox_type

    for param in infobox_template.params:
        key = param.name.strip().replace(":", "").lower()
        val = param.value.strip()

        wikilinks = re.compile(r'\[\[(.*?)\]\]', re.DOTALL).findall(val)
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
        return str(obj)


def extract_yaml_header(title, tags, extra_fields=None):
    header = {'title': title, 'tags': tags}
    if extra_fields:
        header.update(sanitize_for_yaml(extra_fields))

    return f"---\n{yaml.safe_dump(header, sort_keys=False)}---\n"


def clean_heading_ids(md_text):
    return re.compile(r'^(#{1,6} .+?)\s*\{\#.*?\}', re.MULTILINE).sub(r'\1', md_text)


def fix_links_from_pandoc(md_text):
    def replace_wikilinks_no_files(match: re.Match):
        cleaned_filename = clean_filename(match.group(2).strip().replace('_', ' '))
        text = match.group(3).strip()
        if cleaned_filename == text:
            return f'[[{cleaned_filename}]]'
        else:
            return f'[[{cleaned_filename}|{text}]]'

    pandoc_wikilink_no_files_regex = re.compile(r'(?<!!)\[([^]]+)\]\(([^ ]+) "(.+?)"\)({[^}]+})?')
    md_text_link_no_files_fixed = pandoc_wikilink_no_files_regex.sub(
        replace_wikilinks_no_files, md_text
    )

    def replace_wikilink_inline_files(match: re.Match):
        text = match.group(3).strip()
        return f'![[{text}]]'

    pandoc_wikilink_inline_files_regex = re.compile(r'\\*!\[([^]]+)\]\(([^ ]+) "(.+?)"\)({[^}]+})?')
    md_text_link_files_fixed = pandoc_wikilink_inline_files_regex.sub(
        replace_wikilink_inline_files, md_text_link_no_files_fixed
    )
    return md_text_link_files_fixed


def clean_residual_wikilink_artifacts(md_text):
    return md_text.replace(' "wikilink"', '')


def fix_image_links(md):
    return re.sub(r'\\(!\[\[)', r'\1', md)


def cleanup_markdown(md):
    md = clean_heading_ids(md)
    md = fix_links_from_pandoc(md)
    md = clean_residual_wikilink_artifacts(md)
    md = fix_image_links(md)
    return md


def convert_with_pandoc(text, title=""):
    try:
        result = subprocess.run(
            ['pandoc', '--from=mediawiki', '--to=markdown', '--wrap=none'],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        md = result.stdout.decode("utf-8")
        md = md.replace("\\'", "'")
        return md
    except subprocess.CalledProcessError as e:
        logging.warning(f"⚠️ Pandoc failed for '{title}'. Using raw text.")
        logging.debug(e.stderr.decode())
        return text
    except OSError as e:
        logging.warning(f"⚠️ Pandoc failed for '{title}'. Using raw text.")
        logging.debug(e)
        return text


def clean_and_convert_text(raw_text, title):
    """Parse MediaWiki wikitext and prepare it for Pandoc conversion.

    Extracts categories, images, and infobox data; builds an Obsidian YAML
    front matter header; and records tags in the global tag index.

    Note: Tags will become a file and a property, weird characters will break linking,
    cleaning for good filenames with `clean_filename()`

    Returns (yaml_header, cleaned_wikitext, tags).
    """
    text = unescape(raw_text)
    wikicode = mwparserfromhell.parse(text)
    wikicode, tags = extract_categories(wikicode)
    wikicode = extract_images(wikicode)
    wikicode, infobox_data = extract_infobox(wikicode)

    tags = [clean_filename(tag) for tag in tags]

    # Conditionally infer tag
    if infobox_data.get('infobox'):
        infobox_name = str(infobox_data['infobox'])

        if not p.singular_noun(infobox_name):
            infobox_name = p.plural(infobox_name)

        inferred_tag = normalize_tag(infobox_name)

        if inferred_tag not in tags:
            tags.append(inferred_tag)

    cleaned_text = str(wikicode).strip()
    title = clean_filename(title)
    yaml_header = extract_yaml_header(title, tags, infobox_data)

    # Track tags for index
    for tag in tags:
        tag_to_pages[tag].append(title)

    return yaml_header, cleaned_text, tags


def convert_pages(tree):
    ns = {"ns": NS}
    total_pages = len(tree.findall(".//ns:page", {"ns": NS}))

    disable_tqdm = logging.getLogger().level <= logging.DEBUG

    with tqdm(total=total_pages, desc="Converting pages", disable=disable_tqdm) as pbar:
        for page in tree.findall(".//ns:page", ns):
            title_elem = page.find("ns:title", ns)
            if title_elem is None or not title_elem.text:
                pbar.update(1)
                continue

            if SKIP_REDIRECTS and (page.find("ns:redirect", ns) is not None):
                logging.debug(f"⏭️ Skipping redirect: {title_elem.text.strip()}")
                pbar.update(1)
                continue

            title = title_elem.text.strip()
            logging.debug(f"✅ Found page: {title}")

            latest_revision = None
            latest_revision_id = None
            for revision in page.findall(TAG("revision")):
                try:
                    revision_id = int(revision.find(TAG("id")).text)
                except AttributeError:
                    logging.warning(f"⚠️ No ID in revision for: {title}")
                    continue

                if latest_revision_id is None or revision_id > latest_revision_id:
                    latest_revision_id = revision_id
                    latest_revision = revision

            if latest_revision is None:
                logging.warning(f"⚠️ No revision for: {title}")
                pbar.update(1)
                continue

            text_elem = latest_revision.find(TAG("text"))
            if text_elem is None or not text_elem.text or not text_elem.text.strip():
                logging.warning(f"⚠️ No content in: {title}")
                pbar.update(1)
                continue

            raw_text = text_elem.text
            yaml_str, wikitext, tags = clean_and_convert_text(raw_text, title)
            if not SKIP_PANDOC and PANDOC_AVAILABLE:
                wikitext = convert_with_pandoc(wikitext, title)
                wikitext = cleanup_markdown(wikitext)
            markdown = f"{yaml_str}\n{wikitext.strip()}\n"
            base_filename = clean_filename(title)
            count = filename_counts[base_filename]
            filename_counts[base_filename] += 1
            filename = f"{base_filename}{'_' + str(count) if count else ''}.md"
            filepath = os.path.join(OUTPUT_DIR, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                logging.debug(f"✍️ Writing: {filepath}")
                f.write(markdown)

            pbar.update(1)

    logging.info("✅ Main articles converted")


def create_tag_indexes():
    """Write Obsidian index pages for each collected tag.

    Uses the global tag_to_pages map populated during conversion(`clean_and_convert_text()`)
    to emit one markdown file per tag under _indexes/, each with YAML front matter and
    wikilinks to every page in that tag.

    Note: Tags and page titles become filenames and wikilinks; weird characters
    will break linking, so both are cleaned with `clean_filename()`.
    """
    index_dir = os.path.join(OUTPUT_DIR, "_indexes")
    os.makedirs(index_dir, exist_ok=True)
    for tag, pages in tag_to_pages.items():
        tag = clean_filename(tag)
        display_tag = tag
        yaml_header = extract_yaml_header(f"Index: {display_tag}", tag)
        lines = [f"# {display_tag.title()} Index"]
        for page in sorted(pages):
            display_page = clean_filename(page)
            lines.append(f"- [[{display_page}]]")
        content = yaml_header + "\n".join(lines)
        with open(os.path.join(index_dir, f"_{tag}.md"), "w", encoding="utf-8") as f:
            f.write(content)
    logging.info("📚 Index pages created under _indexes/ with tag references")


def main():
    logging.info("🔄 Converting MediaWiki XML to Obsidian Vault...")
    try:
        tree = ET.parse(INPUT_XML)
    except ET.ParseError as e:
        logging.error(f"❌ Failed to parse XML: {e}")
        return

    try:
        extract_wiki_url(tree)
    except ValueError as e:
        logging.error(f"❌ {e}")
        return

    convert_pages(tree)
    create_tag_indexes()
    logging.info(f"✅ All done! Markdown vault ready at: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
