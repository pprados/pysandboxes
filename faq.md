## Comment activer que les logs importants ?
```python
import logging
logging.getLogger("Pysandboxies").setLevel(logging.INFO)
logging.getLogger("pysandboxies").setLevel(logging.WARNING)
```
## Comment ajouter le PID dans les logs ?
La sandbox et le programme original n'utilisent pas le même processus. Cela permet
l'isolation. Pour savoir si les traces viennent de l'un ou de l'autre processus,
nous vous conseillons d'ajouter le PID dans le format des logs.
```
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-5s [%(process)d] %(name)s:%(message)s'
)
```