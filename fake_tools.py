link = "https://docs.scipy.org/doc/numpy/user/basics.broadcasting.html"


class Fake_tools():

    def load_request(self):
        import requests

        f = requests.get(link)
        # print(f.text)

    def load_urlopen(self):
        from urllib.request import urlopen

        f = urlopen(link)
        myfile = f.read()
        # print(myfile)

    def load_socket(self):
        import socket

        HOST = 'docs.scipy.org'  # The remote host
        PORT = 80  # The same port as used by the server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(b'GET /doc/numpy/user/basics.broadcasting.html HTTM/1.0\n'
                      b'Host:docs.scipy.org\n'
                      b'\n')
            data = s.recv(1024)
        # print('Received', repr(data))

    def listen_port(self):
        # Informations du serveur
        import socket
        host = '127.0.0.1'  # Écouter sur toutes les interfaces si '' est utilisé
        port = 12345  # Port d'écoute du serveur

        # Créer un socket TCP
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Associer le socket à l'adresse et au port
            s.bind((host, port))
            # Commencer à écouter les connexions entrantes (1 connexion en attente max)
            s.listen(1)
            print(f"Serveur en écoute sur {host}:{port}...")

            # Attendre une connexion entrante
            conn, addr = s.accept()
            with conn:
                print(f"Connecté par {addr}")
                while True:
                    # Recevoir des données du client (jusqu'à 1024 octets)
                    data = conn.recv(1024)
                    if not data:
                        break
                    print(f"Reçu du client: {data.decode('utf-8')}")

                    # Renvoyer une réponse au client
                    response = "Message reçu !"
                    conn.sendall(response.encode('utf-8'))