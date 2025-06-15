# mediawiki-to-obsidian
Converts an XML MediaWiki export to Markdown files.

Suitable for migrating a Fandom Wiki to an Obsidian vault.

Handles
- Content and formatting (headers, bold, italic etc.)
- Links and aliases
- Categories (mapped to "tags" in Obsidian)
- Infoboxes (converted to YAML frontmatters, also inferring the category "tag")
- Image downloads!

# Usage
1. Download the XML export of the wiki (e.g go to WIKIURL/wiki/Special:Export and hand it a list of pages, obtainable from Special:AllPage)
2. Run `python3 convert.py FILENAME.xml`
