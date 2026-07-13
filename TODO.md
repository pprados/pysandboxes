Modifier les copyright 2025-2026
Augmenter la couverture de tests pour les autres guards
Améliorer le README en tant que harnais.
Faire le ménage sur les scories des outils IA (openmemory, etc)
Il faudra publier les images dockers/qemu
généraliser l'utiliser de __slots__ ?
Enrichir la doc des samples et les samples

Piste non explorée : provider "proxy" (ex-wiki/proxy.md)
  Approche utilisée par le runtime d'Anthropic pour donner un accès réseau filtré
  à une sandbox bwrap sans lui ouvrir le réseau. Combine --bind et socat :
  - Hôte : un serveur proxy (SOCKS ou HTTP) écoute sur un socket Unix (un fichier
    sur disque, typiquement dans /tmp), pas sur un port TCP exposé.
  - Isolation : bwrap est lancé avec --unshare-net, ce qui supprime toutes les
    interfaces réseau du conteneur sauf lo. Le socket Unix de l'hôte est monté
    dans la sandbox via --bind (ou --dev-bind).
  - Sandbox : curl, wget et les librairies HTTP Python ne savent pas parler à un
    socket Unix, elles attendent une IP et un port TCP. socat est démarré dans la
    sandbox, écoute sur un port TCP local et relaie en bidirectionnel vers le
    socket Unix monté.
  Intérêt pour pysandboxes : point de sortie réseau unique et filtrable par
  domaine, là où netfilter ne sait travailler qu'au niveau IP (voir wiki/dns.md).
  Référencé comme item non implémenté dans wiki/roadmap.md.