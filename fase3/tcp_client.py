from tcp_socket import TCPSocket
import time


def main():
    """
    Função principal do cliente TCP.

    Fluxo:
      1. Cria um socket TCP com porta aleatória.
      2. Conecta ao servidor no IP e porta especificados.
      3. Para cada mensagem:
         - envia ao servidor,
         - aguarda e imprime a resposta recebida,
         - espera 1 segundo entre cada mensagem.
      4. Encerra a conexão ao final.
    """
    print("DEBUG CLIENTE: main iniciado")

    # Cria cliente TCP com porta aleatória
    client = TCPSocket()

    print("DEBUG CLIENTE: prestes a chamar connect")
    client.connect(("127.0.0.1", 12345))
    print("✅ Conectado ao servidor!")

    mensagens = ["Oi servidor!", "Como vai?", "Teste de transmissão", "sair"]

    for msg in mensagens:
        # Envia mensagem ao servidor
        print(f"📤 Enviando: {msg}")
        client.send(msg.encode())

        # Recebe resposta do servidor
        resposta = client.recv()
        print(f"📩 Servidor respondeu: {resposta.decode()}")

        # Pequena pausa entre envios
        time.sleep(1)

    # Encerra conexão
    print("🔒 Encerrando conexão do lado cliente...")
    client.close()
    print("🛑 Cliente finalizado.")


if __name__ == "__main__":
    main()
