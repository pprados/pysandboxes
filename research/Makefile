SHELL=/bin/bash
.PHONY: tex pdf arxiv clean collect help

SRC := confining-python-by-observation.md md2latex.py
DIR := build
NAME := confining-python-by-observation

.DEFAULT_GOAL := help

# The LaTeX and the bibliography are derived artefacts: they are rebuilt
# whenever the paper or the converter changes, and never edited by hand.
$(DIR)/$(NAME).tex $(DIR)/$(NAME).bib &: $(SRC)
	unset VIRTUAL_ENV && uv run python3 md2latex.py

$(DIR)/$(NAME).pdf: $(SRC)
	unset VIRTUAL_ENV && uv run python3 md2latex.py --pdf

$(DIR)/$(NAME)-arxiv.tar.gz: $(SRC)
	unset VIRTUAL_ENV && uv run python3 md2latex.py --arxiv

# Everything is generated under build/, which is git-ignored. Only the
# publishable subset is copied back beside the paper: the PDF to read, plus the
# .tex and .bbl an arXiv submission needs. arXiv typesets the LaTeX itself but
# runs neither pandoc nor biber, so it needs the *formatted* bibliography; the
# .bib stays in build/ as an intermediate.
KEEP := tex bbl pdf

# The figures are handled separately, and on purpose. They are conditional
# outputs -- without mermaid-cli none are produced -- and their number is the
# number of mermaid blocks in the paper rather than a fixed list, so they are
# copied by collect instead of being declared as targets. The cost: deleting
# figures/ alone does not trigger a rebuild. Run `make clean` first if the
# figures need to be regenerated.

collect:
	@for ext in $(KEEP); do \
	  src=$(DIR)/$(NAME).$$ext; \
	  if [ -f "$$src" ]; then cp -f "$$src" . && echo "  $(NAME).$$ext"; fi; \
	done
	@if ls $(DIR)/figures/*.pdf >/dev/null 2>&1; then \
	  rm -rf figures && mkdir figures && cp -f $(DIR)/figures/*.pdf figures/ \
	  && echo "  figures/ ($$(ls $(DIR)/figures/*.pdf | wc -l) figures)"; \
	fi

tex: $(DIR)/$(NAME).tex
	@$(MAKE) --no-print-directory collect

pdf: $(DIR)/$(NAME).pdf
	@$(MAKE) --no-print-directory collect

arxiv: $(DIR)/$(NAME)-arxiv.tar.gz
	@$(MAKE) --no-print-directory collect
	@cp -f $< . && echo "  $(NAME)-arxiv.tar.gz"

clean:
	@rm -rf $(DIR) figures $(NAME)-arxiv
	@rm -f $(NAME).* $(NAME)-arxiv.tar.gz

help:
	@echo "Available rules:"
	@echo "  tex    Convert the paper to LaTeX and regenerate its bibliography"
	@echo "  pdf    The above, then typeset the PDF"
	@echo "  arxiv  The above, then package $(NAME)-arxiv.tar.gz"
	@echo "  clean  Drop $(DIR)/ and every generated file"
