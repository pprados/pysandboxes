# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# crewai keeps its data under ~/.local/share on Linux.
expose-rw=~/.local/share/crewai-demo
expose-rw=~/.local/share/crewai/credentials

# crewai, numpy and chromadb map more than firejail's default 300m of address space: the
# import or the first thread then dies with a MemoryError.
firejail.rlimit-as=1g
