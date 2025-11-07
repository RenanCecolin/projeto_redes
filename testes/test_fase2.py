"""
Testes comparativos de protocolos: rdt3.0 (Stop-and-Wait), Go-Back-N e Selective Repeat.

Mede throughput, retransmissões, utilização e verifica perdas/ordenação.
Gera gráficos comparativos de desempenho.
Compatível com Windows e com diferentes assinaturas de classes sender/receiver.
"""

import time
import sys
import os
import socket
import threading
import matplotlib.pyplot as plt
from typing import Any, Optional

# Permitir import dos módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.simulator import UnreliableChannel
from fase1.rdt30 import RDT30Sender, RDT21Receiver
from fase2.gbn import GBNSender, GBNReceiver
from fase2.sr import SR_Sender, SR_Receiver


def try_call_ctor(cls, /, *pos_args, **kw_args):
    """
    Tenta instanciar `cls` com vários conjuntos de argumentos:
    - primeiro com os passados via pos_args/kw_args
    - se falhar, tenta sem alguns kwargs adicionais.
    Retorna instância ou levanta a exceção final.
    """
    try:
        return cls(*pos_args, **kw_args)
    except TypeError:
        # tenta algumas combinações heurísticas removendo keys possivelmente não suportadas
        # ordem de preferências: passar local_addr, channel, deliver_callback, window_size, N
        fallback_kw = dict(kw_args)
        keys = list(fallback_kw.keys())
        # remover keys uma a uma para tentar
        for k in keys:
            tmp = dict(fallback_kw)
            tmp.pop(k, None)
            try:
                return cls(*pos_args, **tmp)
            except TypeError:
                continue
        # por fim tenta sem kwargs
        return cls(*pos_args)


def start_receiver_loop(receiver_obj):
    """
    Inicia o loop de recepção do receiver_obj em uma thread daemon.
    Tenta chamar receiver.receive(), receiver.start(), receiver.run(), receiver._recv_loop().
    """
    for method in ("receive", "start", "run", "_recv_loop", "recv_loop"):
        fn = getattr(receiver_obj, method, None)
        if callable(fn):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            return t
    # se não tiver nenhum loop, apenas ignore (algumas classes fazem recv no ctor)
    return None


def instantiate_receiver(receiver_cls, channel, deliver_callback, window_size: int, verbose: bool):
    """
    Tenta instanciar receiver com várias assinaturas possíveis.
    Retorna (receiver_instance, port_if_available)
    """
    # tentativas com argumentos diferentes (heurísticas)
    tries = [
        {"local_addr": ("localhost", 0), "deliver_callback": deliver_callback, "channel": channel, "window_size": window_size, "verbose": verbose},
        {"local_addr": ("localhost", 0), "deliver_callback": deliver_callback, "channel": channel, "verbose": verbose},
        {"local_addr": ("localhost", 0), "deliver_callback": deliver_callback, "window_size": window_size},
        {"local_addr": ("localhost", 0), "channel": channel, "window_size": window_size},
        {"channel": channel, "window_size": window_size},
        {"channel": channel},
        {}
    ]
    last_exc = None
    for kw in tries:
        try:
            inst = try_call_ctor(receiver_cls, **kw)
            # obter porta se inst tiver sock
            port = None
            sock = getattr(inst, "sock", None)
            if sock:
                try:
                    port = sock.getsockname()[1]
                except Exception:
                    port = None
            return inst, port
        except Exception as e:
            last_exc = e
            continue
    raise last_exc


def instantiate_sender(sender_cls, dest_addr, channel, window_size: int, timeout: float, verbose: bool):
    """
    Tenta instanciar sender com várias assinaturas possíveis.
    Retorna instância.
    """
    tries = [
        {"local_addr": ("localhost", 0), "dest_addr": dest_addr, "channel": channel, "N": window_size, "window_size": window_size, "timeout": timeout, "verbose": verbose},
        {"local_addr": ("localhost", 0), "dest_addr": dest_addr, "channel": channel, "window_size": window_size, "timeout": timeout, "verbose": verbose},
        {"local_addr": ("localhost", 0), "dest_addr": dest_addr, "channel": channel, "timeout": timeout, "verbose": verbose},
        {"local_addr": ("localhost", 0), "dest_addr": dest_addr, "channel": channel},
        {"channel": channel, "window_size": window_size, "timeout": timeout},
        {"channel": channel},
        {}
    ]
    last_exc = None
    for kw in tries:
        try:
            inst = try_call_ctor(sender_cls, **kw)
            # se tiver atributo dest or dest_addr, atualize
            if dest_addr:
                if hasattr(inst, "dest") and isinstance(inst.dest, tuple):
                    inst.dest = dest_addr
                elif hasattr(inst, "dest_addr"):
                    inst.dest_addr = dest_addr
            return inst
        except Exception as e:
            last_exc = e
            continue
    raise last_exc


def run_protocol_test(name, sender_cls, receiver_cls, total_chunks=1024, chunk_size=10,
                      window_size=1, loss_rate=0.1, delay_range=(0.01, 0.05), verbose=False):
    """
    Executa o teste de um protocolo confiável (RDT3, GBN ou SR) com canal não confiável.
    Retorna estatísticas do teste.
    """
    # 1. Criar canal
    channel = UnreliableChannel(loss_rate=loss_rate, corrupt_rate=0.0, delay_range=delay_range, verbose=verbose)

    # 2. Lista para receber os dados
    received = []
    def deliver(data):
        received.append(data)
        if verbose:
            print(f"[SR] Pacote recebido: {data}")  # log de recebimento


    # 3. Criar receiver
    if name == "SR":
        receiver = receiver_cls(channel=channel, window_size=window_size, deliver_callback=deliver)
        receiver_port = receiver.sock.getsockname()[1]
        sender = sender_cls(channel=channel, window_size=window_size, dest_addr=('localhost', receiver_port))
    elif name == "GBN":
        receiver = receiver_cls(local_addr=('localhost', 0), deliver_callback=deliver, channel=channel, verbose=verbose)
        receiver_port = receiver.sock.getsockname()[1]
        sender = sender_cls(local_addr=('localhost', 0), dest_addr=('localhost', receiver_port),
                            channel=channel, N=window_size, timeout=1.0, verbose=verbose)
    else:  # RDT3
        receiver = receiver_cls(local_addr=('localhost', 0), deliver_callback=deliver, channel=channel, verbose=verbose)
        receiver_port = receiver.sock.getsockname()[1]
        sender = sender_cls(local_addr=('localhost', 0), dest_addr=('localhost', receiver_port),
                            channel=channel, timeout=1.0, verbose=verbose)

    # 4. Criar os dados
    data_chunks = [b'x'*chunk_size for _ in range(total_chunks)]

    # 5. Enviar dados e medir tempo
    start = time.time()
    if name == "RDT3":
        # envia cada chunk separadamente para evitar TypeError
        for i, chunk in enumerate(data_chunks):
            sender.send(chunk)
            if verbose:
                print(f"[SR] Pacote enviado ({i+1}/{len(data_chunks)}): {chunk}")   
    else:
        for chunk in data_chunks:
            sender.send(chunk)

    time.sleep(1)  # espera ACKs finais
    elapsed = max(time.time() - start, 0.000001)

    # 6. Estatísticas
    delivered_count = len(received)
    total_data = chunk_size * total_chunks
    throughput = total_data / elapsed / 1e6  # MB/s
    utilization = throughput / (8 / sum(delay_range))  # simplificado
    retransmissions = getattr(sender, "retransmissions", 0)

    # 7. Fechar sockets
    try:
        sender.close()
        receiver.close()
    except Exception:
        pass
    time.sleep(0.2)

    if delivered_count < total_chunks:
        print(f"[WARN] {name} entregou apenas {delivered_count}/{total_chunks} chunks! (porta receiver={receiver_port})")

    return {
        'protocol': name,
        'window': window_size,
        'time': elapsed,
        'throughput': throughput,
        'utilization': utilization,
        'retransmissions': retransmissions,
        'received': delivered_count
    }
def main():
    # Parâmetros do teste
    total_chunks = 10      # número de pacotes por teste
    chunk_size = 25        # tamanho de cada pacote em bytes
    delay_range = (0.01, 0.05)
    loss_rate = 0.1
    verbose = False

    results = []

    # === RDT3.0 (Stop-and-Wait) ===
    print("\n=== Testando RDT3.0 (Stop-and-Wait) ===")
    rdt3 = run_protocol_test("RDT3", RDT30Sender, RDT21Receiver,
                             total_chunks=total_chunks,
                             chunk_size=chunk_size,
                             window_size=1,
                             loss_rate=loss_rate,
                             delay_range=delay_range,
                             verbose=verbose)
    results.append(rdt3)

    # === Go-Back-N ===
    print("\n=== Testando Go-Back-N ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("GBN", GBNSender, GBNReceiver,
                                total_chunks=total_chunks,
                                chunk_size=chunk_size,
                                window_size=N,
                                loss_rate=loss_rate,
                                delay_range=delay_range,
                                verbose=verbose)
        results.append(res)

    # === Selective Repeat ===
    print("\n=== Testando Selective Repeat ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("SR", SR_Sender, SR_Receiver,
                                total_chunks=total_chunks,
                                chunk_size=chunk_size,
                                window_size=N,
                                loss_rate=loss_rate,
                                delay_range=delay_range,
                                verbose=True)
        results.append(res)

    # === Exibir resultados ===
    print("\n==== RESULTADOS ====")
    for r in results:
        print(f"{r['protocol']} (N={r['window']}): "
              f"tempo={r['time']:.2f}s, throughput={r['throughput']:.4f}MBps, "
              f"utilização={r['utilization']:.4f}, retransmissões={r['retransmissions']}, "
              f"recebidos={r['received']}")

    # === Gráfico comparativo ===
    plt.figure(figsize=(8,5))

    gbn = [r for r in results if r['protocol'] == 'GBN']
    sr = [r for r in results if r['protocol'] == 'SR']

    if gbn:
        plt.plot([r['window'] for r in gbn], [r['throughput'] for r in gbn],
                 marker='o', label='GBN')
    if sr:
        plt.plot([r['window'] for r in sr], [r['throughput'] for r in sr],
                 marker='s', label='SR')

    plt.axhline(y=rdt3['throughput'], color='gray', linestyle='--', label='RDT3.0')

    plt.xlabel("Tamanho da Janela (N)")
    plt.ylabel("Throughput (MBps)")
    plt.title("Desempenho dos Protocolos Confiáveis")
    plt.grid(True)
    plt.legend()
    plt.savefig("comparativo_protocolos.png", dpi=120)
    plt.show()


if __name__ == "__main__":
    main()
