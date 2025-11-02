"""
tests/test_fase2.py
Teste robusto do protocolo Go-Back-N (GBN) avaliando throughput
em função do tamanho da janela, com debug opcional.

Exemplo de execução:
python testes/test_fase2.py
"""

import time
import sys
import os
import matplotlib.pyplot as plt

# Ajusta caminho para importar módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_gbn_var_window():
    """
    Testa desempenho do GBN variando o tamanho da janela.
    Avalia throughput, tempo, retransmissões para cada tamanho.

    Configuração:
        - Perda de 10% de pacotes.
        - Sem corrupção.
        - Delay variável entre 10ms e 50ms.
        - Envio de 32 chunks de 1024 bytes cada.
    """
    from utils.simulator import UnreliableChannel
    from fase2.gbn import GBNSender, GBNReceiver

    N_list = [1, 5, 10, 20]
    results = []
    total_chunks = 32  # Teste reduzido para facilitar debug

    for N in N_list:
        print(f"\n==== Testando janela N={N} ====")
        port = 15000 + N  # Porta única para cada teste
        ch = UnreliableChannel(loss_rate=0.10, corrupt_rate=0.0, delay_range=(0.01, 0.05), verbose=False)
        received = []

        def deliver(b):
            print("Pacote entregue à aplicação:", len(b))
            received.append(b)

        receiver = GBNReceiver(local_addr=('localhost', port), deliver_callback=deliver, channel=ch, verbose=False)
        sender = GBNSender(local_addr=('localhost', 0), dest_addr=('localhost', port),
                           channel=ch, N=N, timeout=1.0, verbose=False)

        data = b'x' * 1024
        t0 = time.time()
        for i in range(total_chunks):
            sender.send(data)
            print(f"[TESTE] Sender enviou chunk {i}")
        t1 = time.time()

        print("[TESTE] Esperando recebimento final...")
        time.sleep(2)

        throughput = (1024 * total_chunks) / (t1 - t0) / 1e6  # em MBps
        print(f"Janela {N} entregou {len(received)} chunks, tempo={t1-t0:.2f}s, throughput={throughput:.2f} MBps, retransmissões={sender.retransmissions}")

        results.append({'N': N, 'time': t1 - t0, 'throughput': throughput, 'retransmissions': sender.retransmissions})
        sender.close()
        receiver.close()

    print("\n==== Resultados ====")
    for r in results:
        print(f"N={r['N']}, tempo={r['time']:.2f}s, throughput={r['throughput']:.2f} MBps, retransmissions={r['retransmissions']}")

    # Gráfico do throughput por tamanho da janela
    plt.figure()
    plt.plot([r['N'] for r in results], [r['throughput'] for r in results], marker='o')
    plt.xlabel('Window size (N)')
    plt.ylabel('Throughput (MBps)')
    plt.title('GBN: Throughput x Window Size')
    plt.grid(True)
    plt.savefig('gbn_throughput.png', dpi=120)
    plt.show()


if __name__ == '__main__':
    test_gbn_var_window()
