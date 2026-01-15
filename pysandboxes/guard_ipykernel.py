import jupyter_client

# 1. On utilise le même KernelManager pour lancer le processus
km = jupyter_client.KernelManager()
km.start_kernel()

try:
    # 2. On obtient un client pour communiquer avec ce kernel
    kc = km.client()

    # 3. Le client doit démarrer ses propres canaux de communication
    kc.start_channels()
    print("Client connecté et canaux de communication ouverts.")

    # 4. Préparons du code à exécuter
#     code = """
# import time
# print("Bonjour depuis le kernel !")
# time.sleep(2)
# a = 42
# print(f"La variable 'a' a été créée.")
# a * 2  # C'est le résultat qui sera retourné
# """
    code = """
3+5
"""

    print("\n--- Envoi du code pour exécution ---")

    # 5. On exécute le code. Cela envoie un message sur le canal 'shell'.
    # On récupère l'ID du message pour suivre les réponses associées.
    msg_id = kc.execute(code)
    print(f"Code envoyé avec l'ID de message : {msg_id}")

    print("\n--- Réception des messages du kernel ---")

    # 6. Boucle pour écouter les messages sur le canal iopub
    while True:
        try:
            # On attend un message du kernel (avec un timeout pour ne pas bloquer indéfiniment)
            msg = kc.get_iopub_msg(timeout=1)

            # On vérifie que le message reçu est bien une réponse à notre requête
            if msg['parent_header'].get('msg_id') == msg_id:
                msg_type = msg['header']['msg_type']
                content = msg['content']

                # On affiche les sorties de type 'print'
                if msg_type == 'stream':
                    print(f"[Sortie Print] : {content['text'].strip()}")

                # On affiche le résultat final de l'exécution
                elif msg_type == 'execute_result':
                    print(f"[Résultat] : {content['data']['text/plain']}")

                # On regarde l'état du kernel. S'il est 'idle', il a fini de travailler.
                elif msg_type == 'status' and content['execution_state'] == 'idle':
                    print("[Status] : Kernel inactif, l'exécution est terminée.")
                    break  # On sort de la boucle

        except Exception:
            # La file d'attente est vide, on continue d'attendre
            pass

finally:
    print("\n--- Nettoyage ---")
    # On arrête les canaux du client
    kc.stop_channels()
    # On arrête le processus du kernel
    km.shutdown_kernel(now=True)
    print("Canaux et kernel arrêtés.")