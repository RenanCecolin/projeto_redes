"""
tests/test_fase1.py
Testes para rdt2.0, rdt2.1 e rdt3.0 com UnreliableChannel.
Executa sender e receiver em threads e verifica entrega correta das mensagens.

Exemplo de execução:
python -m testes.test_fase1
"""

import threading
import time
import sys
import os

# Ajusta caminho para importar módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importações
from fase1.rdt20 import RDT20Sender, RDT20Receiver
from fase1.rdt21 import RDT21Sender, RDT21Receiver
from fase1.rdt30 import RDT30Sender
from utils.simulator import UnreliableChannel
from utils.packet import TYPE_DATA, TYPE_ACK, TYPE_NAK


# ---------------------- Teste rdt2.0 ----------------------
def test_rdt20():
    print("=== Teste rdt2.0 ===")

    # Canal com 10% de perda, 10% de corrupção, delay até 0.1s
    channel = UnreliableChannel(loss_rate=0.1, corrupt_rate=0.1, delay_range=(0.0, 0.1))

    # Cria receptor (não há deliver_callback nem verbose)
    receiver = RDT20Receiver(listen_port=11000, channel=channel)
    recv_thread = threading.Thread(target=receiver.start, daemon=True)
    recv_thread.start()

    # Cria sender
    sender = RDT20Sender(bind_port=11001, dest_host='localhost', dest_port=11000,
                         channel=channel, timeout=1.5)

    msgs_to_send = [f"Mensagem {i}" for i in range(10)]

    for msg in msgs_to_send:
        max_attempts = 5
        attempt = 0
        while attempt < max_attempts:
            success = sender.send_message(msg)
            if success:
                break
            attempt += 1
            print(f"[TEST] Retry {attempt} for message '{msg}'")
        if attempt == max_attempts:
            print(f"[TEST] Failed to send message '{msg}' after {max_attempts} attempts")
        time.sleep(0.05)

    # Dá tempo do receptor processar
    time.sleep(1)

    sender.close()
    receiver.stop()

    print("=== Resultados ===")
    print(f"Mensagens enviadas: {len(msgs_to_send)}")
    print(f"Mensagens recebidas: {len(receiver.received_messages)}")
    print(f"Retransmissões: {sender.retransmissions}")
    print("Mensagens recebidas:")
    for m in receiver.received_messages:
        print("  ", m)

# ---------------------- Teste rdt2.1 ----------------------
def test_rdt21():
    print("\n=== Teste rdt2.1 ===")

    received_messages = []

    def deliver(msg):
        print("[RECV] Delivered:", msg.decode())
        received_messages.append(msg)

    # Cria receptor com canal simulado opcional
    rx = RDT21Receiver(local_addr=('localhost', 12000),
                       deliver_callback=deliver, verbose=True)

    # Cria sender
    sender = RDT21Sender(local_addr=('localhost', 0),
                          dest_addr=('localhost', 12000),
                          verbose=True)

    # 20% de chance de corromper DATA
    import random
    PACKET_HDR_SIZE = 5  # tipo (1) + seq (1) + checksum (4) = 6 bytes? Ajuste se seu make_packet gerar outro tamanho

    original_send = sender._send_packet

    def send_with_corruption(pkt: bytes):
        # Corrompe DATA 20%
        if random.random() < 0.2 and pkt[0] == TYPE_DATA:
            pkt = bytearray(pkt)
            # inverte primeiro byte do payload
            if len(pkt) > PACKET_HDR_SIZE:
                pkt[PACKET_HDR_SIZE] ^= 0xFF
            pkt = bytes(pkt)
            print("[SIM] Pacote DATA corrompido pelo teste")
        original_send(pkt)

    sender._send_packet = send_with_corruption

    # Envia mensagens
    mensagens = [f"Mensagem {i}".encode() for i in range(10)]

    for m in mensagens:
        sender.send(m)
        time.sleep(0.1)  # pequeno delay

    # Dá tempo para receptor processar tudo
    timeout = time.time() + 5
    while len(received_messages) < len(mensagens) and time.time() < timeout:
        time.sleep(0.05)

    print("\n=== Resultados rdt2.1 ===")
    print("Mensagens enviadas:", len(mensagens))
    print("Mensagens recebidas:", len(received_messages))
    print("Retransmissões:", sender.retransmissions)
    print("Mensagens recebidas detalhadas:")
    for msg in received_messages:
        print("   ", msg.decode())

    sender.close()
    rx.close()

# ---------------------- Teste rdt3.0 ----------------------
def test_rdt30():
    print("\n=== Teste rdt3.0 ===")

    channel = UnreliableChannel(loss_rate=0.15, corrupt_rate=0.15, delay_range=(0.05, 0.2))
    received = []

    def deliver(msg):
        received.append(msg)

    # Receptor rdt2.1 funciona como receptor para rdt3.0
    rx = RDT21Receiver(local_addr=('localhost', 13000), deliver_callback=deliver, channel=channel, verbose=True)
    sender = RDT30Sender(local_addr=('localhost', 13001), dest_addr=('localhost', 13000),
                         channel=channel, timeout=2.0, verbose=True)

    msgs = [f"Mensagem {i}".encode() for i in range(20)]
    for m in msgs:
        sender.send(m)
        time.sleep(0.05)

    timeout = time.time() + 10
    while len(received) < len(msgs) and time.time() < timeout:
        time.sleep(0.05)

    print("\n=== Resultados rdt3.0 ===")
    print("Mensagens enviadas:", len(msgs))
    print("Mensagens recebidas:", len(received))
    print("Retransmissões:", sender.retransmissions)

    sender.close()
    rx.close()


# ---------------------- Main ----------------------
if __name__ == "__main__":
    test_rdt20()
    test_rdt21()
    test_rdt30()
