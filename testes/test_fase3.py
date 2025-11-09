"""
Teste completo da Fase 3 (TCP simplificado sobre UDP).

Testa:
    - Handshake (three-way)
    - Transferência de dados (10KB e 1MB)
    - Controle de fluxo (janela de recepção reduzida)
    - Retransmissão simulada por perda de pacotes
    - Encerramento (four-way)
    - Gráfico de desempenho (throughput e RTT estimado pelo cliente)

Executar:
    python -m testes.test_fase3

OBS: Usa a implementação TCPSocket presente em fase3/tcp_socket.py
"""

import threading
import time
import sys
import os
import random
import matplotlib.pyplot as plt

# Permitir import dos módulos da fase3
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'fase3')))
from tcp_socket import TCPSocket

# --------------------------- Helpers ---------------------------


def _temporary_drop_sendto(probability):
    """
    Monkeypatch para socket.sendto que descarta pacotes com determinada probabilidade.

    Args:
        probability (float): Probabilidade de descartar um pacote (0 a 1).

    Returns:
        function: Função original sendto para restauração.
    """
    import socket
    orig = socket.socket.sendto

    def patched_sendto(self, data, addr):
        """Função substituta para sendto que simula perda de pacotes."""
        if random.random() < probability:
            # Simula perda de pacote
            return len(data)
        return orig(self, data, addr)

    socket.socket.sendto = patched_sendto
    return orig


def mbps(bytes_sent, seconds):
    """
    Converte bytes/segundo para MB/s.

    Args:
        bytes_sent (int): Quantidade de bytes enviados.
        seconds (float): Tempo decorrido em segundos.

    Returns:
        float: Throughput em MB/s.
    """
    return (bytes_sent / 1e6) / max(seconds, 1e-9)


# --------------------------- Test routines ---------------------------


def run_handshake_test(server_port=8000, client_port=9000, timeout=5.0):
    """
    Testa o three-way handshake entre cliente e servidor.

    Args:
        server_port (int): Porta do servidor.
        client_port (int): Porta do cliente.
        timeout (float): Tempo máximo de espera em segundos.

    Returns:
        bool: True se handshake completado com sucesso, False caso contrário.
    """
    result = {"server_connected": False, "client_connected": False}

    def server_task():
        """Thread do servidor que aceita conexão TCP."""
        srv = TCPSocket(local_addr=("127.0.0.1", server_port))
        srv.accept()  # bloqueia até handshake
        result["server_connected"] = srv.connected
        server_task.srv = srv  # referência para fechamento

    def client_task():
        """Thread do cliente que inicia conexão TCP."""
        cli = TCPSocket(local_addr=("127.0.0.1", client_port))
        cli.connect(("127.0.0.1", server_port))
        result["client_connected"] = cli.connected
        client_task.cli = cli

    # Inicia threads do servidor e cliente
    t_srv = threading.Thread(target=server_task, daemon=True)
    t_srv.start()
    time.sleep(0.05)
    t_cli = threading.Thread(target=client_task, daemon=True)
    t_cli.start()

    # Aguarda handshake ou timeout
    start = time.time()
    while time.time() - start < timeout:
        if result["server_connected"] and result["client_connected"]:
            break
        time.sleep(0.01)

    ok = result["server_connected"] and result["client_connected"]

    # Cleanup: fecha sockets
    try:
        if hasattr(client_task, "cli"):
            client_task.cli.close()
    except Exception:
        pass
    try:
        if hasattr(server_task, "srv"):
            server_task.srv.close()
    except Exception:
        pass

    return ok


def run_transfer_test(data_bytes, server_port=8000, client_port=9000, drop_prob=0.0):
    """
    Testa a transferência de dados do cliente para o servidor.

    Args:
        data_bytes (int): Quantidade de bytes a enviar.
        server_port (int): Porta do servidor.
        client_port (int): Porta do cliente.
        drop_prob (float): Probabilidade de perda simulada.

    Returns:
        dict: Métricas da transferência (sucesso, throughput, RTT, etc.).
    """
    orig_sendto = None
    if drop_prob > 0:
        orig_sendto = _temporary_drop_sendto(drop_prob)

    server = TCPSocket(local_addr=("127.0.0.1", server_port))
    server_thread_ready = threading.Event()

    def server_thread():
        """Thread que recebe os dados do cliente e fecha o socket."""
        try:
            server.accept()
            server_thread_ready.set()
            received = bytearray()

            # Recebe dados até o cliente fechar ou atingir total esperado
            while True:
                chunk = server.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
                if len(received) >= data_bytes:
                    break

            server.received = bytes(received)
        finally:
            # Fecha o socket ao terminar
            try:
                server.close()
            except Exception:
                pass

    t_srv = threading.Thread(target=server_thread, daemon=True)
    t_srv.start()

    client = TCPSocket(local_addr=("127.0.0.1", client_port))
    time.sleep(0.05)
    client.connect(("127.0.0.1", server_port))

    # Espera o servidor estar pronto
    server_thread_ready.wait(timeout=2.0)
    if not server_thread_ready.is_set():
        print("Aviso: Servidor não completou o accept a tempo.")

    # Envio em blocos de acordo com recv_window
    chunk_size = client.recv_window if client.recv_window > 0 else 1024
    t0 = time.time()
    bytes_sent = 0
    while bytes_sent < data_bytes:
        block = b"x" * min(chunk_size, data_bytes - bytes_sent)
        client.send(block)
        bytes_sent += len(block)

    # Cliente fecha conexão (envia FIN)
    try:
        client.close()
    except Exception:
        pass

    # Aguarda thread do servidor terminar
    t_srv.join(timeout=20.0)

    t1 = time.time()
    elapsed = t1 - t0
    throughput_val = mbps(bytes_sent, elapsed)
    client_rtt = getattr(client, "estimated_rtt", None)
    received_len = len(getattr(server, "received", b""))
    success = (received_len == data_bytes)

    # Cleanup
    try:
        server.close()
    except Exception:
        pass

    if orig_sendto is not None:
        import socket
        socket.socket.sendto = orig_sendto

    return {
        "success": success,
        "elapsed": elapsed,
        "throughput_MBs": throughput_val,
        "client_rtt": client_rtt,
        "bytes_sent": bytes_sent,
        "bytes_received": received_len,
        "drop_prob": drop_prob,
    }


def run_flow_control_test(total_bytes=10240, recv_window=1024, server_port=8000, client_port=9000):
    """
    Testa controle de fluxo reduzindo a janela de recepção do servidor.

    Args:
        total_bytes (int): Quantidade total de bytes a enviar.
        recv_window (int): Tamanho da janela de recepção do servidor.
        server_port (int): Porta do servidor.
        client_port (int): Porta do cliente.

    Returns:
        dict: Métricas de transferência (bytes enviados, recebidos e throughput).
    """
    server = TCPSocket(local_addr=("127.0.0.1", server_port), recv_window=recv_window)

    def server_thread():
        """Thread que recebe os dados do cliente respeitando recv_window."""
        server.accept()
        received = bytearray()
        while len(received) < total_bytes:
            chunk = server.recv(65536)
            if not chunk:
                break
            received.extend(chunk)
        server.received = bytes(received)

    t_srv = threading.Thread(target=server_thread, daemon=True)
    t_srv.start()

    client = TCPSocket(local_addr=("127.0.0.1", client_port))
    time.sleep(0.05)
    client.connect(("127.0.0.1", server_port))

    # Envio em blocos maiores que recv_window
    t0 = time.time()
    sent = 0
    chunk_size = 2048
    while sent < total_bytes:
        block = b"x" * min(chunk_size, total_bytes - sent)
        client.send(block)
        sent += len(block)

    # Pequena espera para garantir recebimento
    time.sleep(1.0 + total_bytes / 1e6)
    t1 = time.time()

    throughput_val = mbps(sent, t1 - t0)
    received_len = len(getattr(server, "received", b""))

    # Cleanup
    client.close()
    server.close()

    return {
        "sent": sent,
        "received": received_len,
        "throughput_MBs": throughput_val,
        "recv_window": recv_window,
    }


# --------------------------- Main test runner ---------------------------


def main():
    """Executa todos os testes da Fase 3 e gera relatório com gráfico."""
    print("=== Iniciando testes da Fase 3 (TCP simplificado) ===")
    results = {}

    # Test 1: Handshake
    print("\n[TEST 1] Handshake (3-way)")
    ok = run_handshake_test()
    print("Handshake OK?", ok)
    results["handshake_ok"] = ok

    # Test 2: Transferência 10KB
    print("\n[TEST 2] Transferência 10KB")
    res_10kb = run_transfer_test(10 * 1024)
    print(res_10kb)
    results["10KB"] = res_10kb

    # Test 3: Controle de fluxo (recv_window=1KB)
    print("\n[TEST 3] Controle de fluxo (recv_window=1KB)")
    flow_res = run_flow_control_test(total_bytes=10 * 1024, recv_window=1024)
    print(flow_res)
    results["flow"] = flow_res

    # Test 4: Retransmissão (simular perda 20%)
    print("\n[TEST 4] Retransmissão com perda simulada (20%)")
    res_loss = run_transfer_test(50 * 1024, drop_prob=0.20)
    print(res_loss)
    results["loss_20"] = res_loss

    # Test 5: Desempenho - Transferência 1MB
    print("\n[TEST 5] Desempenho - transfer 1MB")
    res_1mb = run_transfer_test(1024 * 1024)
    print(res_1mb)
    results["1MB"] = res_1mb

    # Gera gráfico (Throughput e RTT)
    labels = ["10KB", "50KB_loss20%", "1MB"]
    throughputs = [
        results["10KB"]["throughput_MBs"],
        results["loss_20"]["throughput_MBs"],
        results["1MB"]["throughput_MBs"],
    ]
    rtts = [
        results["10KB"]["client_rtt"] or 0,
        results["loss_20"]["client_rtt"] or 0,
        results["1MB"]["client_rtt"] or 0,
    ]

    plt.figure(figsize=(10, 4))
    plt.subplot(1, 2, 1)
    plt.bar(labels, throughputs)
    plt.ylabel("Throughput (MBps)")
    plt.title("Throughput em testes selecionados")

    plt.subplot(1, 2, 2)
    plt.bar(labels, rtts)
    plt.ylabel("Estimated RTT (s)")
    plt.title("RTT estimado pelo TCPSocket")

    plt.tight_layout()
    plt.savefig("fase3_desempenho.png", dpi=150)
    print("\nGráfico salvo em: fase3_desempenho.png")

    print("\n=== Resultados resumidos ===")
    for k, v in results.items():
        print(k, v)

    print("\n✅ Testes da Fase 3 finalizados.")


if __name__ == "__main__":
    main()
