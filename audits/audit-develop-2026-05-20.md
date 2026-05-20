# Audit de la branche `develop` — PySandboxes

**Date** : 2026-05-20
**Branche auditée** : `develop` @ `0e7831c`
**Écart avec `master`** : 127 commits, 2099 fichiers (dont ~95 % de bruit : `wiki/bmad/`, `.agents/`, `_bmad/`, `.ia_backup/`, `graphify-out/`, `uv.lock`)
**Périmètre** : `pysandboxes/`, `pysandboxes/templates/`, `samples/`, `tests/`, `README.md`, `wiki/*.md`, `Makefile`, `pyproject.toml`, `.github/workflows/`
**Hors périmètre** (généré ou outillage agent, non produit) : `graphify-out/`, `wiki/bmad/`, `.ia_backup/`, `_bmad/`, `.agents/`, `.cursor/`, `.codex/`, `lat.md/`, `dist/`

## Synthèse

`develop` n'est pas dans un état publiable. Le constat structurant est un **schéma répété** : plusieurs protections sont décrites dans le code sans y être branchées.

| Protection | État réel |
|---|---|
| `guard_pickle.py` (284 l.) | jamais importé en production — §1.1 |
| `guard_self.py` (anti-altération) | `return module` inchangé, `activate_guard()` vide — §1.11 |
| `os.system`/`exec*`/`spawn*`/`fork`/`popen` | 19 lignes `# DENY` en commentaire, zéro patch — §1.10 |
| `modules_blacklist.txt` (ctypes, subprocess…) | sert uniquement à générer un commentaire — §1.5 |
| `patch_rules` de `guard_envs` | rend `{}` hors mode learning — §1.14 |
| `REPLACE` (backend firejail) | `False # TODO`, 4 branches mortes — §1.8 |

Un lecteur du code — humain ou agent — conclut de chacun qu'une protection existe. Aucune n'est active. C'est la fausse assurance qui est le problème central de cette branche, plus encore que chaque trou pris isolément.

Trois constats dominent ensuite :

1. **La décision d'autorisation du garde fichiers est aveugle aux liens symboliques** : elle refuse un fichier hors périmètre, puis autorise un lien qui le désigne — démontré en interrogeant la fonction d'autorisation, et `os.symlink` ne valide jamais sa cible (§1.0). L'exploitation de bout en bout n'a pas pu être exécutée ici et reste à confirmer, mais le mécanisme est établi au niveau des sources. C'est une faute de logique réparable, non une limite assumée du monkey-patching, et elle n'est pas divulguée.
2. **Le filtrage d'imports est inactif dans la quasi-totalité des samples** : 10 fichiers portent un `python-import=*` (§1.4, §2.10), et 5 configurations top-level n'ont aucune règle d'import — ce qui, à cause de `guard_import.py:424`, équivaut silencieusement à tout autoriser (§1.9). Combiné à `os.system` non patché (§1.10), le niveau Python n'oppose alors aucune barrière.
3. **Les garde-fous du projet ne gardent rien** : `make lint` échoue, `make test` est un no-op silencieux, la CI n'exerce que 2 samples sur 11 et une seule version de Python sur 4 déclarées, et `CLAUDE.md` — l'autorité lue par tous les contributeurs et agents — est faux sur six points, dont un chemin de fichier inexistant.

Le point 3 explique mécaniquement les points 1 et 2 : rien dans la chaîne d'intégration n'était en mesure de les arrêter.

À l'inverse, deux choses sont solides et méritent d'être dites : le parser de configuration est **strict et fail-closed** sur les directives inconnues (§1.6), et `README.md` / `wiki/weaknesses.md` sont d'une honnêteté inhabituelle sur les limites du modèle — ils documentent explicitement les évasions par `__subclasses__` et `sys.meta_path`. Le problème n'est pas la sincérité du discours, c'est l'écart entre ce discours et ce que l'outillage vérifie.

### Priorités

| # | Sévérité | Sujet | Effort |
|---|---|---|---|
| §1.0 | **CRITIQUE** | Cécité aux symlinks (`realpath` + validation de la cible de `os.symlink`/`os.link`) — et rejouer le scénario de bout en bout | moyen |
| §1.1 | **CRITIQUE** | Câbler ou supprimer `guard_pickle` | faible à moyen |
| §1.9 | **CRITIQUE** | Distinguer « aucune règle d'import » (refuser) de `*` (tout autoriser) | faible (mais cassera des samples) |
| §1.10 | **CRITIQUE** | Patcher réellement `os.system`/`exec*`/`spawn*`/`fork`/`popen`, ou retirer les 19 commentaires `# DENY` | moyen |
| §1.11 | HAUTE | Terminer `guard_self` (`GuardModule` sur `sys`) — ferme §1.3 à la racine | moyen |
| §1.12 | HAUTE | `bind` fail-open, `assert False` comme contrôle, exemption AF_UNIX | faible à moyen |
| §2.1 | HAUTE | Réparer `make lint` (20 erreurs mypy) | faible |
| §2.2 | HAUTE | `make test` no-op + noms de cibles faux dans `CLAUDE.md` | faible |
| §2.3 | HAUTE | Réactiver les 9 samples désactivés en CI | faible à moyen |
| §1.4 §1.5 | HAUTE | `python-import=*` silencieux ; blacklist non appliquée ; configs de samples issues du learning brut | moyen |
| §1.2 §1.3 | HAUTE | Passer les 5 évasions `skip`/vertes en `xfail(strict)` | faible |
| §3.1 | HAUTE | Corriger `CLAUDE.md` (backends, `uv`, 78/120, cibles make, semgrep) | faible |

Les lignes à effort « faible » se traitent en une passe et rendraient l'audit suivant nettement plus lisible.

*Note de lecture : la numérotation des sections suit l'ordre de découverte, pas la sévérité — §1.9 et §1.10 sont critiques bien qu'elles suivent des sections moyennes. Le tableau ci-dessus est l'ordre de traitement recommandé.*

## Ce qui a été vérifié / non vérifié

| Vérification | Résultat |
|---|---|
| `make lint` | **ÉCHEC** — 20 erreurs mypy |
| `make test` | **ne fait rien** (« Nothing to be done for 'test' ») |
| `uv run pytest tests/unit_tests` | 371 passés, 6 ignorés, 2 xfailed |
| `uv run pytest tests/unit_tests/test_escape_pysandbox.py` | 1 passé, 4 ignorés, 2 xfailed |
| Tests d'intégration / conteneurs | **NON VÉRIFIÉS** — nécessitent firejail/bwrap/qemu/minikube absents de cet environnement. Aucune conclusion n'est tirée sur leur état. |
| Secrets versionnés (`.env`) | OK — non tracké par git, couvert par `.gitignore:130` |

---

# 1. Sécurité

## 1.0 CRITIQUE — le contrôle d'accès fichiers est aveugle aux liens symboliques (décision d'autorisation démontrée ; exploitation de bout en bout non exécutée)

C'est la trouvaille principale de cet audit. Contrairement aux faiblesses assumées dans `wiki/weaknesses.md` (introspection, `__subclasses__`, code compilé), il ne s'agit pas d'une limite inhérente au monkey-patching : c'est une **faute de logique**, réparable, et non divulguée.

### Cause : asymétrie de canonicalisation

Les chemins des **règles** sont canonicalisés — les liens symboliques sont résolus (`guard_files.py:186`, et `:256` pour les chemins Python) :

```python
resolved = Path(Path(s_path).expanduser()).resolve().absolute()
```

Les chemins **accédés** ne le sont pas. `guard_files.py:477`, dans `_apply_dest_to_src_rules`, la fonction d'autorisation centrale :

```python
fake_path: str = _os_path_abspath(str(path))   # abspath, PAS realpath
```

`os.path.abspath` normalise `..` lexicalement mais **ne résout pas les liens symboliques** (`_os_path_realpath` est bien capturé ligne 134 — il n'est simplement pas utilisé ici ; le patch d'`os.path.realpath` est d'ailleurs commenté, l. 713 et 1558). L'autorisation porte donc sur un chemin non canonique, tandis que l'appel système réel (`func(remapped, ...)`, l. 631) suit les liens.

### Aggravant : `os.symlink` ne valide sa cible que si elle est absolue

`guard_files.py:1152-1157`, `_wrap_os_symlink` :

```python
        if str(src).startswith("/"):
            remapped_src, _ = _apply_dest_to_src_rules(
                src, write=False, accept_src=True
            )
        else:
            remapped_src = src  # Relative link      <- aucun contrôle
```

Le contrôle de la cible **existe**, mais il est conditionné à un chemin absolu. Une cible **relative** contourne entièrement la vérification. `os.symlink("../../../../etc/passwd", "<répertoire_autorisé>/lien")` est donc accepté sans examen de la cible.

C'est plus embarrassant qu'une absence de contrôle : le garde sait qu'il doit valider la cible, et l'attaquant choisit la forme d'écriture qui esquive la validation. Un `os.path.abspath(src)` avant le test suffirait à fermer cette variante — mais pas la cécité de fond aux liens décrite ci-dessus, puisque l'évaluation reste faite sur un chemin non résolu.

### Ce qui est démontré, et ce qui ne l'est pas

**Démontré** — exécuté sur `develop`, avec pour seule règle `expose-rw=<répertoire autorisé>`, en interrogeant directement la fonction d'autorisation :

```
[1] verdict sur le fichier cible, hors périmètre  -> (None, None)                          = REFUSÉ
[2] os.symlink(cible_hors_périmètre, allowed/innocent.txt)                                 = ACCEPTÉ
[3] verdict sur le lien, dans le périmètre        -> ('…/allowed/innocent.txt', None)      = AUTORISÉ
```

Le contraste entre **[1]** et **[3]** est le cœur du défaut : `_apply_dest_to_src_rules` refuse le fichier, puis autorise un chemin qui désigne ce même fichier. C'est le verdict de la fonction d'autorisation elle-même, pas une inférence.

**Non exécuté** : l'exploitation de bout en bout dans un sandbox réel. En toute rigueur, je n'ai pas pu la lancer — le helper de test `activate_guard_files_rules` et `guard_files.activate_guard()` ne posent que `_rules` sans installer les patches sous pytest (vérifié : `hasattr(open, "__pysandbox__")` vaut `False`, et l'accès direct au fichier cible passe), et le CLI `python-sb` n'a pas pu démarrer dans cet environnement (`python_sb.py:131` code `/tmp` en dur, monté en lecture seule ici). Une première version de cette section affirmait avoir lu le contenu « à travers le sandbox » : c'était en réalité un `open()` **non patché**. Corrigé.

**Pourquoi la sévérité reste CRITIQUE malgré cela.** Le mécanisme est établi au niveau des sources, sans exécution requise. `_wrap_filename` (`:621-631`) montre que la décision et l'appel système portent sur le même chemin non résolu :

```python
remapped, rule = _apply_dest_to_src_rules(file, write=write)   # décision sur l'abspath
...
return func(remapped, *args, **kwargs)                          # appel réel sur ce même abspath
```

Tous les wrappers fichiers routent leur décision par cette fonction, puis transmettent le chemin non canonicalisé à la fonction d'origine, qui suit les liens. Un chemin autorisé à tort est donc, par construction, un accès effectif. Il ne manque que la mise en scène.

**Direction écriture — inférée, non observée.** Sous `expose-rw`, la branche `write=True` (`:488`) ne lève que si `rule.write` est faux ; un lien placé sous une règle en écriture devrait donc passer le contrôle et rendre la cible inscriptible (`~/.ssh/authorized_keys`, `~/.bashrc`, un fichier de configuration). Ce raisonnement suit le même chemin de code que la lecture, mais **je ne l'ai pas exécuté** : à traiter comme une hypothèse à vérifier, pas comme un constat. Le même raisonnement s'applique à `os.link` (`:1474`).

**À faire en priorité** : rejouer ce scénario avec un vrai `python-sb` sur un hôte où `/tmp` est inscriptible, dans les deux directions, et pour chacun des providers OS. Une couche OS-sandbox (firejail, bwrap, landlock) peut très bien intercepter l'accès là où la couche Python le laisse passer — c'est précisément l'argument de défense en profondeur du produit. Mais la couche Python, seule (`os-sandbox=subprocess`, le défaut de tous les samples), ne tient pas.

### Correction

Canonicaliser le chemin accédé avec `realpath` avant l'évaluation des règles, **et** valider la cible de `os.symlink`/`os.link` comme un accès de plein droit. Attention : `realpath` seul laisse subsister une fenêtre TOCTOU (le lien peut être créé entre la vérification et l'appel système) ; la fermeture complète demande une résolution relative à un descripteur (`O_NOFOLLOW`, `openat` avec `dir_fd`), ou de s'appuyer sur la couche OS-sandbox pour ce périmètre. Au minimum, l'écart actuel — règles résolues, accès non résolus — doit disparaître.

### Défauts adjacents dans le même wrapper

Deux bugs francs dans `_wrap_os_symlink`, non couverts par les tests :

| Ligne | Code | Problème |
|---|---|---|
| 1130 | `if isinstance(str, int) or isinstance(dst, int):` | teste l'objet-type `str` contre `int` — toujours faux. Devait être `isinstance(src, int)` : un `src` passé comme descripteur n'est pas détecté. |
| 1140 | `if isinstance(dst, bytes): src = os.fsdecode(dst)` | affecte `src` au lieu de `dst`. Un `dst` de type `bytes` reste en `bytes` **et** écrase `src`. |

## 1.1 CRITIQUE — `guard_pickle.py` n'est jamais câblé : évasion `pickle.loads` → `os.system` active

`pysandboxes/guard_pickle.py` (284 lignes) n'est importé par **aucun** module de production. Vérification :

```
$ rg -n 'guard_pickle' pysandboxes/
pysandboxes/guard_pickle.py:26,121,248,274   # auto-références uniquement
```

Les gardes réellement activés par `py_sandbox.py` sont : `guard_envs`, `guard_files`, `guard_import`, `guard_provider`, `guard_self`, `guard_socket`. **Pas `guard_pickle`.**

Le dépôt le sait et l'a inscrit dans sa suite de tests — `tests/unit_tests/test_escape_pysandbox.py:60` :

```python
@pytest.mark.xfail(
    strict=True,
    reason="pickle.loads() escape not blocked: guard_pickle is never wired "
    "into the sandbox pipeline",
)
def test_escape_with_pickle_allowed() -> None:
    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_ALLOWED'\ntRp1\n."
```

**Impact** : du code non fiable dans le sandbox exécute une commande shell arbitraire via les opcodes pickle, sans passer par aucun garde d'import. C'est l'évasion la moins coûteuse de tout le produit : une ligne, aucune introspection.

**Aggravant** : le module existe, est documenté dans ses propres docstrings comme la protection pickle, et porte 3 suppressions `nosemgrep` — un lecteur du code conclut raisonnablement que pickle est protégé. Il ne l'est pas. Un module de sécurité mort est pire que pas de module : il produit une fausse assurance.

**À décider** : soit câbler `guard_pickle` dans `py_sandbox.activate_sandboxes`, soit le supprimer et documenter explicitement que pickle n'est pas protégé au niveau Python. L'état actuel — présent mais inerte — n'est pas tenable.

## 1.2 CRITIQUE — un test qui *passe* atteste que le garde fichiers est contournable

`tests/unit_tests/test_escape_pysandbox.py:12`, `test_escape_with_closure`, n'est ni `skip` ni `xfail`. Il **passe** :

```python
def test_escape_with_closure() -> None:
    import io
    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents
    assert original_open.__module__ in ["_io", "io"], "Not the _original io.open"
```

La suite de tests **affirme comme comportement attendu** que `io.open.__closure__[0].cell_contents` restitue le `io.open` original non patché. Tout le garde fichiers (`guard_files.py`, 1684 lignes) tombe en une ligne.

C'est cohérent avec la stratégie de patch (le wrapper doit conserver l'original) et `wiki/weaknesses.md:6` le concède en termes généraux. Mais l'encoder en test *vert* plutôt qu'en `xfail(strict)` inverse le signal : le jour où quelqu'un durcit la fermeture, ce test échouera et sera « réparé » en restaurant l'évasion. Les autres évasions du même fichier utilisent `xfail(strict=True)`, qui est le bon mécanisme. Incohérence à corriger.

## 1.3 HAUTE — 4 évasions connues neutralisées en `skip`, sans échéance

Même fichier, quatre tests `@pytest.mark.skip` :

| Ligne | Évasion | Raison inscrite |
|---|---|---|
| 21 | `object.__subclasses__()` → atteindre `pysandboxes.guard_import` et poser `_rules = ()` | « not yet blocked » |
| 53 | tronquer `sys.meta_path` pour retirer le loader du sandbox | « TODO: block sys.meta_path escape » |
| 106 | `fn.__globals__` / `gen.gi_frame.f_globals` | « not yet blocked » |
| 133 | `getattr(type, "__sub"+"classes"+"__")`, chaînes `chr()`, décodage hex | « not yet blocked » |

`skip` ne surveille rien : si l'une de ces évasions était fermée par effet de bord, personne ne le saurait, et si une régression les rouvrait plus largement, rien ne le signalerait. `xfail(strict=True)` — déjà utilisé pour pickle dans le même fichier — est le mécanisme correct et transforme ces 4 tests en sentinelles. C'est un changement à coût quasi nul avec un gain de signal réel.

**Divulgation** : `wiki/weaknesses.md` couvre correctement `__subclasses__` (l. 7) et `sys.meta_path` (l. 8). Ne sont **pas** divulgués : l'évasion `pickle`, `__globals__`/`f_globals`, et le contournement par noms obfusqués.

## 1.4 HAUTE — `python-import=*` annule toute la whitelist, et un sample livré l'utilise

`pysandboxes/guard_import.py:138` :

```python
if "*" in white_list:
    white_list = ["*"]
```

Un seul `python-import=*` réduit la whitelist à « tout autoriser ». Or `samples/crewai-demo/crewai_demo/.py-sandboxes` contient, **après ~60 lignes de whitelist soigneusement curée**, la ligne `python-import=*`. Le sample :

- annule sa propre curation ;
- autorise donc `ctypes`, `subprocess`, `marshal`, `pty`, etc. ;
- déclare par ailleurs explicitement `python-import=subprocess` sous un commentaire `# ⚠ Dangerous!`.

Les samples sont la documentation de référence de l'usage correct. Livrer un sample dont le garde d'import est désactivé enseigne l'inverse du modèle du produit. À noter que le wildcard lui-même est un choix défendable comme échappatoire d'urgence, mais alors il devrait produire un avertissement bruyant au démarrage — aujourd'hui il est silencieux.

## 1.5 HAUTE — `modules_blacklist.txt` est purement cosmétique, et le mode learning produit les configs permissives des samples

`pysandboxes/modules_blacklist.txt` liste les modules que le projet lui-même juge dangereux :

```
ctypes bdb faulthandler mmap pdb cProfile subprocess webbrowser
atexit inspect code codeop pkgutil importlib posix
```

Ce fichier n'est lu qu'en **deux** endroits, tous deux dans le générateur de configuration du mode learning (`guard_import.py:598` et `:605`) :

```python
black_list = set(resources.read_text(__name__, "modules_blacklist.txt").split())
...
    if learn_rule.name in black_list:
        danger_result.add(learn_rule.name)
...
    if danger_result:
        result.append("# ⚠ Dangerous!")
```

Il ne joue **aucun rôle dans l'application des règles**. Écrire `python-import=ctypes` est accepté sans le moindre avertissement à l'exécution — et `ctypes` donne accès à la mémoire du processus et aux appels systèmes, ce qui rend l'ensemble des gardes Python purement consultatif. La seule conséquence de la blacklist est un commentaire dans un fichier généré.

**Conséquence directe et observable** : le commentaire `# ⚠ Dangerous!` suivi de `python-import=subprocess` dans `samples/crewai-demo/crewai_demo/.py-sandboxes` n'est pas une décision humaine assumée — c'est la sortie littérale de ce générateur, commitée telle quelle. La même config liste aussi `importlib`, `inspect`, `os` et `pickle`, tous signalés dangereux par la blacklist du projet, puis termine par `python-import=*` (§1.4) qui rend le tout sans objet.

Le mode learning est conçu pour produire un point de départ à réviser ; le dépôt versionne sa sortie brute comme documentation de référence. Deux corrections distinctes s'imposent : faire de la blacklist un mécanisme d'application (au minimum un avertissement bruyant au démarrage), et réviser à la main les configs de samples au lieu de commiter la sortie du learning.

## 1.6 MOYENNE — `include` est la seule directive exemptée de la validation stricte, et échoue en silence

Le parser est par ailleurs **strict et fail-closed** : toute directive non reconnue survit jusqu'à `py_sandbox.py:288-298` et lève `ConfigSyntaxError`. C'est le bon comportement et il mérite d'être noté.

`include` échappe à cette règle. `py_sandbox.py:182-217` :

```python
if filename not in includes:
    try:
        if filename.exists():      # fichier absent -> ignoré en silence
            ...
    except PermissionError:
        pass  # Ignore   # fichier illisible -> ignoré en silence
```

Conséquence mesurée — 5 configs de samples incluent des fichiers inexistants :

| Config | Include manquant |
|---|---|
| `samples/crewai-demo/crewai_demo/.py-sandboxes` | `.py-sandboxes.pycharm` (**deux fois**) |
| `samples/google-adk-demo/google_adk_demo/.py-sandboxes` | `.py-sandboxes.pycharm` (**deux fois**) |
| `samples/mcp-client/.py-sandboxes` | `.py-sandboxes.pycharm` |
| `samples/mcp-server/mcp_server/.py-sandboxes` | `.py-sandboxes.pycharm` |

(Les includes de `./.local.py-sandboxes`, `~/.config/py-sandboxes/…` et `/etc/py-sandboxes/…` dans `mcp-server-demo` et `strands-agents-demo` sont vraisemblablement optionnels par conception — surcharges utilisateur.)

Dans un modèle purement whitelist, un include perdu retire des permissions : cela **fail-closed**, donc pas d'escalade de privilèges. Le défaut est fonctionnel et diagnostique : le sample perd silencieusement ses allowances et l'utilisateur débogue un refus dont la cause est invisible. `include` d'un chemin explicitement nommé devrait être une erreur ; l'optionnalité mérite une syntaxe distincte (`-include`, à la manière de `make`).

**Bug adjacent** — `py_sandbox.py:212` : la récursion passe `root_path` (le répertoire de la config racine) et non le parent du fichier inclus. Un include relatif écrit *dans* un fichier inclus se résout donc contre le répertoire racine, pas contre celui qui l'inclut. Sémantique surprenante, non testée.

## 1.7 MOYENNE — le gate semgrep documenté n'est pas le gate réel

Trois divergences :

1. `CLAUDE.md` prescrit `semgrep --config=p/security-audit`. Le `Makefile:138` exécute `uvx semgrep --config auto`. Ce ne sont pas les mêmes règles.
2. `.semgrep.yml` désactive **globalement** deux règles :
   ```yaml
   rule-settings:
     - id: python.lang.security.audit.eval-detected.eval-detected
       enabled: false
     - id: python.lang.security.audit.exec-detected.exec-detected
       enabled: false
   ```
   Désactiver globalement la détection d'`eval`/`exec` dans un produit dont la raison d'être est d'empêcher l'exécution de code arbitraire supprime précisément le détecteur qui compte. Deux usages légitimes existent (`remote/python_in_sb.py:203,221`) — ils sont déjà couverts par des `nosemgrep` locaux. Le désactivage global est donc redondant *et* aveuglant : tout nouvel `eval`/`exec` introduit ailleurs passera sans bruit.
3. `CLAUDE.md` impose le format `# nosemgrep: <rule-id> — reason: <justification>`. Sur 15 suppressions dans `pysandboxes/`, **13 n'ont aucune clause `reason:`** — dont les 3 de `guard_pickle.py` et les 2 d'`exec` de `python_in_sb.py`. Le commit `a6e3ec0` annonce « restore semgrep suppressions with justifications » ; il n'a justifié que 2 sur 15.

Fichiers concernés sans justification : `_os_sandbox.py:58`, `guard_pickle.py:164,187,193`, `remote/main_sandbox.py:227,317`, `remote/python_in_sb.py:203,221`, `remote/unshare_setup.py:282`, `remote/sse_server_daemon.py:111`, `remote/qemu_image.py:275`, `remote/tools.py:290,305`.

## 1.8 MOYENNE — interrupteur de sécurité mort dans le backend principal

`pysandboxes/remote/firejail_sse_daemon.py:58` :

```python
REPLACE = False  # TODO: firejail
```

Ce drapeau garde 4 branches (l. 315, 473, 594). Celle de la ligne 473 remplace l'intégralité des règles fichiers par :

```python
files_parse_rules([ConfigLine("expose-rw=/", Path(), 0)], [])
```

soit **tout le système de fichiers en lecture-écriture**, désactivant le garde fichiers Python et ne laissant que la couche firejail.

Ce n'est pas une vulnérabilité active — le drapeau est `False`. Mais c'est du code mort, non testé, non couvert, dans le daemon du backend présenté comme principal, dont l'inversion d'un booléen suffirait à éventrer une couche de défense. Dans un produit de sécurité, ce genre de branche se supprime ou se transforme en option explicite et testée, pas en `TODO`.

---

## 1.9 CRITIQUE — aucune règle `python-import=` ≡ tout autoriser, en silence, et 5 samples sont dans ce cas

`guard_import.py:424` :

```python
else:
    if _rules and _rules[0] != "*":     # <- _rules vide (falsy) => bloc entier sauté
        if (not module_name.startswith("pysandboxes")
                and module_name not in _rules):
            raise RuleModuleNotFoundError(...)
return new_spec                          # <- retourné sans contrôle
```

`_rules` vaut `()` par défaut. Une configuration **sans aucune ligne `python-import=`** est donc falsy, le bloc de filtrage n'est jamais exécuté, et tout import passe. L'effet est identique à `python-import=*` (§1.4), à ceci près qu'il est **invisible** : aucune ligne du fichier ne le signale.

C'est une violation directe du principe affiché par le produit (« Everything forbidden by default, explicit permissions required »). Un relecteur qui ouvre une config sans directive d'import conclut logiquement que le deny-by-default s'applique. C'est l'inverse.

Configurations top-level de samples concernées (vérifié : `grep -c '^python-import='` = 0) :

```
samples/agno-demo/.py-sandboxes
samples/crewai-demo/.py-sandboxes
samples/mcp-server-demo/.py-sandboxes
samples/pydantic-ai-demo/.py-sandboxes
samples/strands-agents-demo/.py-sandboxes
```

Ce sont les fichiers réellement chargés lorsqu'on suit l'instruction `cd samples/<nom>` des README. Cinq samples sur quatorze n'ont donc aucun filtrage d'import actif — dont `mcp-server-demo`, précisément l'un des deux seuls exercés en CI (§2.3).

Le correctif est d'une ligne — distinguer « aucune règle » (refuser) de « règle `*` » (tout autoriser) — mais il cassera vraisemblablement plusieurs samples, ce qui est exactement l'information utile.

**Défaut adjacent, même ligne** : le test est `module_name.startswith("pysandboxes")`, pas une égalité ni un préfixe pointé. Un module nommé `pysandboxesx` ou `pysandboxes_evil` déposé sur `sys.path` est donc traité comme le paquet de confiance et échappe à la whitelist.

## 1.10 CRITIQUE — `os.system`, `os.exec*`, `os.spawn*`, `os.fork`, `os.popen` sont refusés en commentaire seulement

`guard_files.py:1503-1533`, dans `_default_rules` — la table qui définit réellement les fonctions patchées :

```python
    # DENY os.execv
    # DENY os.execve
    ...        (8 variantes os.exec*)
    # DENY os.spawnv
    ...        (8 variantes os.spawn*)
    # DENY os.popen
    # DENY os.fork
    # DENY os.forkpty
    # DENY os.system
```

Ce sont **19 commentaires**. Aucune de ces fonctions n'a d'entrée dans la table : aucune n'est patchée, aucune n'est refusée. Il n'existe par ailleurs aucun garde de processus séparé dans le paquet.

Or `os` est whitelisté dans la majorité des configs de samples, et §1.9 montre que 5 samples n'ont aucun filtre d'import du tout. Au niveau Python seul, du code non fiable exécute donc `os.system("...")` — soit un shell arbitraire — sans rencontrer le moindre contrôle.

L'intention était manifestement de les refuser : quelqu'un a écrit les 19 lignes. Elles n'ont jamais été implémentées, et le commentaire donne au lecteur du code l'impression exactement inverse. C'est le même schéma que `guard_pickle` (§1.1) et `guard_self` (§1.11) : une protection décrite, non branchée.

*Portée* : `os-sandbox=firejail|bwrap|unshare|landlock|qemu` peut intercepter l'exécution au niveau OS — c'est l'argument de défense en profondeur, et il est légitime. Mais `os-sandbox=subprocess` (le défaut de 13 samples sur 14) n'apporte pas cette barrière, et `agno-demo` va jusqu'à `none` (§2.10).

## 1.11 HAUTE — `guard_self.py` est entièrement inerte : c'est la cause racine de deux évasions connues

Le module dont la fonction unique est la protection anti-altération ne fait rien. `guard_self.py:56-76` :

```python
def _global_patch_in_sys_module(module: ModuleType) -> ModuleType:
    # TODO GuardModule not working
    # guard_module = GuardModule(
    #     module.__name__, _original=module,
    #     _guard_attributs=("meta_path", "modules"))
    # return guard_module
    return module          # <- rendu inchangé

def patch_rules(learn: bool) -> Dict[str, Callable]:
    return {}

def activate_guard() -> None:
    pass  # Nothing at this time
```

La classe `GuardModule.__setattr__` (l. 47-52) lèverait bien `RuleAttributeError` sur l'écriture d'un attribut protégé — mais `sys` n'est jamais enveloppé dedans, et les deux points d'entrée du module sont des coquilles vides.

**C'est l'explication des deux évasions `skip` de §1.3** : `test_escape_with_subclasses` attend une `RuleAttributeError` lors de l'écriture de `guard_import._rules`, et `test_escape_with_meta_path` l'attend lors du remplacement de `sys.meta_path`. Les deux tests attendent précisément ce que `GuardModule` fournirait. L'échafaudage du correctif existe, il n'a jamais été terminé. Aujourd'hui, `sys.meta_path = sys.meta_path[1:]` retire silencieusement tous les gardes d'import.

Cette information change la lecture de §1.3 : ces évasions ne sont pas « pas encore étudiées », elles ont une correction commencée et abandonnée sous un `TODO`.

## 1.12 HAUTE — filtrage réseau : fail-open sur `bind`, exemption AF_UNIX, et contrôle par `assert`

Trois défauts distincts dans `guard_socket.py`.

**1. `bind` est fail-open sur une forme d'adresse inattendue** (l. 971-978) :

```python
        else:
            logger.warning(
                "Unexpected address format for bind: %s. Skipping IP rule check.",
                address,
            )
        func(self, address)          # <- exécuté quand même
```

Une adresse qui n'est ni un tuple `(str, int)` ni une `str` (AF_UNIX) — un chemin en `bytes`, un tuple AF_INET6 à 4 éléments, une adresse AF_NETLINK/AF_PACKET — produit un avertissement de log, puis l'appel réel s'exécute sans contrôle.

**2. `connect` utilise `assert False` comme barrière** (l. 1015-1020). Contrairement à `bind`, `connect` **ne** laisse pas passer : il journalise puis exécute `assert False`. Mais un `assert` est supprimé par l'interpréteur sous `python -O` / `PYTHONOPTIMIZE`. Sous cette option — courante en production — le contrôle disparaît et `connect` devient fail-open comme `bind`. Un contrôle de sécurité ne doit jamais reposer sur une assertion ; il faut lever une exception réelle. (Le `# noqa: B011` sur la ligne montre que le linter l'avait signalé.)

**3. Les adresses AF_UNIX sont explicitement exemptées de toute règle** (l. 966-970 pour `bind`, l. 1010-1014 pour `connect`) :

```python
        elif isinstance(address, str):  # AF_UNIX
            logger.debug(
                "Allowing connect to AF_UNIX address (not subject to IP rules): %s",
                address,
            )
```

Les règles `net=` ne portent que sur IP ; les sockets de domaine Unix sont autorisées sans restriction. Du code non fiable peut donc se connecter à toute socket Unix accessible sur le système de fichiers — `/var/run/docker.sock` (équivalent root sur l'hôte), l'agent SSH, D-Bus, systemd. Le garde fichiers ne couvre pas davantage les chemins de socket. C'est un trou d'exfiltration et d'escalade qui n'est documenté ni dans `wiki/weaknesses.md` ni dans `wiki/proxy.md`.

**Points d'entrée réseau non interceptés** : seules les méthodes `bind`/`connect`/`connect_ex`/`sendto` sont patchées (l. 1116-1124). `socket.fromfd()` enveloppe un descripteur déjà ouvert sans jamais appeler `connect`, et `socket.socketpair()` connecte deux sockets au niveau syscall sans passer par `connect`. Ni l'un ni l'autre n'est visible pour ce garde.

## 1.13 MOYENNE — contournement structurel par les extensions C (`sqlite3`, `dbm`)

Le garde fichiers intercepte trois primitives : `os.open`, `io.open`, `builtins.open`. Toute extension C qui ouvre ses fichiers depuis le C, sans passer par CPython, est invisible pour lui. Vérifié : `_default_rules` ne contient **aucune** entrée `sqlite3` ni `dbm` — et l'architecture ne permet pas d'en ajouter.

```python
import sqlite3
sqlite3.connect("/chemin/hors/sandbox.db")   # aucun contrôle
```

`python-import=sqlite3` est une entrée de whitelist parfaitement banale. Même remarque pour `dbm.gnu`/`dbm.ndbm`, et pour toute dépendance native manipulant ses propres descripteurs.

C'est une limite de conception, non un bug ponctuel, et elle relève de la même famille que la faiblesse déjà assumée dans `wiki/weaknesses.md` (« Any compiled code can have access to the entire Python memory »). Elle mérite cependant d'y être nommée explicitement : la formulation actuelle parle d'accès mémoire, pas d'accès fichiers hors règles par une extension standard de la bibliothèque Python.

## 1.14 MOYENNE — les patches d'environnement sont inertes hors mode learning (portée à préciser)

`guard_envs.py:376-398` :

```python
def patch_rules(learn: bool) -> dict[str, Callable]:
    if learn:
        return {"os.environ": ..., "os.getenv": ..., "os.putenv": ..., "os.unsetenv": ...}
    else:
        return {}
```

Hors mode learning — donc en usage normal — aucun patch n'est installé sur `os.environ`, `os.getenv`, `os.putenv` ni `os.unsetenv`. `guard_envs.activate_guard(all_rules.envs_rules)` (`py_sandbox.py:378`) ne fait que stocker les règles dans une globale du module que plus aucune fonction installée ne relit.

**Précision importante, contre une conclusion trop rapide** : cela ne signifie pas que les secrets de l'hôte sont lisibles. L'environnement est filtré **au lancement du processus enfant** — `client_subprocess_sse_daemon.py:200` passe `env=dict(envs)` à la création du sous-processus, avec l'environnement issu des règles `env=`/`unenv=`. L'application se fait donc au spawn, pas par les patches Python, et le résultat net est probablement correct pour les providers qui créent un processus.

Le défaut est de conception et de lisibilité : `guard_envs` expose un `activate_guard()` qui suggère une application au runtime alors qu'il n'en assure aucune, et le mécanisme réel est ailleurs. Reste à vérifier — **non fait ici** — si un provider quelconque active les gardes Python sans passer par un nouveau processus ; dans ce cas seulement les règles `env=` seraient sans effet.

---

# 2. Qualité du code et de l'implémentation

## 2.1 HAUTE — `make lint` échoue sur `develop`

```
$ make lint
tests/unit_tests/guard/test_guard_pickle.py:22,29,38,47,56,65,74,83,94,107,117,130,139,146,159,173,182,191,210
  error: Function is missing a return type annotation  [no-untyped-def]
Found 20 errors in 1 file (checked 112 source files)
make: *** [Makefile:116: lint] Error 1
```

Le commit `df6d5d3` s'intitule « fix(expose): clear lint and type regressions left by the WIP branch ». Les régressions ne sont pas résorbées : `test_guard_pickle.py`, introduit par la même série de merges, n'a jamais été annoté. `CLAUDE.md` impose « Type hints required for all code ». Le workflow `.github/workflows/lint.yml:52` exécute `make lint` — **la CI de `develop` est rouge sur le lint**.

## 2.2 HAUTE — `make test` est un no-op silencieux, et 4 commandes documentées n'existent pas

```
$ make test
Makefile:135: warning: overriding recipe for target 'spell_fix'
make: Nothing to be done for 'test'.
```

`test` est déclaré dans `.PHONY` (`Makefile:2`) sans aucune recette. Un contributeur qui lance `make test` obtient un succès immédiat sans avoir exécuté un seul test. C'est le pire mode de défaillance possible pour une commande de test.

Divergence complète entre `CLAUDE.md` et le `Makefile` :

| Documenté dans `CLAUDE.md` | Cible réelle | État |
|---|---|---|
| `make test` | *(aucune recette)* | **no-op silencieux** |
| `make integration_tests` | `integration-tests` | nom faux (underscore vs tiret) |
| `make all-tests` | `all-tests` | OK |
| `make gh-test` | `gh-tests` | nom faux |
| — | `unit-tests` | cible réelle des tests unitaires, **non documentée** |

De plus `gh-tests` (`Makefile:95`) ne dépend que de `format lint` puis lance `gh act push` : le nom suggère « exécuter les tests comme GitHub », il n'exécute aucun test localement.

## 2.3 HAUTE — la CI n'exerce que 2 samples sur 11, dont un en double

`Makefile`, cible `sample-tests` :

```make
sample-tests:
	# (cd samples/agno-demo && make tests && true)
	# (cd samples/autogen-demo && make tests && true)
	# (cd samples/crewai-demo && make tests && true)
	# (cd samples/google-adk-demo && make tests && true)
	(cd samples/langchain-demo && make tests && true)
	(cd samples/mcp-server-demo && make tests && true)
	(cd samples/mcp-server-demo && make tests && true)   # <- doublon
	# (cd samples/openai-agents-sdk-demo && make tests && true)
	# (cd samples/pydantic-ai-demo && make tests && true)
	# (cd samples/smolagents-demo && make tests && true)
	# (cd samples/strands-agents-demo && make tests && true)
```

9 des 11 lignes sont commentées, sans commentaire expliquant pourquoi ni condition de réactivation. `mcp-server-demo` est invoqué deux fois. `.github/workflows/test.yml:53` lance `make all-tests`, qui dépend de `sample-tests` : la CI valide donc `langchain-demo` et `mcp-server-demo` uniquement. Les 9 autres samples ne sont **jamais** exécutés — c'est très exactement l'explication mécanique des incohérences de configuration relevées en §1.4 et §1.5.

*Note de rigueur* : le suffixe `&& true` est un no-op, il **n'avale pas** les échecs (contrairement à `|| true`). Les 2 samples réellement exercés peuvent bien casser le build.

## 2.4 MOYENNE — `_DirEntry` n'implémente pas `os.PathLike`

`pysandboxes/guard_files.py:109` définit `class _DirEntry:` comme proxy des entrées de `os.scandir`. Aucune méthode `__fspath__` n'existe dans tout le paquet :

```
$ rg -n '__fspath__' pysandboxes/
(aucun résultat)
```

`os.DirEntry` réel implémente `os.PathLike`. Toute bibliothèque qui fait `Path(entry)`, `open(entry)` ou `os.stat(entry)` sur un résultat de `scandir` casse à l'intérieur du sandbox — avec un `TypeError` déroutant, sans rapport apparent avec le sandbox.

Reproduit involontairement pendant cet audit, par le nettoyage `atexit` de pytest lui-même :

```
TypeError: argument should be a str or an os.PathLike object where
__fspath__ returns a str, not '_DirEntry'
  File ".../_pytest/pathlib.py", line 353, in cleanup_candidates
    yield Path(entry)
```

Le correctif est de trois lignes (`def __fspath__(self) -> str: return self.path`). L'absence de test sur la conformité `PathLike` du proxy est le vrai défaut.

## 2.5 MOYENNE — concaténation de littéraux : `TRANSFORMERS_CACHE` et `TORCH_HOME` ne sont jamais reconnus

`pysandboxes/guard_files.py:322`, dans la liste `_special_home` :

```python
"HF_HUB_CACHE",
"TRANSFORMERS_CACHE" "," "TORCH_HOME",     # <- virgule DANS les guillemets
"KERAS_HOME",
```

La virgule séparatrice a été saisie à l'intérieur des guillemets. Python concatène alors les trois littéraux adjacents en un seul élément. Preuve :

```
$ uv run python -c 'print(["A","TRANSFORMERS_CACHE" "," "TORCH_HOME","B"])'
['A', 'TRANSFORMERS_CACHE,TORCH_HOME', 'B']
```

La liste contient donc l'entrée inexistante `"TRANSFORMERS_CACHE,TORCH_HOME"` au lieu des deux variables attendues. Conséquence : **ni `TRANSFORMERS_CACHE` ni `TORCH_HOME` ne sont jamais reconnus** par `_special_home`, qui sert à substituer les répertoires de caches de modèles lors de la génération de règles. Les utilisateurs de HuggingFace Transformers et de PyTorch — soit une large part du public visé, puisque le produit cible les usages IA/LLM — obtiennent des règles générées avec des chemins absolus en dur au lieu de la variable d'environnement.

Correction : remplacer par `"TRANSFORMERS_CACHE", "TORCH_HOME",`. Le fait qu'aucun test ne couvre le contenu de `_special_home` est le défaut de fond.

## 2.6 MOYENNE — la limite de 78 colonnes documentée est fictive

`CLAUDE.md` : « Line length: 78 chars maximum ». `pyproject.toml:122` : `line-length = 120`. Résultat : **895 lignes** du paquet dépassent 78 colonnes.

Pires contributeurs : `remote/qemu_sse_daemon.py` (155), `remote/qemu_setup.py` (60), `guard_socket.py` (52), `remote/bwrap_sse_daemon.py` (43), `guard_files.py` (43).

Une règle que l'outillage n'applique pas et que le code viole 895 fois n'est pas une règle. Soit `pyproject.toml` passe à 78 et le code est reformaté, soit `CLAUDE.md` dit 120. La situation actuelle rend la consigne inexploitable pour un contributeur — humain ou agent.

## 2.7 MOYENNE — fonctions démesurées dans le code critique de sécurité

`CLAUDE.md` : « Functions must be focused and small ». Les 15 plus longues fonctions du paquet :

| Lignes | Emplacement | Fonction |
|---|---|---|
| 303 | `remote/parse_cpython_args.py:19` | `parse_python_cmd_line` |
| 281 | `remote/unshare_setup.py:136` | `main` |
| **279** | `remote/firejail_sse_daemon.py:333` | `_firejail_args` |
| 247 | `remote/unshare_sse_daemon.py:608` | `_launch` |
| 239 | `python_sb.py:76` | `main` |
| 192 | `remote/qemu_setup.py:100` | `_bootstrap_script_content` |
| 182 | `remote/qemu_sse_daemon.py:1154` | `_re_start_cmd` |
| 181 | `remote/main_sandbox.py:284` | `main` |
| **180** | `guard_socket.py:218` | `_parse_rule` |
| **164** | `guard_socket.py:597` | `_check_address_with_rules` |

Les trois en gras sont les plus préoccupantes : `_firejail_args` construit la ligne de commande d'isolation du backend principal, `_parse_rule` interprète les règles réseau, `_check_address_with_rules` décide d'autoriser ou refuser une connexion. Ce sont les fonctions de décision de sécurité, et ce sont parmi les plus longues du dépôt. Une fonction de 279 lignes qui assemble des arguments d'isolation n'est ni relisable ni testable par branche — c'est là que se logent les évasions.

## 2.8 BASSE — `/tmp` codé en dur ignore `TMPDIR`

`pysandboxes/python_sb.py:131` :

```python
_host_tmp = "/tmp" if os.path.isdir("/tmp") else None
```

Le test porte sur l'existence de `/tmp`, pas sur son caractère inscriptible, et `TMPDIR` n'est pas consulté. Sur un hôte où `/tmp` est monté en lecture seule — durcissement classique, conteneurs à racine immuable, et c'est le cas de l'environnement de cet audit — `python-sb` échoue au démarrage avec une trace brute :

```
OSError: [Errno 30] Read-only file system: '/tmp/pysandboxes-sb-p_16uvhv'
```

Respecter `tempfile.gettempdir()` (qui honore `TMPDIR`) coûte une ligne et rend le CLI utilisable sur ces hôtes. C'est aussi ce qui m'a empêché de conclure la démonstration de §1.0.

## 2.9 HAUTE — la commande de lancement des README `mcp-client` est cassée

Quatre occurrences, dans les deux README :

```
samples/mcp-client/README.md:151       uv run -m mcp_sample_chatbot.main ${CONFIG}
samples/mcp-client/README.md:185       uv run -m pysandboxes.python_sb -m mcp_sample_chatbot.main ${CONFIG}
samples/mcp-client-demo/README.md:154  uv run -m mcp_sample_chatbot.main ${CONFIG}
samples/mcp-client-demo/README.md:188  uv run -m pysandboxes.python_sb -m mcp_sample_chatbot.main ${CONFIG}
```

Le paquet réel est `mcp_simple_chatbot`, pas `mcp_sample_chatbot`. Copiée-collée telle quelle, la commande échoue sur `ModuleNotFoundError`.

C'est l'exemple phare du mode « sandboxer le processus entier » via `python-sb` — celui qui justifie le transfert des clés d'API dans l'environnement du sandbox. Il n'est pas exécutable depuis sa propre documentation, et ni `mcp-client` ni `mcp-client-demo` ne sont exercés en CI (§2.3), ce qui explique que la coquille survive dans les deux copies.

## 2.10 MOYENNE — incohérences propres aux samples

**`crewai-demo` : la tâche par défaut est bloquée par sa propre configuration.** `crewai_demo/main.py:25` définit comme tâche par défaut « fetch `https://www.google.com` with fetch_webpage ». La configuration réellement chargée en suivant le README (`cd samples/crewai-demo`, donc `samples/crewai-demo/.py-sandboxes`) n'autorise que :

```
samples/crewai-demo/.py-sandboxes:32   net=ALLOW|tcp|example.com|443|OUT
samples/crewai-demo/.py-sandboxes:38   net=DENY|*|*|*|OUT
```

`www.google.com` n'y figure pas, et un `net=DENY` explicite ferme le reste. Le sample échoue donc sur son scénario par défaut. La config imbriquée `crewai_demo/.py-sandboxes` autorise bien `www.google.com`, mais elle ne gouverne que si le répertoire courant est le paquet interne — ce que le chemin d'exécution documenté ne fait jamais.

**`agno-demo` désactive l'isolation par défaut.** `samples/agno-demo/.py-sandboxes:12` :

```
os-sandbox=${OS_SANDBOX:-none}
```

C'est le seul des quatorze samples dont le défaut est `none` ; les treize autres utilisent `subprocess`. Aucun commentaire n'explique la divergence, et l'en-tête du fichier lui-même énonce que `subprocess` est « the default, safest ». Combiné à §1.9 (agno-demo n'a aussi aucune règle `python-import=`) et §1.10 (`os.system` non patché), ce sample ne présente en pratique aucune barrière.

**Liste complète des `python-import=*` actifs** — §1.4 en citait un, il y en a dix :

```
samples/smolagents-demo/.py-sandboxes:6
samples/openai-agents-sdk-demo/.py-sandboxes:6
samples/mcp-server/.py-sandboxes:72
samples/mcp-server/mcp_server/.py-sandboxes:72
samples/mcp-server-demo/mcp_server/.py-sandboxes:72
samples/mcp-client/.py-sandboxes:85
samples/mcp-client/mcp_simple_chatbot/.py-sandboxes:85
samples/mcp-client-demo/mcp_simple_chatbot/.py-sandboxes:85
samples/google-adk-demo/google_adk_demo/.py-sandboxes:80
samples/crewai-demo/crewai_demo/.py-sandboxes:88
```

Avec les 5 configurations sans aucune règle d'import (§1.9), **la quasi-totalité des samples n'a pas de filtrage d'import effectif**. Ce n'est plus une anomalie ponctuelle, c'est l'état par défaut du corpus d'exemples.

**Modules à capacité d'évasion déclarés sans usage dans le code du sample** — signature du mode learning décrite en §1.5, retrouvée dans six fichiers : `langgraph-demo/langgraph_simple_chatbot/.py-sandboxes:8` (`subprocess`, sous « ⚠ Dangerous! ») et `:17-18` (`os`, `pickle`, `socket`) ; `google-adk-demo/.py-sandboxes:11,20` (`subprocess`, `marshal`, `os`, `pickle`) ; `mcp-server/.py-sandboxes:7,20` et son doublon `mcp-server-demo/mcp_server/` (`subprocess`, `socket`, `ssl`) ; `mcp-client{,-demo}/mcp_simple_chatbot/.py-sandboxes:16` (`subprocess`) ; `autogen-demo/.py-sandboxes:63` (`socket` seul). Une réserve : `socket` et `ssl` sont plausiblement nécessaires de façon transitive (uvicorn, starlette, httpx les importent au chargement) ; `subprocess`, `pickle` et `marshal` n'apparaissent dans aucun import direct du code des samples.

**`samples/README_SANDBOX_TESTS.md:39-56` documente ce qui n'existe pas** : le test `test_fetch_sandbox.py` n'existe que dans `samples/mcp-server`, l'arbre mort jamais exercé (§2.11), et la cible `container-tests` n'existe dans aucun des deux `Makefile` de samples. La documentation dirige donc le lecteur vers l'arbre obsolète.

## 2.11 BASSE — hygiène

| Problème | Emplacement |
|---|---|
| Cible `spell_fix` définie deux fois → `make` avertit à chaque invocation | `Makefile:132` et `Makefile:135` |
| Fichier `hack.py` vide, versionné à la racine | `hack.py` |
| Second `hack.py` versionné | `tests/integration_tests/hack.py` |
| Fichiers morts versionnés | `tests/test.old`, `tests/unit_tests/guard/test_guard_python_api.py_old` |
| Lien symbolique cassé/douteux versionné | `.local.py-sandboxes.backup -> pycharm.profile` |
| Arbres de samples dupliqués | `samples/mcp-client` vs `samples/mcp-client-demo`, `samples/mcp-server` vs `samples/mcp-server-demo` |

`unit-tests` et `integration-tests` font `set -a && source .env` : les tests héritent de l'environnement local du développeur. Pour un produit de sécurité dont les règles portent sur `env=`, cela rend les résultats dépendants de la machine. À isoler par un fichier d'environnement de test dédié et versionné.

---

# 3. Cohérence code / paramètres / documentation

## 3.1 HAUTE — `CLAUDE.md` décrit un produit qui n'existe plus

`CLAUDE.md` (lien symbolique vers `AGENTS.md`) est le fichier d'instructions lu par tous les agents travaillant sur ce dépôt. Il est faux sur cinq points vérifiés :

| Affirmation de `CLAUDE.md` | Réalité (source) |
|---|---|
| « Multiple OS sandbox backends supported (firejail primary, Docker/podman planned) » | `_os_sandbox.py:37-47` : `none`, `subprocess`, `bwrap`, `firejail`, `unshare`, `landlock`, `qemu`. **Aucun** backend Docker/podman n'est ni livré ni amorcé ; `bwrap`, `unshare`, `landlock` et `qemu` — quatre backends complets, avec daemons et pages wiki — ne sont pas mentionnés. |
| « **pysandboxes/os_sandbox.py** : OS-level sandbox wrapper » (l. 40) | **Ce fichier n'existe pas.** Le module réel est `pysandboxes/_os_sandbox.py`, avec un underscore initial (vérifié : `ls pysandboxes/os_sandbox.py` → *No such file or directory*). Un agent qui suit le fichier d'instructions cherche un fichier absent. |
| « Package Manager: mv » | `uv` (coquille, mais elle égare un lecteur automatique) |
| « Line length: 78 chars maximum » | `pyproject.toml:122` : `line-length = 120` ; 895 lignes du paquet dépassent 78 (§2.5) |
| « `make test` / `make integration_tests` / `make gh-test` » | cibles réelles : *(aucune)* / `integration-tests` / `gh-tests` (§2.2) |
| « scanned with semgrep … `--config=p/security-audit` » | `Makefile:138` : `--config auto`, plus deux règles désactivées globalement (§1.7) |

Un fichier d'instructions faux est plus nuisible qu'un fichier absent : il est lu comme autorité par les agents et les nouveaux contributeurs, qui reproduisent les erreurs qu'il contient. La liste des backends est le point le plus grave — elle donne à croire que firejail est le seul chemin mûr, alors que le dépôt a livré quatre autres providers depuis.

## 3.2 MOYENNE — `landlock` est un provider livré, absent du template de configuration

`_PROVIDER_SPECS` (`_os_sandbox.py:45`) enregistre `landlock`, le daemon existe (`remote/landlock_daemon.py`, 481 lignes) et `wiki/landlock.md` le documente. Or `pysandboxes/templates/py-sandbox.template` — le fichier de référence que les utilisateurs copient — documente des blocs de paramètres pour `qemu` (l. 199), `bwrap` (l. 234), `firejail` (l. 258), `unshare` (l. 284), `subprocess | none` (l. 297), et **rien pour `landlock`** :

```
$ grep -in 'landlock' pysandboxes/templates/py-sandbox.template
ABSENT
```

Un utilisateur partant du template ne peut pas découvrir `landlock`, pourtant présenté par `wiki/landlock.md:8` comme celui qui « fonctionne partout sans limitations » et « ne requiert aucun privilège » — soit, sur le papier, le plus recommandable par défaut.

## 3.3 BASSE — deux providers internes sont sélectionnables depuis une configuration utilisateur

`_PROVIDER_SPECS` contient `_task` et `_sse_server`, destinés à l'usage interne. `_LazyProvidersFactory.__contains__` ne les distingue pas, et `_os_sandbox.py:155` ne valide que l'appartenance à la table. Une configuration contenant `os-sandbox=_task` est donc acceptée et instancie un daemon interne dans un contexte non prévu. Le préfixe `_` est une convention, pas un contrôle : il faudrait filtrer explicitement les clés privées à la validation de la configuration.

## 3.4 HAUTE — quatre versions de Python déclarées supportées, une seule testée

Le socle de versions est par ailleurs cohérent, ce qui rend l'écart d'autant plus visible :

| Source | Versions |
|---|---|
| `pyproject.toml:9` | `requires-python = ">=3.11,<3.15"` |
| `pyproject.toml:17-21` (classifiers) | 3.11, 3.12, 3.13, 3.14 |
| `.github/workflows/lint.yml:15` | `["3.11","3.12","3.13","3.14"]` |
| `.github/workflows/test.yml:16` | **`["3.13"]`** — la matrice complète est commentée juste au-dessus (l. 15) |

```yaml
# .github/workflows/test.yml
        #python-version: ["3.11","3.12","3.13", "3.14"]
        python-version: ["3.13"]
```

Le paquet est publié comme supportant 3.11 à 3.14 ; **aucun test n'est exécuté sur 3.11, 3.12 ni 3.14**. Seul le lint couvre ces versions, et le lint ne détecte pas les ruptures de comportement.

C'est particulièrement risqué pour ce produit précis : les gardes reposent sur le patch d'internes de CPython (`importlib.metadata.FastPath`/`Prepared` importés en `type: ignore[attr-defined]` dans `guard_import.py:53,299`, structure de `os.DirEntry`, sémantique de `pathlib`). Ce sont exactement les surfaces qui bougent entre versions mineures de CPython — le test suite en donne déjà un exemple avec l'avertissement de dépréciation de `PurePath.is_reserved()` en vue de 3.15. Une régression d'isolation sur 3.11 ou 3.14 passerait aujourd'hui inaperçue.

La matrice a été réduite sans commentaire justificatif ni condition de réactivation — même schéma que les 9 samples désactivés (§2.3). Soit la matrice est rétablie, soit les classifiers et `requires-python` sont resserrés sur ce qui est réellement testé. Publier un produit de sécurité comme compatible avec des versions non testées n'est pas défendable.

## 3.5 MOYENNE — mypy et ruff n'ont pas de version Python cible fixée

`pyproject.toml` ne définit ni `target-version` (black/ruff) ni `python_version` (mypy). Ces outils se rabattent alors sur l'interpréteur courant : le résultat de `make lint` dépend de la version de Python du développeur. Combiné à §3.4, cela signifie que la seule barrière couvrant 3.11–3.14 (le lint en CI) ne vérifie pas la même chose que le lint local d'un contributeur. Fixer `python_version = "3.11"` (la borne basse déclarée) rend le lint déterministe et attrape réellement les usages trop récents.

---

# 4. Couverture de cet audit

Trois balayages ont été délégués à des sous-agents (gardes, documentation, samples) pour contenir le contexte. Leurs signalements sont arrivés et ont été **intégralement recontrôlés sur les sources avant d'entrer dans ce rapport** : chaque constat ci-dessus a été vérifié par mes propres lectures ou exécutions. Trois de leurs affirmations n'ont pas résisté au contrôle et ont été corrigées plutôt que reprises :

| Affirmation reçue | Ce que dit la source |
|---|---|
| 4 samples sans règle `python-import=` | **5** — `mcp-server-demo/.py-sandboxes` avait été omis, et c'est l'un des deux seuls samples exercés en CI |
| `connect()` est fail-open comme `bind()` | `connect` exécute `assert False` (l. 1015-1020) — il bloque, sauf sous `python -O` où l'assertion disparaît (§1.12) |
| `os.symlink` ne valide jamais sa cible | La cible **est** validée si elle est absolue ; seule une cible relative échappe au contrôle (§1.0) |

Une quatrième — des directives `port=`/`pickle-class=` absentes du template — n'a pas pu être confirmée (le template contient bien des occurrences correspondantes) : elle est écartée faute de preuve, dans un sens comme dans l'autre.

Voici ce qui, malgré cela, **n'a pas** été couvert, afin qu'aucune section absente ne soit lue comme un satisfecit :

- **`guard_socket.py`, logique de correspondance IP/CIDR/port** : les défauts de dispatch sont couverts (§1.12), mais l'appariement lui-même, une fois le dispatch franchi, n'a pas été testé unitairement. **À reprendre en priorité** : par analogie avec §1.0, un TOCTOU DNS est plausible (résolution au moment du contrôle vs au moment de la connexion). Le dépôt expose une notion de `pin_dns` qui suggère que le sujet est connu ; elle n'a pas été vérifiée.
- **Imports utilisés mais non déclarés** : les modules à capacité d'évasion *déclarés en trop* sont recensés (§2.10), mais l'inverse — un import nécessaire manquant, qui ferait échouer un sample à l'exécution — n'a pas été établi sample par sample, faute d'exécution.
- **Tests d'intégration et de conteneurs** : non exécutables ici (firejail, bwrap, qemu, minikube absents). **Aucune conclusion, ni positive ni négative, sur leur état.**
- **Autres points d'entrée non patchés** : au-delà de `sqlite3`/`dbm` (§1.13), la revue systématique des fonctions frères atteignant le même appel système (`tarfile`, `mmap`, `codecs.open`, `os.truncate`, `shutil.rmtree`) n'a pas été menée. `shutil.rmtree` est notamment non patché alors que `shutil.copytree` l'est ; sa couverture indirecte n'a pas été tracée.
- **Exploitation de bout en bout de §1.0 et §1.10** : la décision d'autorisation est démontrée fausse, l'exécution dans un sandbox réel ne l'est pas (§1.0, « Non exécuté »).

---

# 5. Budget

Le `CLAUDE.md` global fixe un budget de 4 000 tokens par tâche et 30 000 par session, avec obligation de signaler tout dépassement. **Dépassement signalé** : un audit à quatre axes sur ~19 000 lignes de code, 25 samples et l'ensemble de la documentation ne tient pas dans cette enveloppe. Les balayages bruyants (samples, documentation, surface de contournement des gardes) ont été délégués à des sous-agents pour contenir le contexte principal, conformément à la section « Subagent Strategy ».
