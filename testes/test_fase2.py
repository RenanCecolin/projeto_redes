"""
Testes comparativos de protocolos: rdt3.0 (Stop-and-Wait), Go-Back-N e Selective Repeat.

Mede throughput, retransmissões, utilização e verifica perdas/ordenação.
Gera gráficos comparativos de desempenho.
"""

import time
import sys
import os
import matplotlib.pyplot as plt

# Permitir import dos módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.simulator import UnreliableChannel
from fase1.rdt30 import RDT30Sender, RDT21Receiver
from fase2.gbn import GBNSender, GBNReceiver
from fase2.sr import SR_Sender, SR_Receiver


import threading
import time

def run_protocol_test(name, sender_cls, receiver_cls, total_chunks=1024, chunk_size=1024,
                      window_size=1, loss_rate=0.1, delay_range=(0.01, 0.05), verbose=False,
                      test_out_of_order=False):
    """
    Executa um teste completo para um protocolo confiável.

    Retorna:
        dict: métricas (tempo, throughput, retransmissões, recebidos, utilização)
    """
    port = 14000 + hash(name + str(window_size)) % 1000
    ch = UnreliableChannel(loss_rate=loss_rate, corrupt_rate=0.0, delay_range=delay_range, verbose=False)

    received = []

    def deliver(data):
        received.append(data)

    # === Criação dos objetos de envio e recepção ===
    if name == "SR":
        receiver = receiver_cls(channel=ch, window_size=window_size)
        sender = sender_cls(channel=ch, window_size=window_size, timeout=1.0)

        # 🟢 Inicia o receiver em uma thread separada
        threading.Thread(target=receiver.receive, daemon=True).start()

    elif name == "GBN":
        receiver = receiver_cls(local_addr=('localhost', port), deliver_callback=deliver, channel=ch, verbose=verbose)
        sender = sender_cls(local_addr=('localhost', 0), dest_addr=('localhost', port),
                            channel=ch, N=window_size, timeout=1.0, verbose=verbose)
    else:  # RDT3.0
        receiver = receiver_cls(local_addr=('localhost', port), deliver_callback=deliver, channel=ch, verbose=verbose)
        sender = sender_cls(local_addr=('localhost', 0), dest_addr=('localhost', port),
                            channel=ch, timeout=1.0, verbose=verbose)

    # === Envio dos dados ===
    data = b'x' * chunk_size
    t0 = time.time()

    for i in range(total_chunks):
        sender.send(data)
        if verbose and i % 100 == 0:
            print(f"[{name}] Enviando chunk {i}")

    t1 = time.time()
    elapsed = t1 - t0
    if elapsed == 0:
        elapsed = 0.000001  # evita divisão por zero

    # Espera o recebimento completo
    time.sleep(2.0)

    # === Métricas ===
    delivered_count = len(received)
    total_data = chunk_size * total_chunks
    throughput = total_data / elapsed / 1e6  # MBps
    utilization = throughput / (8 / (delay_range[0] + delay_range[1]))  # taxa relativa
    retrans = getattr(sender, "retransmissions", 0)

    # Verificação de completude
    ok = delivered_count == total_chunks
    if not ok:
        print(f"[WARN] {name} entregou apenas {delivered_count}/{total_chunks} chunks!")

    # Teste de ordenação (apenas SR)
    if name == "SR" and test_out_of_order:
        print("[SR TEST] Simulando entrega fora de ordem.")
        ch.delay_range = (0.01, 0.5)
        # reenviar pequenos pacotes para testar buffer
        for i in range(5):
            sender.send(b"TesteSR" + bytes([i]))

    try:
        sender.close()
        receiver.close()
    except Exception:
        pass

    return {
        'protocol': name,
        'window': window_size,
        'time': elapsed,
        'throughput': throughput,
        'utilization': utilization,
        'retransmissions': retrans,
        'received': delivered_count
    }

def main():
    total_chunks = 1024 # 1024 * 1024 bytes = 1 MB
    results = []

    # === Teste RDT3.0 (Stop and Wait) ===
    print("\n=== Testando RDT3.0 (Stop-and-Wait) ===")
    rdt3 = run_protocol_test("RDT3", RDT30Sender, RDT21Receiver, total_chunks=total_chunks, window_size=1)
    results.append(rdt3)

    # === Teste Go-Back-N ===
    print("\n=== Testando Go-Back-N ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("GBN", GBNSender, GBNReceiver, total_chunks=total_chunks, window_size=N)
        results.append(res)

    # === Teste Selective Repeat ===
    print("\n=== Testando Selective Repeat ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("SR", SR_Sender, SR_Receiver, total_chunks=total_chunks,
                                window_size=N, test_out_of_order=True if N == 10 else False)
        results.append(res)

    # === Exibir resultados ===
    print("\n==== RESULTADOS ====")
    for r in results:
        print(f"{r['protocol']} (N={r['window']}): "
              f"tempo={r['time']:.2f}s, throughput={r['throughput']:.2f}MBps, "
              f"utilização={r['utilization']:.4f}, retransmissões={r['retransmissions']}, "
              f"recebidos={r['received']}")

    # === Gráficos comparativos ===
    plt.figure(figsize=(8, 5))
    gbn = [r for r in results if r['protocol'] == 'GBN']
    sr = [r for r in results if r['protocol'] == 'SR']

    plt.plot([r['window'] for r in gbn], [r['throughput'] for r in gbn], marker='o', label='GBN')
    plt.plot([r['window'] for r in sr], [r['throughput'] for r in sr], marker='s', label='SR')
    plt.axhline(y=rdt3['throughput'], color='gray', linestyle='--', label='RDT3.0')
    plt.xlabel("Tamanho da Janela (N)")
    plt.ylabel("Throughput (MBps)")
    plt.title("Desempenho dos Protocolos Confiáveis")
    plt.legend()
    plt.grid(True)
    plt.savefig("comparativo_protocolos.png", dpi=120)
    plt.show()


if __name__ == "__main__":
    main()
