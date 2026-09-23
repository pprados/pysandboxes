#!/usr/bin/env python3
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Convert the research paper from Markdown to LaTeX, with a BibTeX bibliography.

The paper uses three conventions that plain pandoc does not understand, and this
script normalises them before handing the document over:

1. Citations are written ``[[KEY]]`` and resolved against the ``## References``
   section, which is a Markdown list rather than a ``.bib`` file. The script
   parses that section into a ``.bib`` and rewrites every ``[[KEY]]`` into
   ``\\cite{KEY}``.
2. Diagrams are ```mermaid`` fences, which LaTeX cannot typeset. Each is written
   out as a ``.mmd`` file and, when mermaid-cli and a browser are available,
   rendered to PDF and included as a figure. Otherwise the source is emitted
   verbatim so nothing is silently lost.
3. The title block and the table of contents are Markdown constructs that belong
   in LaTeX metadata and ``\\tableofcontents`` instead. The headings keep their
   own numbers, so LaTeX's section numbering is switched off.

Usage::

    python md2latex.py                    # research.md -> build/*.tex + *.bib
    python md2latex.py --pdf              # ... and typeset the PDF
    python md2latex.py --arxiv            # ... and package the arXiv tarball
    python md2latex.py --bib-only         # only regenerate the bibliography
    python md2latex.py --no-render        # skip the diagram rendering
    python md2latex.py --name foo         # change the generated files' stem

Nothing is required to produce the bibliography and the normalised Markdown.
``pandoc`` is required for the LaTeX step, a LaTeX toolchain with ``biber`` for
the PDF, and mermaid-cli plus a Chromium build for the diagrams; each missing
tool degrades that one step rather than failing the run.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Stem of every generated file, taken from the paper's title rather than a
#: generic "paper", so a downloaded PDF still says what it is.
DOCUMENT_NAME = "confining-python-by-observation"

# --------------------------------------------------------------------------- #
# Bibliography
# --------------------------------------------------------------------------- #

#: Venues that make an entry a conference paper rather than a preprint or a page.
_PROCEEDINGS = (
    "RAID",
    "ICST",
    "NDSS",
    "ICLR",
    "NeurIPS",
    "USENIX",
    "CCS",
    "S&P",
    "Oakland",
    "EuroSys",
    "ASPLOS",
    "OSDI",
    "SOSP",
    "HotOS",
)

_ARXIV = re.compile(r"arXiv:(\d{4}\.\d{4,5})", re.I)
_URL = re.compile(r"<(https?://[^>]+)>")
_ITALIC = re.compile(r"\*([^*]{4,})\*")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_BIB_ITEM = re.compile(r"^- \[([A-Z0-9-]+)\]\s*(.*)$")


@dataclass
class BibEntry:
    """One parsed bibliography entry, ready to be serialised as BibTeX."""

    key: str
    raw: str
    title: str = ""
    author: str = ""
    year: str = ""
    url: str = ""
    arxiv: str = ""
    venue: str = ""
    note: str = ""

    @property
    def entry_type(self) -> str:
        if self.venue:
            return "inproceedings"
        if self.arxiv:
            return "misc"
        return "misc"

    def to_bibtex(self) -> str:
        fields: list[tuple[str, str]] = []
        if self.author:
            fields.append(("author", _format_authors(self.author)))
        fields.append(("title", self.title or self.key))
        if self.venue:
            fields.append(("booktitle", self.venue))
        if self.year:
            fields.append(("year", self.year))
        if self.arxiv:
            fields.append(("eprint", self.arxiv))
            fields.append(("archivePrefix", "arXiv"))
        if self.url:
            # biblatex renders `url` natively; `howpublished` would duplicate it.
            fields.append(("url", self.url))
        if self.note:
            fields.append(("note", self.note))
        body = ",\n".join(f"  {k:<15} = {{{_escape_bib(v)}}}" for k, v in fields)
        return f"@{self.entry_type}{{{self.key},\n{body}\n}}\n"


def _format_authors(authors: str) -> str:
    """Turn a comma-separated author list into BibTeX's ``and``-separated form.

    BibTeX and biber read a comma inside a name as the "Last, First" separator,
    so a comma-separated list is rejected outright ("too many commas") and the
    whole entry is dropped. The paper writes authors as "F. Last, F. Last", which
    is unambiguous to split.
    """
    names: list[str] = []
    for name in authors.split(","):
        name = name.strip().rstrip(".")
        if not name:
            continue
        # "et al" is BibTeX's "others", which renders as the usual et al.
        names.append("others" if name.lower() in {"et al", "et al."} else name)
    return " and ".join(names)


def _escape_bib(value: str) -> str:
    """Escape the characters BibTeX treats specially, leaving \\url{} intact."""
    if value.startswith("\\url{"):
        return value
    for char in ("&", "%", "#", "_"):
        value = value.replace(char, "\\" + char)
    return value


#: A sentence boundary: a period followed by space, with no digit on either side
#: and not preceded by a lone capital, so "2.7" and "A. Effenhauser" stay whole.
_SENTENCE = re.compile(r"(?<!\d)(?<![A-Z])\.(?!\d)\s")

#: Titles longer than this are truncated, with the remainder kept in the note.
_TITLE_MAX = 200


def _clean(text: str) -> str:
    """Strip Markdown emphasis, code spans and angle-bracket links from prose."""
    text = _URL.sub("", text)
    text = re.sub(r"[`*]", "", text)
    text = " ".join(text.split())
    # Removing an author or a title from the middle leaves doubled separators.
    text = re.sub(r"(,\s*){2,}", ", ", text)
    return text.strip(" .,;—-")


def _make_note(raw: str, entry: BibEntry) -> str:
    """Build a note holding only what the structured fields do not already say."""
    note = _clean(raw)
    for known in (entry.author, entry.title):
        if known and known in note:
            note = note.replace(known, "", 1)
    note = _clean(note)
    # A note that merely restates the year or the arXiv id carries nothing.
    if len(note) < 12 or note.lower().startswith("arxiv:"):
        return ""
    return note[:300]


def parse_references(markdown: str) -> list[BibEntry]:
    """Parse the ``## References`` section into structured entries.

    Entries look like ``- [KEY] Author, *Title*, venue (year). <url>`` with
    continuation lines indented by two spaces.
    """
    match = re.search(r"^## References\s*$(.*?)(?=^## |\Z)", markdown, re.S | re.M)
    if not match:
        return []

    # Re-join each item with its continuation lines before parsing.
    items: list[tuple[str, str]] = []
    for line in match.group(1).splitlines():
        item = _BIB_ITEM.match(line)
        if item:
            items.append((item.group(1), item.group(2)))
        elif items and line.startswith("  ") and line.strip():
            items[-1] = (items[-1][0], items[-1][1] + " " + line.strip())

    entries: list[BibEntry] = []
    for key, raw in items:
        entry = BibEntry(key=key, raw=raw)

        url = _URL.search(raw)
        entry.url = url.group(1) if url else ""

        arxiv = _ARXIV.search(raw)
        entry.arxiv = arxiv.group(1) if arxiv else ""

        year = _YEAR.search(raw)
        entry.year = year.group(0) if year else ""

        entry.venue = next((v for v in _PROCEEDINGS if v in raw), "")

        italic = _ITALIC.search(raw)
        if italic:
            entry.title = _clean(italic.group(1))
            before = raw[: italic.start()]
            # An author list precedes the title and ends with a comma.
            if "," in before and len(_clean(before)) < 160:
                entry.author = _clean(before).rstrip(",")
        else:
            # No italic title: take the first sentence. Split on a period that is
            # followed by whitespace and not surrounded by digits, so that
            # version numbers ("Python 2.7", "asteval 1.0.1") stay intact.
            entry.title = _clean(_SENTENCE.split(raw, maxsplit=1)[0])

        if not entry.title:
            entry.title = entry.key

        # An over-long title is a parse that went wide; keep the head and let the
        # remainder fall into the note rather than emitting an unusable title.
        if len(entry.title) > _TITLE_MAX:
            entry.title = entry.title[:_TITLE_MAX].rsplit(" ", 1)[0] + "…"

        entry.note = _make_note(raw, entry)
        entries.append(entry)

    return entries


# --------------------------------------------------------------------------- #
# Diagrams
# --------------------------------------------------------------------------- #

_MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)

#: A figure caption declared inside the diagram, as a mermaid comment:
#: ``%% caption: The five rungs, and the last layer able to see each``.
_CAPTION = re.compile(r"^\s*%%\s*caption:\s*(.+)$", re.M)

#: Browsers mermaid-cli can drive, in order of preference.
_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")

#: Chrome flags that let it run headless in a container or a restricted account.
_CHROME_ARGS = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-crash-reporter",
    "--no-first-run",
)


def _mermaid_command() -> list[str] | None:
    """Locate mermaid-cli, falling back to running it through npx."""
    mmdc = shutil.which("mmdc")
    if mmdc:
        return [mmdc]
    if shutil.which("npx"):
        return ["npx", "-y", "@mermaid-js/mermaid-cli"]
    return None


def _puppeteer_config(figdir: Path) -> tuple[Path, dict[str, str]] | None:
    """Write a puppeteer config and the environment mermaid-cli needs.

    Returns None when no browser can be found, which is the usual reason
    rendering is unavailable on a headless machine.
    """
    import json
    import os

    browser = os.environ.get("PUPPETEER_EXECUTABLE_PATH") or next(
        (p for name in _BROWSERS if (p := shutil.which(name))), None
    )
    if not browser:
        return None

    profile = figdir / ".chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    config = figdir / ".puppeteer.json"
    config.write_text(
        json.dumps({"args": list(_CHROME_ARGS) + [f"--user-data-dir={profile}"]}),
        encoding="utf-8",
    )
    env = dict(os.environ, PUPPETEER_EXECUTABLE_PATH=browser)
    return config, env


def extract_diagrams(markdown: str, figdir: Path, render: bool) -> tuple[str, int, int]:
    """Replace each mermaid fence with a figure, writing the sources to *figdir*.

    Each diagram is always written out as ``figure-NN.mmd`` so nothing is lost.
    When mermaid-cli and a browser are both available the diagram is rendered to
    PDF and included as a real figure; otherwise the LaTeX carries the source in
    a verbatim block, clearly marked as unrendered.

    Returns the rewritten Markdown, the number of diagrams found, and the number
    rendered.
    """
    figdir.mkdir(parents=True, exist_ok=True)
    command = _mermaid_command() if render else None
    puppeteer = _puppeteer_config(figdir) if command else None
    if render and not command:
        print(
            "  ! mermaid-cli not found (install it, or npx must be available):" " diagrams will be emitted as source.",
            file=sys.stderr,
        )
    elif render and not puppeteer:
        print("  ! no Chrome/Chromium found for mermaid-cli:" " diagrams will be emitted as source.", file=sys.stderr)

    rendered = 0
    count = 0
    unnamed: list[int] = []

    def replace(match: re.Match[str]) -> str:
        nonlocal rendered, count
        count += 1
        source = match.group(1)
        stem = f"figure-{count:02d}"
        mmd = figdir / f"{stem}.mmd"
        mmd.write_text(source, encoding="utf-8")

        # The caption is declared in the diagram itself, as a mermaid comment,
        # so the .mmd stays self-describing and mermaid ignores the line.
        title = _CAPTION.search(source)
        caption = title.group(1).strip() if title else f"Diagram {count}"
        if not title:
            unnamed.append(count)

        if command and puppeteer:
            config, env = puppeteer
            pdf = figdir / f"{stem}.pdf"
            # --pdfFit shrinks the PDF page to the chart. Without it mermaid-cli
            # draws into its default 800x600 page, so a short diagram carries a
            # band of blank paper underneath it in the typeset figure.
            result = subprocess.run(
                [*command, "--pdfFit", "-p", str(config), "-i", str(mmd), "-o", str(pdf)],
                capture_output=True,
                text=True,
                errors="replace",
                env=env,
            )
            if result.returncode == 0 and pdf.exists():
                rendered += 1
                # Markdown, not raw LaTeX: a raw block would swallow the
                # headings that follow it, silently dropping whole sections.
                return f"\n![{caption}](figures/{stem}.pdf){{#fig:{stem}}}\n"
            detail = (result.stderr or result.stdout).strip().splitlines()
            reason = next(
                (line for line in detail if "Error" in line or "failed" in line),
                detail[-1] if detail else "unknown error",
            )
            print(f"  ! mermaid-cli failed on {stem}: {reason[:140]}", file=sys.stderr)

        # No renderer, or rendering failed: keep the source rather than lose it.
        # A fenced block, not an indented one, so the verbatim region is
        # delimited unambiguously for the Unicode substitution that follows.
        return (
            f"\n*{caption} — Mermaid source, not rendered. "
            "Install mermaid-cli and a Chromium build, then re-run.*\n\n"
            f"```\n{source.rstrip()}\n```\n"
        )

    result = _MERMAID.sub(replace, markdown)
    if unnamed:
        print(f"  ! diagrams without a caption: {unnamed} — add a" " '%% caption: ...' line to each", file=sys.stderr)
    return result, count, rendered


# --------------------------------------------------------------------------- #
# Document normalisation
# --------------------------------------------------------------------------- #


@dataclass
class Metadata:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    email: str = ""
    date: str = ""
    version: str = ""
    keywords: list[str] = field(default_factory=list)


def extract_metadata(markdown: str) -> tuple[str, Metadata]:
    """Pull the title block out of the body and return it as metadata."""
    meta = Metadata()

    title = re.search(r"^# (.+)$", markdown, re.M)
    if title:
        meta.title = title.group(1).strip()
        markdown = markdown.replace(title.group(0) + "\n", "", 1)

    subtitle = re.search(r"^### (.+)$", markdown, re.M)
    if subtitle and subtitle.start() < 400:
        meta.subtitle = subtitle.group(1).strip()
        markdown = markdown.replace(subtitle.group(0) + "\n", "", 1)

    author = re.search(r"^\*\*([^*]+)\*\* — \[([^\]]+)\]\(mailto:([^)]+)\)\s*$", markdown, re.M)
    if author:
        meta.author = author.group(1).strip()
        meta.email = author.group(3).strip()
        markdown = markdown.replace(author.group(0) + "\n", "", 1)

    # "**Version 1.0** — September 2026", or a bare month and year.
    date = re.search(
        r"^(?:\*\*Version ([\d.]+)\*\* — )?"
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December) \d{4})\s*$",
        markdown,
        re.M,
    )
    if date:
        meta.version = date.group(1) or ""
        meta.date = date.group(2)
        markdown = markdown.replace(date.group(0) + "\n", "", 1)

    keywords = re.search(r"^\*\*Keywords\*\* — (.+?)\.\s*$", markdown, re.M | re.S)
    if keywords:
        meta.keywords = [k.strip() for k in re.split(r"[;\n]", keywords.group(1)) if k.strip()]

    return markdown, meta


#: Characters 8-bit TeX cannot typeset, mapped to a LaTeX equivalent. pdflatex
#: aborts on each of these; xelatex would cope, but pdflatex is the common case.
_UNICODE_TEX = {
    "✅": r"\ding{51}",
    "✔": r"\ding{51}",
    "✓": r"\ding{51}",
    "❌": r"\ding{55}",
    "✘": r"\ding{55}",
    "✗": r"\ding{55}",
    "⚠": r"\textbf{!}",
    "→": r"$\rightarrow$",
    "←": r"$\leftarrow$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "≠": r"$\neq$",
}


#: The same symbols inside code, where a LaTeX macro would be shown verbatim
#: instead of being typeset. An arrow in a listing has to read as "->".
_UNICODE_ASCII = {
    "✅": "[x]",
    "✔": "[x]",
    "✓": "[x]",
    "❌": "[ ]",
    "✘": "[ ]",
    "✗": "[ ]",
    "⚠": "(!)",
    "→": "->",
    "←": "<-",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
}

#: Regions whose content is typeset verbatim: fenced blocks and inline spans.
_CODE_REGION = re.compile(r"^```.*?^```$|`[^`\n]+`", re.S | re.M)


def substitute_unicode(markdown: str) -> tuple[str, int]:
    """Replace symbols pdflatex cannot render, respecting verbatim regions.

    Prose gets LaTeX macros. Code blocks and inline code get ASCII, because a
    ``$\\rightarrow$`` inside a listing is printed as those nine characters
    rather than as an arrow.
    """
    total = 0

    def convert(text: str, table: dict[str, str]) -> str:
        nonlocal total
        for char, replacement in table.items():
            count = text.count(char)
            if count:
                text = text.replace(char, replacement)
                total += count
        return text

    out: list[str] = []
    last = 0
    for match in _CODE_REGION.finditer(markdown):
        out.append(convert(markdown[last : match.start()], _UNICODE_TEX))
        out.append(convert(match.group(0), _UNICODE_ASCII))
        last = match.end()
    out.append(convert(markdown[last:], _UNICODE_TEX))
    return "".join(out), total


#: A pipe-table separator row: |---|:--:|---:| and friends.
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

#: Total dash budget spread across the columns of a rewritten separator.
_TABLE_WIDTH = 72


def _split_row(row: str) -> list[str]:
    """Split a pipe-table row into cells, ignoring pipes inside code spans."""
    cells: list[str] = []
    cell: list[str] = []
    in_code = False
    for char in row.strip().strip("|"):
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(cell))
            cell = []
        else:
            cell.append(char)
    cells.append("".join(cell))
    return [c.strip() for c in cells]


def normalise_tables(markdown: str) -> tuple[str, int]:
    """Rewrite pipe-table separators so column widths follow the content.

    Pandoc derives each LaTeX column width from the *number of dashes* in the
    separator row. A hand-written table where every column is spelled ``---``
    therefore gets equal widths regardless of what it holds, and an alignment
    colon (``---:``) silently makes that column wider still. The result is a
    one-character column taking 40% of the page while the prose columns overflow
    the margin.

    Each separator is re-emitted with a dash count proportional to the widest
    cell in its column, which is the layout the author meant.
    """
    lines = markdown.splitlines()
    fixed = 0
    index = 0
    while index < len(lines):
        if index + 1 >= len(lines) or not _SEPARATOR.match(lines[index + 1]):
            index += 1
            continue

        header = _split_row(lines[index])
        aligns = _split_row(lines[index + 1])
        if len(header) < 2 or len(aligns) != len(header):
            index += 1
            continue

        # Collect the body rows to measure the real content of each column.
        end = index + 2
        widths = [len(c) for c in header]
        while end < len(lines) and lines[end].strip().startswith("|"):
            cells = _split_row(lines[end])
            if len(cells) == len(header):
                widths = [max(w, len(c)) for w, c in zip(widths, cells, strict=True)]
            end += 1

        total = sum(widths) or len(widths)
        dashes = [max(3, round(_TABLE_WIDTH * w / total)) for w in widths]
        rebuilt = []
        for align, count in zip(aligns, dashes, strict=True):
            left, right = align.startswith(":"), align.endswith(":")
            # A colon costs one character; keep the visible run at `count`.
            body = "-" * max(3, count - left - right)
            rebuilt.append(f"{':' if left else ''}{body}{':' if right else ''}")
        new = "| " + " | ".join(rebuilt) + " |"
        if new != lines[index + 1]:
            lines[index + 1] = new
            fixed += 1
        index = end

    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else ""), fixed


def strip_toc(markdown: str) -> str:
    """Remove the hand-written table of contents; LaTeX generates its own."""
    return re.sub(r"^## Table of contents\s*$.*?(?=^---\s*$)", "", markdown, flags=re.S | re.M)


def strip_references(markdown: str) -> str:
    """Remove the References section; the bibliography comes from refs.bib."""
    return re.sub(r"^## References\s*$.*?(?=^## |\Z)", "", markdown, flags=re.S | re.M)


def break_page_before_appendices(markdown: str) -> str:
    """Start each appendix on a fresh page; Markdown has no way to say this."""
    return re.sub(r"^## Appendix ", lambda m: "\\clearpage\n\n" + m.group(0), markdown, flags=re.M)


def rewrite_citations(markdown: str, known: set[str]) -> tuple[str, set[str]]:
    """Rewrite ``[[KEY]]`` into ``\\cite{KEY}``; report keys with no entry."""
    unknown: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in known:
            unknown.add(key)
        return f"\\cite{{{key}}}"

    return re.sub(r"\[\[([A-Z0-9-]+)\]\]", replace, markdown), unknown


def yaml_header(meta: Metadata) -> str:
    def quote(value: str) -> str:
        # Single-quoted YAML: no escape processing, so a backslash stays a
        # backslash. Double quotes would turn "\texttt" into a TAB plus "exttt".
        return "'" + value.replace("'", "''") + "'"

    lines = ["---", f"title: {quote(meta.title)}"]
    if meta.subtitle:
        lines.append(f"subtitle: {quote(meta.subtitle)}")
    if meta.author:
        # No `\\` here: pandoc escapes it to \textbackslash{} inside metadata.
        author = f"{meta.author} (\\texttt{{{meta.email}}})" if meta.email else meta.author
        lines.append(f"author: {quote(author)}")
    if meta.date:
        stamp = f"Version {meta.version} --- {meta.date}" if meta.version else meta.date
        lines.append(f"date: {quote(stamp)}")
    if meta.version:
        lines.append(f"version: {quote(meta.version)}")
    if meta.keywords:
        lines.append("keywords: [" + ", ".join(quote(k) for k in meta.keywords) + "]")
    lines += [
        "documentclass: article",
        "classoption: [11pt, a4paper]",
        "geometry: margin=2.5cm",
        "colorlinks: true",
        # The headings already carry their own numbers ("## 1. Problem
        # statement"), so LaTeX must not add a second set. Sections stay
        # unstarred, and therefore still appear in the table of contents.
        "numbersections: false",
        "toc: true",
        "toc-depth: 3",
        "header-includes:",
        "  - \\usepackage{graphicx}",
        "  - \\usepackage{longtable}",
        "  - \\usepackage{booktabs}",
        "  - \\usepackage{pifont}",
        # Bound every diagram to the text width and to a fraction of the page
        # height, keeping its aspect ratio. Without this a wide flowchart
        # overflows the margin and LaTeX defers the float to a page of its own.
        "  - \\setkeys{Gin}{width=\\linewidth,height=0.38\\textheight,keepaspectratio}",
        # Let a float occupy more of a page before being pushed out, and stop
        # LaTeX from stranding a figure on an otherwise empty page.
        "  - \\renewcommand{\\topfraction}{0.85}",
        "  - \\renewcommand{\\bottomfraction}{0.7}",
        "  - \\renewcommand{\\textfraction}{0.1}",
        "  - \\renewcommand{\\floatpagefraction}{0.75}",
        # Tables carry dense reference material in narrow columns. A smaller
        # body and tighter gutters keep long identifiers inside the margin, and
        # letting \\texttt hyphenate stops one long symbol from overflowing a
        # whole column.
        "  - \\usepackage{etoolbox}",
        "  - \\AtBeginEnvironment{longtable}{\\small\\setlength{\\tabcolsep}{4pt}}",
        "---",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def run_pandoc(source: Path, target: Path, bib: Path) -> bool:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        print("! pandoc not found: the LaTeX step needs it.", file=sys.stderr)
        print("    install it with:  sudo apt install pandoc", file=sys.stderr)
        print(f"    the normalised Markdown is meanwhile at {source}", file=sys.stderr)
        return False
    # Run from the output directory with relative names, so the generated .tex
    # carries `\addbibresource{refs.bib}` and stays portable.
    command = [
        pandoc,
        source.name,
        "-f",
        "markdown+raw_tex+pipe_tables+backtick_code_blocks",
        "-t",
        "latex",
        # The H1 became the LaTeX title, so the paper's own sections are H2.
        # Without this shift they map to \subsection and number as 0.1, 0.2, ...
        "--shift-heading-level-by=-1",
        "--standalone",
        "--biblatex",
        f"--bibliography={bib.name}",
        "-o",
        target.name,
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", cwd=target.parent)
    if result.returncode != 0:
        print(f"! pandoc failed:\n{result.stderr}", file=sys.stderr)
        return False
    if result.stderr.strip():
        print(f"  pandoc warnings: {result.stderr.strip()[:400]}", file=sys.stderr)
    return True


def build_pdf(tex: Path) -> bool:
    """Typeset the LaTeX to PDF, preferring latexmk and falling back to pdflatex.

    Two pdflatex passes surround the bibliography run so that citations and the
    table of contents resolve.
    """
    workdir = tex.parent
    latexmk = shutil.which("latexmk")
    if latexmk:
        runs: list[list[str]] = [[latexmk, "-pdf", "-interaction=nonstopmode", tex.name]]
    else:
        pdflatex = shutil.which("pdflatex") or shutil.which("xelatex")
        if not pdflatex:
            print("! no LaTeX toolchain (latexmk, pdflatex or xelatex): skipping the PDF.", file=sys.stderr)
            print(f"  The LaTeX source is ready at {tex}", file=sys.stderr)
            return False
        # biblatex needs biber; fall back to bibtex if only that is installed.
        bibtool = shutil.which("biber") or shutil.which("bibtex")
        runs = [[pdflatex, "-interaction=nonstopmode", tex.name]]
        if bibtool:
            runs.append([bibtool, tex.stem])
        runs.append([pdflatex, "-interaction=nonstopmode", tex.name])
        runs.append([pdflatex, "-interaction=nonstopmode", tex.name])

    # Remove any PDF from an earlier run first. Otherwise a build that fails
    # outright leaves the stale file in place, and the existence check below
    # would report success while the PDF still shows the previous content.
    pdf = tex.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)

    # A non-zero exit from a LaTeX pass is not fatal on its own: the first pass
    # always reports undefined citations, because the bibliography has not been
    # built yet. Run the whole sequence and judge it by the PDF and the log.
    for command in runs:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", cwd=workdir)
        if result.returncode != 0:
            print(f"  (non-zero exit from {Path(command[0]).name}; continuing)", file=sys.stderr)

    if not pdf.exists():
        print("! the LaTeX run produced no PDF.", file=sys.stderr)  # noqa: T201
        log = tex.with_suffix(".log")
        if log.exists():
            errors = [line for line in log.read_text(errors="replace").splitlines() if line.startswith("! ")]
            print("    " + "\n    ".join(errors[:10]), file=sys.stderr)
        return False

    # Report what the final pass could not resolve, rather than claiming success.
    log = tex.with_suffix(".log")
    if log.exists():
        text = log.read_text(errors="replace")
        errors = sorted({line for line in text.splitlines() if line.startswith("! ")})
        undefined = len(re.findall(r"Citation '[^']*' undefined", text))
        if errors:
            print(f"  ! {len(errors)} LaTeX error kind(s):", file=sys.stderr)
            print("      " + "\n      ".join(errors[:6]), file=sys.stderr)
        if undefined:
            print(f"  ! {undefined} unresolved citation(s) in the final pass", file=sys.stderr)
    print(f"  {pdf.name:<34} {pdf.stat().st_size // 1024} KB")
    return True


def build_arxiv_archive(tex: Path, name: str) -> Path | None:
    """Package the sources arXiv needs into a tarball.

    arXiv typesets the LaTeX itself, but runs neither pandoc nor biber, so the
    formatted bibliography (``.bbl``) must travel with the sources. Build
    products such as ``.aux``, ``.log`` and the PDF are deliberately excluded:
    arXiv rejects or ignores them, and a stale ``.aux`` can break its build.
    """
    import tarfile

    workdir = tex.parent
    bbl = tex.with_suffix(".bbl")
    if not bbl.exists():
        print("! no .bbl: run with --pdf first so biber produces it.", file=sys.stderr)
        return None

    members: list[tuple[Path, str]] = [(tex, tex.name), (bbl, bbl.name)]
    figures = sorted((workdir / "figures").glob("*.pdf"))
    members += [(fig, f"figures/{fig.name}") for fig in figures]

    archive = workdir / f"{name}-arxiv.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path, arcname in members:
            tar.add(path, arcname=arcname)

    print(
        f"  {archive.name:<34} {archive.stat().st_size // 1024} KB " f"({len(members)} files, {len(figures)} figures)"
    )
    if not figures:
        print(
            "    ! no rendered figures: the diagrams will appear as source in the"
            " submission. Install mermaid-cli and re-run.",
            file=sys.stderr,
        )
    return archive


def main() -> int:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=here / "research.md")
    parser.add_argument("--outdir", type=Path, default=here / "build")
    parser.add_argument("--bib-only", action="store_true", help="only generate refs.bib")
    parser.add_argument("--no-render", action="store_true", help="never invoke mermaid-cli")
    parser.add_argument("--pdf", action="store_true", help="also typeset the PDF")
    parser.add_argument(
        "--arxiv", action="store_true", help="also package the arXiv submission tarball (implies --pdf)"
    )
    parser.add_argument(
        "--name", default=DOCUMENT_NAME, help=f"stem for the generated files (default: {DOCUMENT_NAME})"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"! no such file: {args.input}", file=sys.stderr)
        return 1

    markdown = args.input.read_text(encoding="utf-8")
    args.outdir.mkdir(parents=True, exist_ok=True)

    entries = parse_references(markdown)
    bib = args.outdir / f"{args.name}.bib"
    bib.write_text(
        "% Generated by md2latex.py -- do not edit by hand.\n"
        f"% Source: {args.input.name}\n\n" + "\n".join(e.to_bibtex() for e in entries),
        encoding="utf-8",
    )
    print(f"  {bib.name:<34} {len(entries)} entries")
    if args.bib_only:
        return 0

    markdown, meta = extract_metadata(markdown)
    markdown = strip_toc(markdown)
    markdown = strip_references(markdown)
    markdown = break_page_before_appendices(markdown)
    markdown, unknown = rewrite_citations(markdown, {e.key for e in entries})
    # Diagrams first: the mermaid sources must reach mermaid-cli untouched, and
    # substituting Unicode inside them would corrupt every label.
    markdown, found, rendered = extract_diagrams(markdown, args.outdir / "figures", not args.no_render)
    markdown, substituted = substitute_unicode(markdown)
    markdown, retabled = normalise_tables(markdown)

    if retabled:
        print(f"  {'tables':<34} {retabled} column layouts rebalanced")
    if substituted:
        print(f"  {'symbols':<34} {substituted} replaced for pdflatex")

    print(f"  {'diagrams':<34} {found} found, {rendered} rendered to PDF")
    if unknown:
        print(f"! citation keys with no bibliography entry: {sorted(unknown)}", file=sys.stderr)

    normalised = args.outdir / f"{args.name}.md"
    normalised.write_text(yaml_header(meta) + markdown, encoding="utf-8")

    target = args.outdir / f"{args.name}.tex"
    if not run_pandoc(normalised, target, bib):
        return 1
    # Pandoc escapes the bibliography *filename* as if it were text, so a name
    # carrying an underscore reaches biber as `foo\_bar.bib` and is not found.
    tex_source = target.read_text(encoding="utf-8")
    escaped = bib.name.replace("_", r"\_")
    fixed = tex_source.replace(rf"\addbibresource{{{escaped}}}", rf"\addbibresource{{{bib.name}}}")
    if fixed != tex_source:
        target.write_text(fixed, encoding="utf-8")
    print(f"  {target.name:<34} {target.stat().st_size // 1024} KB")

    if args.pdf or args.arxiv:
        if not build_pdf(target):
            return 1
        if args.arxiv and build_arxiv_archive(target, args.name) is None:
            return 1
    else:
        print("\nTo build the PDF:")
        print(f"  python {Path(__file__).name} --pdf")
        print(f"  (or: cd {args.outdir} && latexmk -pdf {target.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
