"""
Script para teste integrado da fase 3.
Inicia servidor e cliente TCP em threads diferentes,
esperando o servidor iniciar antes de iniciar o cliente.
Ao final, aguarda ambas as threads terminarem e imprime mensagem de sucesso.

Exemplo de execução: python testes/test_fase3.py
"""

import threading
import time
import sys
import os

# Ajusta caminho para importar os módulos da fase3
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'fase3')))
from tcp_server import main as server_main
from tcp_client import main as client_main


if __name__ == "__main__":
    # Cria e inicia thread do servidor
    t_server = threading.Thread(target=server_main)
    t_server.start()

    print("Aguardando o servidor inicializar...")
    time.sleep(0.3)  # Pequena espera para garantir servidor ativo antes do cliente

    # Cria e inicia thread do cliente
    t_client = threading.Thread(target=client_main)
    t_client.start()

    # Aguarda término do cliente e depois do servidor
    t_client.join()
    t_server.join()

    print("\n✅ Teste da Fase 3 concluído com sucesso!")
