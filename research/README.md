# Research paper

The conceptual paper behind `py-sandboxes`, and the tooling that turns it into a
LaTeX/PDF submission.

| File | What it is |
|---|---|
| [`research.md`](research.md) | The paper. This is the **source of truth** — edit only this. |
| [`md2latex.py`](md2latex.py) | Converter: Markdown → LaTeX + BibTeX (+ PDF). |
| [`Makefile`](Makefile) | The paper's own build rules, independent of the repository's. |
| [`LICENSE`](LICENSE) | CC BY-NC-SA 4.0, covering the paper. The *software* stays Apache-2.0. |
| `confining-python-by-observation.{pdf,tex,bbl}` | Generated, and kept here: the PDF to read, and what an arXiv submission needs. |
| `confining-python-by-observation-arxiv.tar.gz` | Generated: the submission archive, ready to upload. |
| `figures/` | Generated: the rendered diagrams, when mermaid-cli is available. |
| `build/` | Generated scratch space, git-ignored. Never edit anything in it. |

Every generated file is named after the paper rather than a generic `paper`, so
a downloaded PDF still says what it is.

## Building

The paper has its own `Makefile`, so its build stays independent of the
repository's. From this directory:

```bash
make tex    # research.md -> .tex + the bibliography
make pdf    # the above, then the PDF
make arxiv  # the above, then the submission tarball
make clean  # drop build/ and every generated file
```

Or from the repository root, with `make -C research <rule>`.

Every rule depends on `research.md` and on the converter, so a change to either
triggers a rebuild and nothing else does. Everything is produced under
`build/`, then the publishable subset — `.tex`, `.bbl`, `.pdf` and the rendered
figures — is copied back beside the paper.

The `.bbl` is what ships, not the `.bib`: arXiv typesets the LaTeX itself but
runs neither pandoc nor biber, so it needs the *formatted* bibliography. The
`.bib` stays in `build/` as an intermediate.

The tarball contains exactly what arXiv wants — the `.tex`, the `.bbl`, the
figures and a `00README.json` — and deliberately omits `.aux`, `.log` and the
PDF, which arXiv either ignores or chokes on. The `00README.json` asks for
pdflatex and for the TeX Live release that reads the `.bbl` format the local
biber wrote: 2023 for format 3.2 (biber 2.19), 2025 for format 3.3 (biber
2.20). arXiv defaults to TeX Live 2025, so check that choice on the upload page.

Or call the converter directly, which is useful while iterating:

```bash
python md2latex.py              # LaTeX + bibliography
python md2latex.py --pdf        # ... and typeset the PDF
python md2latex.py --bib-only   # only the bibliography
python md2latex.py --no-render  # skip the diagram rendering
python md2latex.py --name foo   # change the generated files' stem
```

## What you need installed

The converter degrades rather than failing: without pandoc you still get
`refs.bib` and the normalised Markdown, and without mermaid-cli the diagrams are
emitted as source instead of figures. For a submission-quality PDF you want all
three. `make arxiv` does not degrade: it checks every tool below first, prints
the install command of each one missing, and fails if a diagram is not rendered.

**pandoc** — the Markdown → LaTeX step.

```bash
sudo apt install pandoc
```

**A LaTeX toolchain with biber** — the PDF step. `biber` is required because the
generated document uses `biblatex`, and `pifont` supplies the ✓/✗ glyphs that
replace the Unicode ones pdflatex cannot typeset.

```bash
sudo apt install texlive-latex-recommended texlive-latex-extra \
                 texlive-fonts-recommended texlive-bibtex-extra biber latexmk
```

`latexmk` is optional: without it the script falls back to running
`pdflatex`/`biber`/`pdflatex`/`pdflatex` itself.

**mermaid-cli and a Chromium build** — the diagrams. mermaid-cli drives a
headless browser, so a browser must be present.

```bash
npm install -g @mermaid-js/mermaid-cli   # provides `mmdc`
sudo apt install chromium                # or use an existing Google Chrome
```

If `mmdc` is not on `PATH` the script falls back to `npx -y
@mermaid-js/mermaid-cli`. It auto-detects Chrome or Chromium and passes the
flags a headless or containerised environment needs; set
`PUPPETEER_EXECUTABLE_PATH` to override the choice.

> Note: rendering needs the browser to create a local socket for its process
> singleton. Inside a hardened sandbox that denies `socket()`, mermaid-cli fails
> with `Check failed: . socket() failed: Operation not permitted`, and the
> diagrams fall back to source. On an ordinary desktop or CI runner this does
> not occur.

**Do not render to SVG and convert afterwards.** Mermaid places every label in a
`<foreignObject>` holding HTML, which Inkscape, `rsvg-convert` and most other
SVG→PDF converters silently ignore: the result is a diagram of empty boxes with
no text. The script therefore asks mermaid-cli for PDF directly, letting the
browser rasterise the labels. A converter route would need mermaid's
`htmlLabels: false`, which restores real `<text>` elements but drops the `<b>`
emphasis the diagrams use.

## How the conversion works

The paper uses three conventions plain pandoc does not understand, which is why
this script exists rather than a one-line pandoc invocation.

1. **Citations** are written `[[KEY]]` and resolved against the `## References`
   section, which is a Markdown list rather than a `.bib` file. The script parses
   that section into `refs.bib` — inferring authors, title, year, venue, arXiv id
   and URL — and rewrites every `[[KEY]]` into `\cite{KEY}`. A citation with no
   matching entry is reported rather than silently dropped.
2. **Diagrams** are ```` ```mermaid ```` fences. Each is written out as
   `build/figures/figure-NN.mmd`, rendered to PDF when possible, and included as
   a real figure; otherwise the source is emitted verbatim and clearly labelled
   as unrendered, so nothing is lost.

   Each diagram carries its own caption, declared as a mermaid comment on the
   first line so that the `.mmd` stays self-describing and mermaid ignores it:

   ````
   ```mermaid
   %% caption: Each rung of attacker capability, and the last layer able to see it
   flowchart LR
   ```
   ````

   A diagram without one is reported at build time and falls back to
   "Diagram N".
3. **The title block and table of contents** are Markdown constructs. They are
   lifted into LaTeX metadata and `\tableofcontents`. The version and date line
   (`**Version 1.0** — September 2026`) becomes `\date{}`.

Symbols pdflatex cannot represent (✅, ❌, →, ≤, …) are substituted with LaTeX
macros before conversion; the count is reported on each run.

## Publishing

The paper is written to be self-contained wherever it is published: every link
to the implementation is an absolute URL into the GitHub repository, so it
survives being lifted out of this tree.

When submitting to arXiv, note that the license chosen here — CC BY-NC-SA 4.0 —
is one of the licenses arXiv accepts, and must be selected explicitly during
submission to match the `LICENSE` file.
