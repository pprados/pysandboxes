Le module utilise conjointement ces deux mécanismes : il s'appuie à la fois sur --bind (via bwrap) et sur l'utilitaire socat pour établir ce pont réseau.

Voici comment se déroule l'implémentation technique étape par étape :

Côté Hôte (Host) : Le runtime d'Anthropic lance un serveur proxy (SOCKS ou HTTP) sur la machine hôte. Ce serveur n'écoute pas sur un port TCP classique ouvert sur le réseau, mais sur un Unix Domain Socket (qui se présente sous la forme d'un fichier sur le disque, par exemple dans /tmp).

Le montage avec --bind : L'isolation réseau de bubblewrap est activée via l'argument --unshare-net, ce qui supprime toutes les interfaces réseau du conteneur (sauf la boucle locale lo). Pour permettre au processus isolé de parler au proxy de l'hôte, bwrap utilise un montage de type --bind (ou --dev-bind) pour monter le fichier de socket Unix de l'hôte directement à l'intérieur du système de fichiers de la sandbox.

Le rôle de socat dans la Sandbox : La plupart des outils réseau (comme curl, wget ou les librairies HTTP en Python) ne savent pas nativement envoyer des requêtes web à travers un socket Unix ; ils s'attendent à cibler une IP et un port TCP. Pour résoudre ce problème, le runtime démarre le binaire socat à l'intérieur de la sandbox. socat écoute sur un port TCP local (dans l'environnement isolé) et joue le rôle de relais bidirectionnel en redirigeant tout ce qu'il reçoit vers le fichier de socket Unix monté par bubblewrap.