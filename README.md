# MediaWiki to Markdown Vault Converter 🧭

This script converts a MediaWiki XML dump into a clean, tag-driven Markdown vault — including images, categories, infoboxes, and structured YAML frontmatter.

🧭 If you're looking for a worldbuilding tool to connect your ideas, check out my app [Chronicler](https://chronicler.pro/) (source available [here](https://github.com/mak-kirkland/chronicler))

🗂️ If you want to organize your vault into folders based on tags, check out my [Markdown Vault Organizer](https://github.com/mak-kirkland/markdown-vault-organizer).

## ✨ Features

- ✅ Converts MediaWiki pages to Obsidian-compatible Markdown
- 🏷️ Extracts and normalizes categories as `tags`
- 📦 Converts infoboxes into YAML frontmatter (including images)
- 🔧 Infers tags from infobox types using noun inflection
- 🖼️ Downloads and embeds images as `![[images/Filename]]` (supports `File:`, `Image:`, and `Media:` links)
- 🔗 Converts internal links to Obsidian-safe `[[Wikilinks]]` via Pandoc post-processing
- 📚 Automatically generates tag-based index files under `_indexes/`
- 🐢 Uses Pandoc for wikitext-to-Markdown conversion when available (recommended; falls back to raw wikitext on failure)
- ⏭️ Optional `--skip-pandoc` flag to bypass Pandoc conversion entirely and keep raw wikitext
- 🔐 Optional `--cookies` flag for authenticated wikis (private wikis, login-required image downloads)
- 🔍 Verbose mode for detailed output and easier troubleshooting

## Support

If you find this script useful, please consider supporting me on Patreon:

☕️ [Buy Me a Coffee](https://buymeacoffee.com/chronicler)
❤️ [Support on Patreon](https://patreon.com/MichaelKirkland)

---

## 📦 Requirements

> **⚠️ Tested Pandoc version: 3.9.0.2**
>
> Pandoc integration (including wikilink post-processing) is tested against **Pandoc 3.9.0.2**. Other versions may work, but Pandoc's Markdown output can change between releases — if your version differs, conversion results may not match what was tested here.

- Python 3.8+ (already installed — see **Installation** below for the rest)
- [Pandoc](https://pandoc.org/installing.html) CLI on your `PATH` — **optional but recommended** for proper Markdown and wikilink conversion (or pass `--skip-pandoc` to skip it). Install **3.9.0.2** when possible (see callout above).

Python dependencies are listed in `requirements.txt`. All packages use pinned versions (`~=`) for compatibility across environments. You are free to remove the version constraints and try the latest (or older) releases if you prefer — just keep in mind that unpinned installs may introduce breaking changes.

| Package            | Purpose                                |
| ------------------ | -------------------------------------- |
| `mwparserfromhell` | Parse and manipulate wikitext          |
| `requests`         | Download images from the wiki API      |
| `pyyaml`           | Generate YAML frontmatter              |
| `tqdm`             | Progress bar during conversion         |
| `inflect`          | Infer tags from infobox template names |

## 🛠️ Installation

These steps assume **Python 3.8+ is already installed**. Clone or download this repository, then open a terminal in the project folder (`mediawiki-to-markdown`).

### 1. Install the Pandoc CLI (optional but recommended)

`convert.py` uses Pandoc when available for wikitext-to-Markdown conversion and wikilink cleanup. Without it, the script still runs but leaves raw wikitext in place. You can also pass `--skip-pandoc` at runtime to bypass conversion even when Pandoc is installed.

**Use Pandoc 3.9.0.2** — the version this project is tested against (see **Requirements**). Package managers often ship older releases; download the matching build from the [Pandoc install page](https://pandoc.org/installing.html) if needed.

Install the CLI once for your operating system:

> **Using Conda?** You can install Pandoc with `conda install -c conda-forge pandoc` inside your environment — see **Option B — Conda** below and skip this step.

<details>
<summary><strong>macOS</strong></summary>

With [Homebrew](https://brew.sh/):

```bash
brew install pandoc
```

Or download the macOS package from the [Pandoc install page](https://pandoc.org/installing.html).

Verify:

```bash
pandoc --version
```

</details>

<details>
<summary><strong>Linux</strong></summary>

**Debian / Ubuntu:**

```bash
sudo apt update
sudo apt install pandoc
```

**Fedora:**

```bash
sudo dnf install pandoc
```

**Arch Linux:**

```bash
sudo pacman -S pandoc
```

Or use your distribution's package manager, or the [official Linux tarball](https://pandoc.org/installing.html).

Verify:

```bash
pandoc --version
```

</details>

<details>
<summary><strong>Windows</strong></summary>

Pick one of these options:

**winget** (Windows 10/11):

```powershell
winget install JohnMacFarlane.Pandoc
```

**Chocolatey:**

```powershell
choco install pandoc
```

**Installer:** download the `.msi` from the [Pandoc install page](https://pandoc.org/installing.html) and run it. Restart your terminal afterward so `PATH` updates.

Verify in **Command Prompt** or **PowerShell**:

```powershell
pandoc --version
```

</details>

### 2. Install Python dependencies

Choose **venv** (built into Python) or **Conda** (if you already use it).

#### Option A — venv (recommended)

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
cd mediawiki-to-markdown

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

To deactivate later: `deactivate`

</details>

<details>
<summary><strong>Windows (Command Prompt)</strong></summary>

```bat
cd mediawiki-to-markdown

python -m venv .venv
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

To deactivate later: `deactivate`

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
cd mediawiki-to-markdown

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

If activation is blocked by execution policy, run once (as Administrator):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

To deactivate later: `deactivate`

</details>

#### Option B — Conda

Works the same on macOS, Linux, and Windows. Conda can install Pandoc alongside your Python dependencies in one environment:

```bash
cd mediawiki-to-markdown

conda create -n mediawiki-md python=3.8
conda activate mediawiki-md

conda install -c conda-forge pandoc

pip install -r requirements.txt
```

To deactivate later: `conda deactivate`

> **Tip:** If you install Pandoc here, you can skip step 1 above.

### 3. Verify the setup

With your environment activated:

```bash
python convert.py --help
```

You should see the script's help text. If you installed Pandoc, confirm the version matches **3.9.0.2** (the tested version):

```bash
pandoc --version
# Expected first line: pandoc 3.9.0.2
```

---

## 📥 Creating the input XML file

`convert.py` expects a MediaWiki XML export — the same format produced by [Special:Export](https://www.mediawiki.org/wiki/Special:Export) or `dumpBackup.php`. The file must include a `<base>` URL in `<siteinfo>` so the script can resolve image downloads.

### CLI (preferred)

If you have shell access to the MediaWiki server, use the maintenance script. This is the simplest and most reliable option for full or partial exports.

From the wiki root directory:

```bash
# Current revision of every page
php maintenance/run.php dumpBackup --current > wiki-dump.xml

# Full revision history
php maintenance/run.php dumpBackup --full > wiki-dump-full.xml

# Specific namespaces only (0 = main, 10 = Template, 14 = Category, etc.)
php maintenance/run.php dumpBackup --current --namespaces 0,10,14 > partial-dump.xml

# Pages listed in a text file (one title per line)
php maintenance/run.php dumpBackup --current --pagelist pages.txt > selected.xml
```

On older MediaWiki installations you may need to run the script directly from the `maintenance/` folder:

```bash
cd maintenance
php dumpBackup.php --current > ../wiki-dump.xml
```

See the [dumpBackup.php manual](https://www.mediawiki.org/wiki/Manual:DumpBackup.php) for all options.

### Web (Special:Export)

Use this when you do not have server access, or only need a small set of pages.

1. Open `Special:Export` on your wiki (e.g. `https://your-wiki.example/wiki/Special:Export`).
2. Enter page titles — one per line — in the text box. For a single page you can also visit `Special:Export/Page_Title` directly.
3. Optionally check **Include templates** so transcluded templates are exported too.
4. Optionally check **Export all revisions** to include full history (limited to 100 revisions per page via the web UI).
5. Click **Export** and save the downloaded XML file.

For scripted exports over HTTP, you can POST to `Special:Export` with curl:

```bash
curl -d "pages=Main_Page&pages=Another_Page&action=submit" \
  "https://your-wiki.example/wiki/Special:Export" \
  -o wiki-export.xml
```

See [Help:Export](https://www.mediawiki.org/wiki/Help:Export) and [Parameters to Special:Export](https://www.mediawiki.org/wiki/Manual:Parameters_to_Special:Export) for details.

> **Tip:** If your export does not include templates, pages that rely on them may not render correctly after conversion. Include templates in the export when possible.

---

## 🚀 Usage

```bash
python convert.py INPUT_XML [OUTPUT_DIR] [--skip-redirects] [--skip-pandoc] [--verbose] [--cookies COOKIES]
```

| Argument           | Description                                                                 |
| ------------------ | --------------------------------------------------------------------------- |
| `INPUT_XML`        | Path to your MediaWiki XML dump                                             |
| `OUTPUT_DIR`       | Optional output folder (default: `obsidian_vault/`)                          |
| `--skip-redirects` | Ignore redirect pages                                                       |
| `--skip-pandoc`    | Skip Pandoc conversion and wikilink cleanup, even if Pandoc is installed     |
| `--verbose`        | Enable verbose logging (disables progress bar)                              |
| `--cookies`        | Cookie header for authenticated API/image requests (see below)              |

### Skipping Pandoc (`--skip-pandoc`)

Use this when you do not have Pandoc installed, or when you prefer to keep the original wikitext (e.g. for manual cleanup later). Categories, infoboxes, images, and YAML frontmatter are still processed — only the Pandoc Markdown conversion and post-processing step is skipped.

```bash
python convert.py wiki-dump.xml --skip-pandoc
```

### Authenticated wikis (`--cookies`)

If the wiki requires login to access images or the API, copy the `Cookie` header from an authenticated browser session (e.g. Developer Tools → Network → any request → Request Headers) and pass it to the script:

```bash
python convert.py wiki-dump.xml --cookies "sessionid=abc123; csrftoken=xyz789"
```

---

## 🗂️ Output Structure

```text
obsidian_vault/
├── _indexes/
│   ├── _people.md
│   ├── _locations.md
│   └── ...
├── images/
│   ├── Example.jpg
│   └── ...
├── Page_Title_1.md
├── Page_Title_2.md
└── ...
```

## 👤 Author

Created by Michael Kirkland
