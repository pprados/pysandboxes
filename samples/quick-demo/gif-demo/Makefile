# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Record the quick demo and rebuild ../quick-demo.gif. `make check` lists the missing tools.
# PAUSE (seconds after each command) and TYPE_DELAY (seconds per character) set the pace:
#   make PAUSE=6
# LAST_FRAME is how long the GIF holds its closing message before it starts again.
LAST_FRAME ?= 10
# A terminal needs no more: a higher rate only makes the GIF bigger.
FPS ?= 10

TOOLS := asciinema agg bwrap gifsicle
install_asciinema := sudo apt install asciinema
install_agg := cargo install --git https://github.com/asciinema/agg
install_bwrap := sudo apt install bubblewrap
install_gifsicle := sudo apt install gifsicle

.PHONY: gif rehearse check

gif: check
	asciinema rec --overwrite --cols 110 --rows 12 -c ./demo.sh quick-demo.cast
	agg --fps-cap $(FPS) --last-frame-duration $(LAST_FRAME) quick-demo.cast ../quick-demo.gif
	gifsicle -O3 --batch ../quick-demo.gif

rehearse:
	PAUSE=0 TYPE_DELAY=0 ./demo.sh

check:
	@$(foreach t,$(TOOLS),command -v $(t) >/dev/null || { echo "Missing $(t): $(install_$(t))"; missing=1; };) \
	exit $${missing:-0}
