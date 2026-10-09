LAST_FRAME ?= 10
FPS ?= 12

.PHONY: gif gif-full gif-partial check rehearse rehearse-full rehearse-partial

gif: gif-full gif-partial

gif-full: check
	asciinema rec --overwrite --cols 110 --rows 46 -c "bash ./demo.sh full" coding-agents-full.cast
	agg --fps-cap $(FPS) --last-frame-duration $(LAST_FRAME) coding-agents-full.cast coding-agents-full.gif
	gifsicle -O3 --no-loopcount --batch coding-agents-full.gif
	@if gifsicle --info coding-agents-full.gif | grep -q 'loop'; then echo 'GIF still loops' >&2; exit 1; else echo 'GIF plays once'; fi

gif-partial: check
	asciinema rec --overwrite --cols 110 --rows 42 -c "bash ./demo.sh partial" coding-agents-partial.cast
	agg --fps-cap $(FPS) --last-frame-duration $(LAST_FRAME) coding-agents-partial.cast coding-agents-partial.gif
	gifsicle -O3 --no-loopcount --batch coding-agents-partial.gif
	@if gifsicle --info coding-agents-partial.gif | grep -q 'loop'; then echo 'GIF still loops' >&2; exit 1; else echo 'GIF plays once'; fi

rehearse: rehearse-full rehearse-partial

rehearse-full:
	PAUSE=0 TYPE_DELAY=0 INTERACTION_PAUSE=0 bash ./demo.sh full

rehearse-partial:
	PAUSE=0 TYPE_DELAY=0 INTERACTION_PAUSE=0 bash ./demo.sh partial

check:
	@for tool in asciinema agg gifsicle; do \
		command -v $$tool >/dev/null || { echo "Missing $$tool"; exit 1; }; \
	done
