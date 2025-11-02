from tcp_socket import TCPSocket
import time

def main():
    """
    Função principal do cliente TCP.
    Realiza conexão com servidor, envia uma série de mensagens e recebe respostas.

    Fluxo:
      1. Cria socket TCP com porta aleatória.
      2. Conecta ao servidor no IP e porta especificados.
      3. Para cada mensagem:
         - envia ao servidor.
         - aguarda e imprime resposta recebida.
         - espera 1 segundo entre cada mensagem.
      4. Encerra a conexão ao final.
    """
    print("DEBUG CLIENTE: main iniciado")
    client = TCPSocket()  # Porta aleatória

    print("DEBUG CLIENTE: prestes a chamar connect")
    client.connect(("127.0.0.1", 12345))

    print("✅ Conectado ao servidor!")
    mensagens = ["Oi servidor!", "Como vai?", "Teste de transmissão", "sair"]

    for msg in mensagens:
        print(f"📤 Enviando: {msg}")
        client.send(msg.encode())
        resposta = client.recv()
        print(f"📩 Servidor respondeu: {resposta.decode()}")
        time.sleep(1)

    print("🔒 Encerrando conexão do lado cliente...")
    client.close()
    print("🛑 Cliente finalizado.")

if __name__ == "__main__":
    main()
