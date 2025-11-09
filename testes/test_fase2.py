"""
Testes comparativos de protocolos confiáveis: RDT3.0 (Stop-and-Wait), 
Go-Back-N e Selective Repeat.

Objetivos:
- Medir throughput, retransmissões e utilização.
- Verificar perdas e ordenação dos pacotes.
- Gerar gráficos comparativos de desempenho.
- Compatível com Windows e diferentes assinaturas de classes sender/receiver.
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
    Tenta instanciar `cls` com vários conjuntos de argumentos.

    Ordem de tentativa:
        1. kwargs passados.
        2. removendo keys problemáticas (heurística).
        3. sem kwargs.

    Args:
        cls: Classe a ser instanciada.
        pos_args: Argumentos posicionais.
        kw_args: Argumentos nomeados.

    Returns:
        Instância de `cls`.

    Raises:
        TypeError: Se nenhuma assinatura funcionar.
    """
    try:
        return cls(*pos_args, **kw_args)
    except TypeError:
        fallback_kw = dict(kw_args)
        keys = list(fallback_kw.keys())
        for k in keys:
            tmp = dict(fallback_kw)
            tmp.pop(k, None)
            try:
                return cls(*pos_args, **tmp)
            except TypeError:
                continue
        return cls(*pos_args)


def start_receiver_loop(receiver_obj):
    """
    Inicia o loop de recepção do receiver_obj em uma thread daemon.
    Tenta chamar receiver.receive(), receiver.start(), receiver.run() ou _recv_loop().

    Args:
        receiver_obj: Instância de receiver.
    
    Returns:
        Thread iniciada ou None se não houver loop.
    """
    for method in ("receive", "start", "run", "_recv_loop", "recv_loop"):
        fn = getattr(receiver_obj, method, None)
        if callable(fn):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            return t
    return None


def instantiate_receiver(receiver_cls, channel, deliver_callback, window_size: int, verbose: bool):
    """
    Instancia receiver com múltiplas assinaturas possíveis.

    Args:
        receiver_cls: Classe do receiver.
        channel: Canal de envio/recepção.
        deliver_callback: Função de callback para entrega de pacotes.
        window_size: Tamanho da janela de recepção.
        verbose: Flag de depuração.

    Returns:
        Tuple[receiver_instance, port_if_available]: Instância e porta do socket.

    Raises:
        Exception: Se nenhuma tentativa for bem-sucedida.
    """
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
            port = getattr(inst, "sock", None)
            if port:
                try:
                    port = inst.sock.getsockname()[1]
                except Exception:
                    port = None
            return inst, port
        except Exception as e:
            last_exc = e
    raise last_exc


def instantiate_sender(sender_cls, dest_addr, channel, window_size: int, timeout: float, verbose: bool):
    """
    Instancia sender com múltiplas assinaturas possíveis.

    Args:
        sender_cls: Classe do sender.
        dest_addr: Endereço do receiver.
        channel: Canal de envio/recepção.
        window_size: Tamanho da janela.
        timeout: Timeout para retransmissão.
        verbose: Flag de depuração.

    Returns:
        Instância de sender.
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
            if dest_addr:
                if hasattr(inst, "dest") and isinstance(inst.dest, tuple):
                    inst.dest = dest_addr
                elif hasattr(inst, "dest_addr"):
                    inst.dest_addr = dest_addr
            return inst
        except Exception as e:
            last_exc = e
    raise last_exc


def run_protocol_test(name, sender_cls, receiver_cls, total_chunks=1024, chunk_size=1024,
                      window_size=1, loss_rate=0.1, delay_range=(0.01, 0.05), verbose=False):
    """
    Executa teste de protocolo confiável (RDT3, GBN, SR) com canal não confiável.

    Args:
        name: "RDT3", "GBN" ou "SR".
        sender_cls: Classe do sender.
        receiver_cls: Classe do receiver.
        total_chunks: Número de pacotes a enviar.
        chunk_size: Tamanho de cada pacote.
        window_size: Tamanho da janela.
        loss_rate: Probabilidade de perda.
        delay_range: Intervalo de atraso simulado (s).
        verbose: Habilita logs detalhados.

    Returns:
        dict: Estatísticas do teste.
    """
    channel = UnreliableChannel(loss_rate=loss_rate, corrupt_rate=0.0, delay_range=delay_range, verbose=verbose)
    received = []

    # Callback de entrega de pacotes
    def deliver(*args):
        if len(args) == 2:
            seq, data = args
        else:
            data = args[0]
            seq = None
        received.append((seq, data))
        if verbose:
            print(f"[DEBUG] Pacote recebido: seq={seq}, tamanho={len(data)}")

    # Instancia receiver e sender
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

    # Criar pacotes de teste
    data_chunks = [bytes([i % 256]) * chunk_size for i in range(total_chunks)]
    packet_logs = []

    start = time.time()
    if name == "SR":
        for i, chunk in enumerate(data_chunks):
            sender.send(chunk)
            packet_logs.append(f"[SR] Pacote enviado: seq={i}, tamanho={len(chunk)}")
            if verbose:
                print(packet_logs[-1])
    else:
        for chunk in data_chunks:
            sender.send(chunk)

    time.sleep(2)
    elapsed = max(time.time() - start, 0.000001)

    # Estatísticas
    ordered = True
    if name == "SR":
        received_dict = {seq: data for seq, data in received if seq is not None}
        for i in range(total_chunks):
            if received_dict.get(i) != data_chunks[i]:
                ordered = False
                if verbose:
                    print(f"[ERRO] Pacote fora de ordem ou corrompido: seq={i}")

    delivered_count = len(received)
    total_data = chunk_size * total_chunks
    throughput = total_data / elapsed / 1e6  # MB/s
    utilization = throughput / (8 / sum(delay_range))
    retransmissions = getattr(sender, "retransmissions", 0)

    # Fechar sockets
    try:
        sender.close()
        receiver.close()
    except Exception:
        pass
    time.sleep(0.2)

    if delivered_count < total_chunks:
        print(f"[WARN] {name} entregou apenas {delivered_count}/{total_chunks} chunks!")

    return {
        'protocol': name,
        'window': window_size,
        'time': elapsed,
        'throughput': throughput,
        'utilization': utilization,
        'retransmissions': retransmissions,
        'received': delivered_count,
        'ordered': ordered,
        'packet_logs': packet_logs
    }


def main():
    """Executa testes comparativos e gera gráfico de desempenho."""
    total_chunks = 1024
    chunk_size = 1024
    delay_range = (0.01, 0.05)
    loss_rate = 0.1
    verbose = False

    results = []

    # Teste RDT3.0
    print("\n=== Testando RDT3.0 (Stop-and-Wait) ===")
    rdt3 = run_protocol_test("RDT3", RDT30Sender, RDT21Receiver,
                             total_chunks=total_chunks, chunk_size=chunk_size,
                             window_size=1, loss_rate=loss_rate,
                             delay_range=delay_range, verbose=True)
    results.append(rdt3)

    # Teste Go-Back-N
    print("\n=== Testando Go-Back-N ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("GBN", GBNSender, GBNReceiver,
                                total_chunks=total_chunks, chunk_size=chunk_size,
                                window_size=N, loss_rate=loss_rate,
                                delay_range=delay_range, verbose=True)
        results.append(res)

    # Teste Selective Repeat
    print("\n=== Testando Selective Repeat ===")
    for N in [1, 5, 10, 20]:
        res = run_protocol_test("SR", SR_Sender, SR_Receiver,
                                total_chunks=total_chunks, chunk_size=chunk_size,
                                window_size=N, loss_rate=loss_rate,
                                delay_range=delay_range, verbose=True)
        results.append(res)

    # Exibir resultados
    print("\n==== RESULTADOS ====")
    for r in results:
        print(f"{r['protocol']} (N={r['window']}): tempo={r['time']:.2f}s, "
              f"throughput={r['throughput']:.4f}MBps, "
              f"utilização={r['utilization']:.4f}, "
              f"retransmissões={r['retransmissions']}, "
              f"recebidos={r['received']}")

    # Gráfico comparativo
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
