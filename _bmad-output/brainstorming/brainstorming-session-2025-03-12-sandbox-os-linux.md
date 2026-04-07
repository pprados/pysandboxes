# Brainstorming Session: Solutions de sandbox OS sous Linux

**Date:** 2025-03-12  
**Objectif:** Identifier d'autres solutions de sandbox OS sous Linux (au-delà de subprocess, bwrap, firejail, unshare, landlock déjà intégrés dans pysandboxes).

---

## Contexte projet

- **pysandboxes** propose une couche Python (guards) + une couche OS (providers/daemons).
- Providers actuels : `none`, `subprocess`, `bwrap`, `firejail`, `unshare`, `landlock`.
- Roadmap et TODOs mentionnent : podman, docker, lxc, Flatpak, bubblejail, AppArmor, micro-VM (Firecracker, Kata, etc.).

---

## 1. Inventaire des idées par thème

### Thème 1 : Outils légers (namespaces + seccomp, style bwrap/firejail)

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **NsJail** | Google, namespaces + cgroups + seccomp-bpf, modes LISTEN/ONCE/RERUN, support user namespace | Alternative riche (TCP inetd, limites CPU/RAM, politiques Kafel), bon pour fuzzing ou services |
| **Hakoniwa** | Isolation processus (namespaces, limites, seccomp) | Léger, une option de plus dans la même catégorie |
| **Callander** | Sandboxing par filtrage de syscalls (simple) | Très simple, possible complément seccomp-only |
| **minijail** | Chrome/Chromium, namespaces + seccomp | Référence sécurité, mais plutôt orienté Chrome |
| **runc** | Runtime OCI standard (containers) | Si on veut un provider "container OCI" générique |

### Thème 2 : Wrappers / écosystème Bubblewrap

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **Bubblejail** (igo95862) | Sandbox desktop basé sur bwrap, profils TOML, seccomp + D-Bus, GUI | Réutilisation de patterns (profils, permissions) ou inspiration pour UX config |
| **Flatpak** | Apps sandboxées avec bwrap sous le capot, portals | Provider "flatpak" si on veut lancer du code dans un contexte Flatpak |
| **bwrap-oci** | OCI sur bwrap | Aligner avec écosystème OCI sans daemon lourd |

### Thème 3 : Containers (Docker, Podman, LXC)

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **Podman** | Rootless, pas de daemon, compatible Docker | Déjà dans la roadmap ; priorité haute (rootless = pas de socket) |
| **Docker** | Avec --privileged ou DinD | Déjà évoqué ; utile en dev/CI, moins en prod sécurisée |
| **LXC / LXD** | Conteneurs système légers | Isolation forte, une option "container système" |
| **Kubernetes** | Orchestration | Provider "pod" pour exécution dans un cluster (roadmap) |

### Thème 4 : Micro-VM et isolation forte

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **gVisor** | Noyau userspace (Go), runsc = runtime OCI | Isolation type VM, coût raisonnable ; provider "gvisor" si runtime disponible |
| **Firecracker** | Micro-VM (AWS Lambda, etc.) | Très forte isolation, plutôt pour déploiement serverless |
| **Kata Containers** | Containers dans des micro-VM | Déjà roadmap ; pour environnements à haute sécurité |
| **Cloud Hypervisor / QEMU-microvm** | Hyperviseurs légers | Pour scénarios "VM légère" dédiés |

### Thème 5 : LSM et renforcement noyau

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **AppArmor** | Profils LSM (fichiers, capacités, réseau) | Déjà en TODO ; peut être paramétré en plus de bwrap/firejail |
| **SELinux** | LSM (contexte, types) | Renforcement sur distros qui l’utilisent (RHEL, Fedora) |
| **Landlock** | Déjà intégré | LSM sans privilège, whitelist fichiers/réseau (ABI v5) |

### Thème 6 : Outils système et “chroot amélioré”

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **systemd-nspawn** | Conteneurs légers systemd (namespaces, chroot++) | Très répandu ; support unprivileged en amélioration (rpm-ostree, etc.) |
| **proot** | Chroot-like en userspace (sans root) | Intérêt pour environnements sans user namespace ou très restreints |
| **rpm-ostree** | Images immuables + nspawn | Roadmap ; déploiement OS immuable |

### Thème 7 : Niche et émergent

| Solution | Description | Intérêt pour pysandboxes |
|----------|-------------|---------------------------|
| **container2wasm** | Container → WebAssembly | Roadmap ; exécution en sandbox WASM |
| **Cloud morph** | (à préciser) | Roadmap |
| **Daemon externe** | Provider qui se connecte à un daemon déjà démarré | Déjà TODO ; utile pour debug, CI, déploiements custom |
| **Sub-interpreter** | Python sub-interpreter (PEP 554) | Roadmap "sub interpreter" ; isolation in-process, pas OS |

---

## 2. Synthèse et critères

- **Déjà en place :** none, subprocess, bwrap, firejail, unshare, landlock.  
- **Alignés roadmap / TODOs :** podman, docker, lxc, Flatpak, bubblejail (inspiration), AppArmor, Kata, Firecracker, gVisor, systemd-nspawn / rpm-ostree, container2wasm, daemon externe, sub-interpreter.

**Critères utiles pour prioriser :**

- **Privilèges :** rootless > root (podman, landlock, bwrap unprivileged, nspawn unprivileged).
- **Intégration :** possibilité de lancer un processus Python dans le sandbox et de communiquer (stdin/stdout, socket, ou SSE comme aujourd’hui).
- **Maturité :** large déploiement (runc, podman, systemd-nspawn) vs expérimental.
- **Cohérence avec l’architecture :** un daemon qui étend `BaseDaemon` / `BaseSubProcessDaemon` et qui appelle un binaire (podman, docker, nsjail, etc.) ou qui s’appuie sur une API (Kubernetes).

---

## 3. Priorisation proposée

**Priorité haute (aligné roadmap, fort impact)**  
1. **Podman** — rootless, pas de socket, déjà prévu.  
2. **Daemon externe** — flexibilité déploiement / CI.  
3. **AppArmor** — paramétrage en couche supplémentaire (ex. avec bwrap/firejail).

**Priorité moyenne (extension naturelle)**  
4. **NsJail** — remplace ou complète un “subprocess durci” (limites, seccomp, mode inetd).  
5. **systemd-nspawn** — très présent sur Linux moderne.  
6. **Docker** — pour dev/CI (avec les précautions déjà décrites dans la roadmap).  
7. **Flatpak / bwrap-oci** — si besoin d’alignement avec écosystème desktop/OCI.

**Priorité plus basse (spécialisé ou long terme)**  
8. **gVisor** — si besoin d’isolation type “noyau userspace”.  
9. **LXC/LXD** — pour option “container système”.  
10. **Bubblejail** — surtout comme référence (profils, UX) plutôt que provider direct.  
11. **Kata / Firecracker / QEMU-microvm** — micro-VM (roadmap long terme).  
12. **Hakoniwa, Callander, minijail** — à considérer si besoin de variantes légères ou spécifiques.

---

## 4. Prochaines actions suggérées

1. **Court terme**  
   - Affiner le design du provider **Podman** (comment on lance le conteneur, réseau, bind mounts) et l’ajouter à `providers_factory`.  
   - Documenter le contrat du **daemon externe** (env, socket, token) et ajouter un provider qui s’y connecte.  
   - Étudier l’ajout de **paramètres AppArmor** (ex. `apparmor.profile=...`) pour bwrap/firejail.

2. **Moyen terme**  
   - POC **NsJail** : un `NsJailSSEDaemon` qui lance le processus Python via `nsjail` avec une config dérivée des règles (bind, seccomp, limites).  
   - Évaluer **systemd-nspawn** en mode unprivileged (bind mounts, etc.) pour un provider optionnel.

3. **Documentation / roadmap**  
   - Mettre à jour la roadmap avec les solutions de ce brainstorming (NsJail, gVisor, systemd-nspawn, AppArmor, bubblejail comme référence).  
   - Ajouter une page wiki ou une section “OS sandbox options” listant toutes les solutions (déjà intégrées + candidates) avec tableau comparatif (privilèges, isolation, usage typique).

---

## 5. Session summary

- **Objectif :** Identifier d’autres solutions de sandbox OS sous Linux.  
- **Résultat :** Une vingtaine de solutions classées en 7 thèmes (outils légers, wrappers bwrap, containers, micro-VM, LSM, système/chroot, niche).  
- **Priorités :** Podman, daemon externe et AppArmor en tête ; NsJail et systemd-nspawn en suite logique ; le reste en option ou long terme.  
- **Actions :** Intégration Podman + daemon externe + paramètres AppArmor ; POC NsJail ; mise à jour roadmap et doc.

---

*Session brainstorming Bmad — identifier d'autres solutions de sandbox OS sous Linux.*
