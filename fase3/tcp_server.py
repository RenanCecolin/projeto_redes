from tcp_socket import TCPSocket

def main():
    """
    Função principal do servidor TCP.
    Configura socket para escutar conexões em endereço e porta especificados,
    aceita conexão de cliente, recebe mensagens e responde, até o cliente encerrar.

    Fluxo:
      1. Cria socket TCP e liga ao endereço local definido.
      2. Aguarda conexão do cliente.
      3. Em loop, recebe mensagens do cliente.
         - Encerra se mensagem vazia ou comando 'sair'.
         - Imprime e responde com mensagem de confirmação.
      4. Fecha conexão quando cliente encerra.
    """
    print("DEBUG SERVER: main iniciado")
    server = TCPSocket(local_addr=("127.0.0.1", 12345))
    print("🖥️ Servidor aguardando conexão...")
    server.accept()
    print("✅ Conexão estabelecida com o cliente!")

    while True:
        data = server.recv()
        if not data:
            break
        print(f"📩 Mensagem recebida: {data.decode()}")
        if data.decode().lower() == "sair":
            print("🚪 Cliente solicitou encerramento.")
            break
        server.send(b"Mensagem recebida com sucesso!")

    print("🔒 Encerrando conexão do lado servidor...")
    server.close()
    print("🛑 Servidor finalizado.")

if __name__ == "__main__":
    main()
