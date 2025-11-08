"""
Testes automáticos para RDT 2.0, 2.1 e 3.0.

Mede:
 - Retransmissões
 - Taxa de retransmissão
 - Throughput efetivo
 - Overhead de protocolo
 - Duplicação de mensagens (fase 2.1)

Execução:
    python -m testes.test_fase1
"""

import threading
import time
import random
import os
import sys
from collections import Counter

# Adiciona caminho raiz do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fase1.rdt20 import RDT20Sender, RDT20Receiver
from fase1.rdt21 import RDT21Sender, RDT21Receiver
from fase1.rdt30 import RDT30Sender
from utils.simulator import UnreliableChannel


# ==============================================================
# Teste RDT 2.0 - Canal com erros de bits
# ==============================================================

def test_rdt20():
    """Testa RDT 2.0 com canal que corrompe bits aleatoriamente."""
    print("\n=== [FASE 1A] Testando RDT 2.0 (canal com erros de bits) ===")

    # 30% corrupção de bits
    channel = UnreliableChannel(loss_rate=0.0, corrupt_rate=0.3, delay_range=(0.0, 0.05))

    receiver = RDT20Receiver(listen_port=10000, channel=channel)
    sender = RDT20Sender(
        bind_port=10001,
        dest_host="localhost",
        dest_port=10000,
        channel=channel,
        timeout=1.5
    )

    recv_thread = threading.Thread(target=receiver.start, daemon=True)
    recv_thread.start()

    mensagens = [f"Mensagem_{i}" for i in range(10)]
    inicio = time.time()

    for msg in mensagens:
        sender.send_message(msg)
        time.sleep(0.05)

    time.sleep(1.0)

    duracao = time.time() - inicio
    throughput = len(mensagens) / duracao
    taxa_retx = sender.retransmissions / len(mensagens) if mensagens else 0

    sender.close()
    receiver.stop()

    print("\n📊 Resultados RDT2.0:")
    print(f"Mensagens enviadas: {len(mensagens)}")
    print(f"Mensagens recebidas: {len(receiver.received_messages)}")
    print(f"Retransmissões: {sender.retransmissions}")
    print(f"Taxa de retransmissão: {taxa_retx:.2f}")
    print(f"Throughput: {throughput:.2f} msg/s")
    print("Mensagens recebidas:", receiver.received_messages)
    print("✅ Teste RDT2.0 concluído.\n")


# ==============================================================
# Teste RDT 2.1 - Corrupção de DATA/ACK, duplicação e overhead
# ==============================================================

def test_rdt21():
    """Testa RDT 2.1 com números de sequência e simulação de erros."""
    print("\n=== [FASE 1B] Testando RDT 2.1 (com números de sequência) ===")

    received = []

    def deliver(msg: bytes):
        received.append(msg.decode())

    rx = RDT21Receiver(local_addr=("localhost", 11000), deliver_callback=deliver)
    sender = RDT21Sender(local_addr=("localhost", 0), dest_addr=("localhost", 11000), verbose=False)

    # 20% de corrupção em DATA e ACK
    orig_send = sender._send_packet

    def corrupt_send(pkt: bytes):
        pkt_list = bytearray(pkt)
        if random.random() < 0.2 and pkt_list[0] == 0:  # DATA
            pkt_list[-1] ^= 0xFF
            print("[SIM] DATA corrompido")
        elif random.random() < 0.2 and pkt_list[0] == 1:  # ACK
            pkt_list[-1] ^= 0xFF
            print("[SIM] ACK corrompido")
        orig_send(bytes(pkt_list))

    sender._send_packet = corrupt_send

    mensagens = [f"Msg_{i}".encode() for i in range(10)]
    start = time.time()

    for msg in mensagens:
        sender.send(msg)
        time.sleep(0.1)

    timeout = time.time() + 5
    while len(received) < len(mensagens) and time.time() < timeout:
        time.sleep(0.05)

    elapsed = time.time() - start
    throughput = len(received) / elapsed if elapsed > 0 else 0

    # Verificação de duplicação
    duplicados = [msg for msg, count in Counter(received).items() if count > 1]
    duplicacao = len(duplicados)

    # Overhead (simplificado): total de bytes enviados / bytes úteis
    dados_uteis = sum(len(m) for m in mensagens)
    bytes_totais = sender.bytes_sent
    overhead = (bytes_totais / dados_uteis - 1) * 100 if dados_uteis else 0

    print("\n📊 Resultados RDT2.1:")
    print(f"Mensagens enviadas: {len(mensagens)}")
    print(f"Mensagens recebidas: {len(received)}")
    print(f"Retransmissões: {sender.retransmissions}")
    print(f"Mensagens duplicadas: {duplicacao}")
    print(f"Overhead: {overhead:.2f}%")
    print(f"Throughput: {throughput:.2f} msg/s")
    print("Mensagens recebidas:", received)

    sender.close()
    rx.close()
    print("✅ Teste RDT2.1 concluído.\n")


# ==============================================================
# Teste RDT 3.0 - Perda, atraso e temporizador
# ==============================================================

def test_rdt30():
    """Testa RDT 3.0 com temporizador, perda de pacotes e atraso variável."""
    print("\n=== [FASE 1C] Testando RDT 3.0 (temporizador e perda) ===")

    channel = UnreliableChannel(loss_rate=0.15, corrupt_rate=0.15, delay_range=(0.05, 0.5))
    received = []

    def deliver(msg: bytes):
        received.append(msg.decode())

    rx = RDT21Receiver(local_addr=("localhost", 12000), deliver_callback=deliver, channel=channel)
    sender = RDT30Sender(
        local_addr=("localhost", 12001),
        dest_addr=("localhost", 12000),
        channel=channel,
        timeout=2.0,
        verbose=False
    )

    mensagens = [f"Pacote_{i}".encode() for i in range(20)]
    start = time.time()

    for msg in mensagens:
        sender.send(msg)
        time.sleep(0.05)

    timeout = time.time() + 10
    while len(received) < len(mensagens) and time.time() < timeout:
        time.sleep(0.1)

    elapsed = time.time() - start
    bytes_uteis = sum(len(m) for m in mensagens)
    throughput = bytes_uteis / elapsed if elapsed > 0 else 0
    taxa_retx = sender.retransmissions / len(mensagens) if mensagens else 0

    print("\n📊 Resultados RDT3.0:")
    print(f"Mensagens enviadas: {len(mensagens)}")
    print(f"Mensagens recebidas: {len(received)}")
    print(f"Retransmissões: {sender.retransmissions}")
    print(f"Taxa de retransmissão: {taxa_retx:.2f}")
    print(f"Throughput efetivo: {throughput:.2f} bytes/s")
    print("Mensagens recebidas:", received)

    sender.close()
    rx.close()
    print("✅ Teste RDT3.0 concluído.\n")


# ==============================================================
# Execução principal
# ==============================================================

if __name__ == "__main__":
    print("🚀 Iniciando testes automáticos da Fase 1 de RDT...\n")
    test_rdt20()
    test_rdt21()
    test_rdt30()
    print("🏁 Todos os testes concluídos com sucesso!")
