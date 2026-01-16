# %% run
import asyncio

import pytest

from .sample import config_path, async_forty_two, \
    async_sanboxes, bridge_async_to_sync
from pysandboxes import run


def test_run() -> None:
    """
    Invoke the sandboxes.run() function
    """
    assert config_path.exists()
    run(async_forty_two(), config_path=config_path)


def test_run_and_async_sanboxes() -> None:
    # An async method, call a async method with sandboxes ressource manager
    run(async_sanboxes(config_path), config_path=config_path)


# FIXME
# Le problème est que je dois lancer un run() dans le même thread que la loop
# mais que ensuite, lorsque j'appel un truc synchrone, ce dernier ne pas récupérer le résultat
# puisque la boucle de tourne plus.
# Est-ce qu'il faut que j'identifie le pb pour le signaler simplement ?
# Ne pas oublier de comparer avec la version git d'avant.
# Voir l'explication du problème ici: https://g.co/gemini/share/fb0d5fd5c641

# Est-ce très en amont qui faut utiliser un thread pour l'invocation synchrone ?
# @pytest.mark.skip(reason="Not working")
def test_run_and_sync_sanboxes() -> None:
    # An async method, call a sync method with sandboxes ressource manager
    # asyncio.run(bridge_async_to_sync(config_path))  # L'exception est bien remonté dans le run_until_finish
    run(bridge_async_to_sync(config_path), config_path=config_path)



