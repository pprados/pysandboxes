# Analyse de sécurité adversariale de PySandboxes

Date de l’analyse : 2026-10-09
Périmètre : code courant, architecture, providers et compatibilité CPython 3.11 à 3.14. Les documents d’audit antérieurs n’ont pas été utilisés comme preuve.
Méthode : lecture statique des points d’entrée, des gardes, du transport RPC et des commandes providers; comparaison avec les garanties annoncées par les documentations primaires. Aucun test d’évasion ni essai d’exploitation n’a été exécuté dans cette passe. Les constats « à valider » demandent une reproduction isolée avant décision.

## Résumé exécutif

PySandboxes combine un processus Python séparé avec des gardes Python et, selon le provider, une restriction du système d’exploitation. La séparation par processus est utile, mais ne constitue pas une frontière de sécurité contre du code hostile. Les gardes Python sont des modifications réversibles de modules CPython et ne peuvent pas remplacer une politique kernel. La force réelle dépend donc entièrement du provider sélectionné, des chemins exposés, des règles réseau et des options de profil.

Le profil par défaut vise `landlock` sous Linux compatible et `subprocess` ailleurs. `subprocess` n’ajoute aucune restriction OS. `landlock` limite surtout les accès fichiers et, selon l’ABI, ports TCP; il ne fournit ni isolation de processus ni filtrage général des appels système. Même les providers Linux laissent volontairement des chemins vers les fichiers auxquels l’application donne accès en écriture. `qemu` est la meilleure séparation de cette liste, mais les montages 9p et les périphériques virtuels restent des interfaces d’attaque entre invité et hôte.

Le risque le plus urgent dans le code revu est le transport d’exceptions enfant → parent : le désérialiseur accepte toute classe `Exception` déjà chargée, puis le pickle peut reconstruire cette classe et exécuter ses hooks. Les résultats en mode `objects` sont aussi protégés par une denylist fail-open et peuvent reconstruire des objets applicatifs. Le mode `data-only`, activé par défaut, est une réduction importante de cette surface.

Conclusion d’usage : traiter `subprocess`, `none` et le seul sandbox Python comme adaptés au développement ou à du code de confiance, jamais comme une frontière pour une charge arbitraire. Pour un service multi-tenant ou des secrets de l’hôte, privilégier un worker séparé avec identité OS dédiée et limites de ressources; considérer QEMU avec montages minimaux comme le candidat le plus robuste parmi les providers actuels, sans le qualifier d’infaillible.

## Modèle de menace retenu

L’attaquant peut contrôler le code décoré `@sandbox`, ses arguments, ses sorties, ses exceptions et son comportement temporel. Il peut tenter des accès système via Python, modules natifs, appels indirects et processus enfants. Le parent, son environnement, ses secrets, ses fichiers non exposés et les autres utilisateurs du système sont considérés comme protégés. Les administrateurs qui écrivent les règles/provider sont de confiance. Une configuration `learn`, `py-sandbox=false`, `remote-result-mode=objects` ou `remote-result-guard=false` est traitée comme une réduction volontaire de protection et doit être considérée dans le risque global.

L’audit du code ne prouve pas qu’un binaire, un noyau, un hyperviseur, un profil Firejail local ou une configuration Docker/Podman est sain. Les résultats doivent être validés sur les versions et noyaux réellement déployés.

## Constats prioritaires

### C-01 — Une exception hostile peut déclencher du code pendant sa reconstruction dans le parent

**Sévérité : élevée, conditionnelle aux classes d’exception chargées dans l’application.**
**Preuve :** `exception_predicate()` accepte toute classe qui hérite de `Exception` (`pysandboxes/remote/tools.py`, lignes 737–745); `_RestrictedUnpickler.find_class()` appelle ce prédicat, puis `Unpickler.load()` reconstruit l’objet (`pysandboxes/remote/tools.py`, lignes 642–681 et 846–884). Le serveur tente d’abord de sérialiser l’exception entière avec `pickle.dumps()` (`pysandboxes/remote/sse_server_daemon.py`, lignes 160–183). Les classes `Exception` personnalisées peuvent définir des reconstructions pickle, `__new__` ou `__setstate__` exécutées lors du chargement.

**Scénario :** un code hostile lève une classe d’exception applicative déjà importée dans le parent. Le transport riche la désérialise hors de la sandbox. Une classe dont les hooks traitent les données d’exception sans précaution peut alors provoquer effets de bord, lecture/écriture ou exécution dans le parent. Le risque exact dépend des classes et des dépendances de l’application; le garde actuel n’impose pas de schéma sûr.

**Correction :** ne jamais désérialiser l’instance d’exception d’un processus non fiable. Toujours transporter un descripteur primitif fermé (module/nom à titre informatif, message tronqué, dénis sérialisés), puis reconstruire une exception générique locale. N’instancier une exception spécialisée que depuis une petite liste de types internes dont la reconstruction est explicitement testée. Ajouter des limites de longueur au message, au traceback et aux dénis.

### C-02 — Le mode `objects` ne garantit pas l’absence d’exécution de code au retour

**Sévérité : élevée si du code hostile peut choisir le profil ou rendre des objets; faible en mode `data-only`.**
**Preuve :** le mode par défaut `data-only` valide une grammaire de valeurs après désérialisation (`pysandboxes/remote/tools.py`, lignes 719–750 et 872–909). En revanche, `result_predicate()` bloque une liste de modules/objets connus et laisse passer les autres (`pysandboxes/remote/tools.py`, lignes 750–798). Les résultats peuvent donc reconstruire des classes applicatives ou de dépendances chargées dans le parent. `remote-result-guard=false` désactive même cette denylist; le pré-scan pickle reste actif, mais n’empêche pas une reconstruction permise d’exécuter du code (`pysandboxes/remote/tools.py`, lignes 846–884). Le code et le template reconnaissent explicitement le caractère fail-open de ce contrôle.

**Correction :** conserver `data-only` comme unique valeur sûre par défaut et pour tout usage avec entrée hostile. Remplacer les résultats d’objets par un protocole de données versionné (JSON/CBOR avec types fermés, limites de profondeur et de taille). Si un mode objet est indispensable, permettre une allowlist explicite de types avec constructeurs purs dédiés; ne jamais présenter la denylist comme protection complète. Faire refuser au démarrage les options risquées en profil de production, ou exiger un opt-in dont le nom et la documentation expriment clairement l’exécution côté parent.

### C-03 — Les gardes Python sont contournables par conception et leur inventaire manuel peut dériver

**Sévérité : critique si elles sont utilisées seules; élevée avec `subprocess`; défense en profondeur pour un provider kernel.**
**Preuve :** les gardes patchent `builtins`, modules et classes en mémoire. La table `SENSITIVE_API` est maintenue manuellement et le commentaire indique qu’une API CPython ajoutée mais non enregistrée reste appelable (`pysandboxes/guard_api.py`, lignes 27–30). Le code ajoute des noms spécifiques à 3.12, 3.13 et 3.14 (`guard_api.py`, lignes 304–327), ce qui confirme la dépendance à la version. Des interfaces natives, des références capturées avant patch, des modules C déjà chargés, des appels syscalls ou de nouvelles surfaces CPython peuvent échapper à ces wrappers. `subprocess` ne fournit pas de frontière OS; la doc du template le dit aussi (`pysandboxes/templates/py-sandboxes.template`, lignes 240–256).

**Correction :** considérer les gardes Python comme contrôle d’usage et auditabilité, jamais comme barrière ultime contre du code adversarial. Pour un usage hostile, rendre obligatoire une isolation kernel vérifiée ou un worker VM/conteneur avec utilisateur distinct. Maintenir une revue à chaque mineure CPython et des tests différentiels automatisés des API sensibles (processus, natif, introspection, sous-interpréteurs, code dynamique, fichiers, réseau). Toute nouvelle API doit être refusée par défaut quand le provider ne peut la confiner.

### C-04 — Politique d’accès aux fichiers par wrappers Python vulnérable aux chemins natifs et aux courses

**Sévérité : élevée avec `subprocess`; réduite mais non nulle par Landlock/mount namespaces.**
**Preuve :** le contrôle Python inspecte le chemin, puis exécute l’appel système (`pysandboxes/guard_files.py`, lignes 1181–1224). Cette séquence n’est pas atomique : un chemin ou répertoire peut être échangé entre la validation et l’ouverture (TOCTOU). Les APIs natives, extensions ou appels directs au noyau contournent le wrapper. Le code miroir des fonctions `os.*` sur `posix`/`nt` corrige des alias connus, mais ne couvre pas toutes les bibliothèques natives (lignes 1940–1973).

**Correction :** pour du code non fiable, imposer la politique au niveau OS et réduire les montages accessibles. Pour l’API Python, utiliser des descripteurs de répertoire préouverts et des opérations relatives (`openat2` avec résolution contrainte lorsqu’elle est disponible), éviter les vérifications suivies d’accès par chemin, et tester liens symboliques, `dir_fd`, hardlinks, chemins supprimés/remplacés et appels via C.

### C-05 — Absence de limites fortes et communes contre déni de service

**Sévérité : élevée dans un service exposé; moyenne en exécution locale.**
**Preuve :** les délais RPC et d’arrêt empêchent certains blocages du parent, mais ne plafonnent pas CPU, mémoire, nombre de processus, descripteurs, disque, output ou requêtes simultanées. Le budget de réponse limite les pickle à 384 KiB, mais autorise jusqu’à 5 millions d’opcodes et 2 millions d’entrées memo (`pysandboxes/remote/tools.py`, lignes 398–431 et 584–630). Le serveur suit `_active_requests` mais n’impose pas de quota dans le chemin RPC (`sse_server_daemon.py`, ligne 37 et endpoint ligne 233+). Les délais ne tuent pas nécessairement un appel de calcul déjà actif.

**Correction :** appliquer des limites par exécution depuis le superviseur : cgroup v2 (CPU/mémoire/PID), `RLIMIT_CPU`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE`, quota de stockage/tmp, durée murale avec terminaison du groupe complet, taille maximale de stdout/stderr/arguments/résultat, et nombre de tâches simultanées. Réduire substantiellement le budget opcode et mesurer son coût maximal sur les versions 3.11–3.14. En cas d’expiration, tuer l’ensemble du groupe/namespace/VM et confirmer la disparition de tous les descendants.

### C-06 — Le provider par défaut change de niveau de protection selon l’hôte

**Sévérité : élevée pour les déploiements portables.**
**Preuve :** Linux choisit Landlock s’il est disponible, sinon le profil généré retombe à `subprocess`; macOS et Windows sélectionnent `subprocess` (`pysandboxes/_os_sandbox.py`, lignes 37–53 et 95–110). Le repli écrit le provider dans le profil et avertit parfois, mais l’application peut ensuite tourner sans frontière OS. Le nom `subprocess` peut être interprété à tort comme une vraie sandbox alors qu’il s’agit d’un processus distinct seulement.

**Correction :** exposer au démarrage un niveau d’isolation effectif explicite; refuser l’exécution de code non fiable quand le niveau demandé n’est pas obtenu. En production, ne pas faire de downgrade implicite. Fournir un paramètre de politique tel que « minimum d’isolation requis » et une télémétrie exploitable indiquant le provider effectif, ABI, namespaces, filtres et quotas réellement actifs.

### C-07 — Configuration avec `learn` ou profil absent autorise temporairement trop

**Sévérité : élevée si le premier lancement traite du code non fiable.**
**Preuve :** `load_and_parse_config()` passe en mode apprentissage quand le profil n’existe pas (`pysandboxes/py_sandbox.py`, autour des lignes 130–180); le template indique que ce mode force `subprocess` (`py-sandbox.template`, ligne 254). Le verrou `learn=false` est optionnel. L’apprentissage observe les appels d’une exécution et les écrit pour revue, ce qui signifie que l’exécution d’apprentissage n’est pas une exécution à permissions minimales.

**Correction :** en mode sécurité, échouer fermé quand le profil est absent ou `learn` actif. Séparer explicitement le mode d’apprentissage d’un lancement de charge potentiellement hostile (pas de secrets, compte jetable, réseau coupé, données synthétiques), et exiger un profil verrouillé en production.

## Comparaison adversariale des providers

| Provider | Ce qu’il ajoute effectivement | Limites et risques principaux | Recommandation |
|---|---|---|---|
| `none` | Exécute dans le processus courant; ne crée pas de frontière. | Aucun isolement; l’état, les secrets et les effets de bord sont ceux du parent. | Tests uniquement. Interdire avec code non fiable. |
| `subprocess` | Processus Python enfant, configuration/environnement distincts, RPC local avec bearer token. | Même utilisateur et noyau; pas de confinement syscall/fichiers/réseau. Les patches Python sont contournables. Un processus séparé ne protège pas l’hôte contre code natif. | Développement ou code de confiance seulement. |
| `landlock` | Sous-processus plus règles Landlock de fichiers et, pour ABI suffisante, ports TCP. Démarre avec `no_new_privs`. | Pas de namespace PID, pas de filtre syscall général, pas de quota; sockets Unix abstraits et descripteurs hérités sont hors de la politique fichier ordinaire. Kernel/ABI déterminants. Les fichiers `expose-rw` restent modifiables réellement par l’identité hôte. | Bon renfort Linux simple; ne pas en faire un conteneur complet. Valider les fichiers ouverts/hérités et l’ABI du noyau. |
| `bwrap` | Namespace de montage et construction explicite d’un système de fichiers; réseau isolé et filtré lorsque demandé; capacités absentes par défaut. | La politique dépend des binds calculés et du profil. Les répertoires exposés en écriture sont des accès hôte réels. L’isolation réseau peut être désactivée lorsque le profil le demande; vérifier la présence effective des namespaces/options après lancement. Pas de quotas CPU/mémoire visibles dans la commande auditée. | Provider Linux robuste si configuration stricte et testée. Auditer le `argv` effectif, les mounts et namespaces à chaque version. |
| `firejail` | Namespaces et restrictions Firejail, capacités supprimées par le template; configuration de réseau/netfilter possible. | Dépend du binaire, de sa compilation, de sa version et des profils/include locaux. `restricted-network yes` garde le réseau hôte et ne laisse que les gardes Python filtrer les sockets (commentaire explicite dans `firejail_sse_daemon.py`, lignes 464–477). Option `--net`/bridge/netfilter et profils système peuvent changer la protection. | Acceptable après contrôle des flags réellement appliqués et tests d’évasion par version Firejail; refuser la variante réseau partagée pour code hostile. |
| `unshare` | Namespace utilisateur/montage/réseau/PID; chroot et mounts bind; slirp/netfilter selon règles. | S’appuie sur kernel + util-linux + `slirp4netns` + outils mount/iptables. Namespace utilisateur n’est pas une frontière contre bugs noyau; mêmes fichiers exposés et même hôte. L’interface réseau/filtrage dépend de la mise en place. Ressources non plafonnées par le seul fait d’utiliser namespaces. | Bon renfort si chaque namespace et règle est vérifié; ajouter quotas cgroup et utilisateur dédié. |
| `qemu` | Guest VM distinct; RAM configurée (2 GiB par défaut), réseau utilisateur avec port-forward explicite, OS invité séparé. | QEMU et périphériques virtuels sont une surface de sortie VM. 9p expose les chemins choisis directement; une règle `expose-rw` rend le partage modifiable côté hôte. Le forwarding réseau et la configuration guest font partie de la frontière. Pas de limite CPU/temps garantie par `-m`. | Meilleure isolation disponible ici pour code arbitraire, avec partages minimaux, pas de secrets dans l’image/guest, QEMU à jour et tests de kill/quota/évasion. |

**Point particulier bwrap :** le template n’active pas `--disable-userns` par défaut; l’option existe en commentaire et peut être ajoutée au profil (`pysandboxes/templates/bwrap.template`, lignes 108–113). Il faut mesurer si les charges peuvent créer des user namespaces imbriqués sur les hôtes supportés. Cela augmente la surface noyau et rend nécessaire une politique explicite sur les namespaces internes, même si les mounts initiaux sont bien construits.

Les garanties Landlock et QEMU doivent être lues avec leurs limites officielles : [documentation Landlock du noyau Linux](https://docs.kernel.org/userspace-api/landlock.html), [modèle de sécurité QEMU](https://www.qemu.org/docs/master/system/security.html). Bubblewrap se décrit comme un outil de construction de sandbox et non une politique complète prête à l’emploi : [README bubblewrap](https://github.com/containers/bubblewrap). Firejail décrit ses options et leurs dépendances dans [son manuel](https://github.com/netblue30/firejail/blob/master/src/man/firejail.1.in).

## Différences CPython 3.11–3.14

| Version | Changements explicitement suivis dans `guard_api.py` | Risque à auditer |
|---|---|---|
| 3.11 | Base de la matrice supportée; noms historiques de threads et sous-interpréteurs. | Tester les aliases `posix`/modules C sur la version minimale; dépendances/stdlib différentes peuvent ajouter des chemins vers API natives. |
| 3.12 | Ajout de `os.unshare`, `os.setns`, hooks de trace/profil global et `sys.monitoring` à la table. | Vérifier chaque API et ses aliases au runtime, ainsi que la présence/absence selon le build. Ne pas supposer que le nom listé suffit à bloquer tous les accès sous-jacents. |
| 3.13 | Changement de primitives de thread et sous-interpréteur vers `_start_joinable_thread`, `_thread.start_joinable_thread`, `_interpreters.create`. | Risque de dérive entre modules natifs et wrappers; exécuter les tests d’évasion sous tous les builds disponibles. |
| 3.14 | `sys.remote_exec` ajouté aux API sensibles. | Tester les nouvelles interfaces de contrôle d’interpréteur et tous les changements pickle/import/threads; `sys.remote_exec` exige un interpréteur distant de même major/minor selon la [doc Python 3.14](https://docs.python.org/3.14/library/sys.html#sys.remote_exec). |

Le projet revendique 3.11–3.14 et les jobs test/lint principaux ont une matrice de ces versions (`pyproject.toml`, lignes 12–24; workflows test/integration). Les jobs macOS/Windows consultés ne testent que Python 3.13 (`.github/workflows/cross-os.yml`, ligne 42). Cela ne prouve pas que le comportement adversarial Windows/macOS est le même en 3.11, 3.12 ou 3.14. La table `SENSITIVE_API` est manuelle, donc la couverture de tests fonctionnels n’équivaut pas à une revue exhaustive de nouvelles surfaces CPython.

La documentation Python rappelle que `sys.remote_exec` exécute du code dans l’interpréteur distant; le garde doit refuser l’API et ses alias, mais cela ne rend pas les autres API de contrôle sûres. Maintenir un diff de symboles sensibles par minor CPython et des tests qui vérifient à la fois les noms publics (`os`, `threading`, `sys`) et les modules C sous-jacents.

## Risques d’architecture et d’exploitation

1. **Identité OS partagée.** Aucun des processus Linux listés ne semble utiliser un UID hôte dédié par exécution. Les namespaces et les montages limitent la vue, mais les chemins bind/9p en écriture autorisent des modifications de fichiers de l’utilisateur appelant. Déplacer les workers sous un UID sans secrets, sans home sensible et avec droits de partage minimaux.
2. **Configuration de sécurité dépendante du profil.** Les options `py-sandbox`, `learn`, règles réseau, chemins exposés et paramètres Firejail/bwrap/unshare déterminent la frontière. Un profil inexistant peut activer l’apprentissage. Valider le profil résolu et les valeurs effectives avant de lancer le code.
3. **Environnement et héritage de descripteurs.** L’enfant reçoit un environnement construit depuis les règles, mais la revue doit inclure chaque provider, les descripteurs ouverts, sockets, fichiers temporaires, FIFOs, handles Windows et interfaces QEMU. Fermer explicitement tout handle non nécessaire et vérifier `pass_fds`/héritage en runtime.
4. **RPC local.** Le serveur est configuré pour loopback dans le cas standard et compare un bearer token en temps constant. `/ping` est sans authentification; cela divulgue seulement la présence du daemon, mais un bind réseau non loopback élargit immédiatement le risque. Garder loopback/hostfwd, secret aléatoire à usage unique, aucun log de secret, limites de requêtes HTTP et défense contre requêtes lentes.
5. **Canal de données et journalisation.** Capturer puis imprimer le stdout/stderr de l’enfant peut permettre de tromper les opérateurs ou d’injecter des séquences de terminal; la sortie devrait être plafonnée, neutralisée pour les logs et séparée des messages de sécurité.

## Plan de validation expérimentale recommandé

Effectuer ces tests dans une VM de test sans secrets, sous un compte non privilégié, avec un répertoire hôte jetable et des limites de ressources. Ne pas les lancer sur un poste contenant des données sensibles.

1. **Transport d’exceptions (priorité immédiate).** Créer une exception de test importable par parent et enfant, avec `__reduce__`/`__setstate__` qui crée uniquement un marqueur dans un répertoire jetable. La lever dans la fonction sandboxée et observer si le hook s’exécute dans le parent. Tester les modes exception riche et fallback. Réussite attendue après correction : aucun hook applicatif n’est exécuté côté parent.
2. **Résultat objet.** Dans un module de test chargé des deux côtés, retourner un objet avec reconstruction observable sans effet dangereux. Comparer `data-only`, `objects` avec garde active et garde désactivée. Vérifier le comportement des objets de dépendances usuelles. Résultat attendu : seule une allowlist explicite de types reconstruits peut traverser.
3. **Évasion Python sans OS.** En environnement jetable, tester références pré-importées, `posix`/`nt`, modules C, `ctypes`, `mmap`, sous-interpréteurs et mécanismes de code dynamique par minor 3.11–3.14. Avec `subprocess`, tout accès hôte prouve la limite attendue; ne pas classer une réussite de garde Python comme preuve d’isolation.
4. **Matrice provider.** Pour chaque provider disponible et chaque environnement supporté : vérifier l’accès à un fichier sentinelle hors règles, écriture hors bind, fichiers symlink/hardlink, sockets UNIX et abstraits, IPv4/IPv6, loopback/metadata cloud, fork/descendants, `ptrace`, `/proc`, création de namespaces, appels syscalls directs. Capturer `argv`, `/proc/<pid>/status`, namespaces, mounts, filtres seccomp/LSM et journaux.
5. **DoS et arrêt.** Tester boucle CPU, allocation mémoire, fork-bomb plafonnée, fichier temporaire volumineux, stdout sans fin, exception/pickle volumineux et annulation du client. Vérifier que les limites sont atteintes, que tous les descendants sont tués et que le daemon redevient disponible.
6. **Compatibilité croisée.** Ajouter au CI Windows/macOS Python 3.11, 3.12 et 3.14 pour les gardes et le transport; sur Linux, exécuter les tests providers sur noyaux/ABI Landlock min/max, avec et sans user namespaces, dans et hors conteneur.

## Ordre de remédiation

1. Supprimer la désérialisation riche des exceptions enfant → parent; écrire un test de régression prouvant qu’aucun hook pickle n’est exécuté dans le parent.
2. Restreindre le transport de résultat à `data-only` ou à un protocole de types fermé; retirer l’idée que la denylist protège les résultats arbitraires.
3. Introduire une politique d’isolation minimale obligatoire, avec échec fermé si le provider effectif est `subprocess`/`none` ou si une option demandée n’a pas été appliquée.
4. Ajouter quotas CPU, RAM, PIDs, fichiers, sortie et concurrence par exécution, avec kill de tout le groupe.
5. Tester les propriétés effectives de chaque provider avec des sondes adversariales isolées; documenter précisément les partages hôte modifiables.
6. Élargir CI cross-OS à 3.11–3.14 et automatiser la revue des APIs sensibles par minor CPython.
7. Renforcer l’usage en production : compte OS dédié sans secrets, répertoire de travail jetable, profil verrouillé, réseau fermé par défaut, mises à jour kernel/provider/hyperviseur.

## Limites de cette analyse

Cette passe est une revue statique ciblée, pas une certification ni un audit de code exhaustif. Aucune reproduction n’a confirmé un gadget d’exception exploitable dans une dépendance réelle, aucune évasion de provider n’a été exécutée et les niveaux de confinement effectifs n’ont pas été mesurés sur un noyau/runtime précis. Les constats conditionnels sont conservateurs et doivent être validés par les tests ci-dessus. Les CVE des dépendances, du noyau, de Firejail, QEMU, bwrap, slirp4netns et des images invitées nécessitent une vérification de versions au moment du déploiement.
