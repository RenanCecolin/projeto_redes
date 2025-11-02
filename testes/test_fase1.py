"""
tests/test_fase1.py
Script simples para testar rdt2.1 e rdt3.0 localmente com simulação de canal não confiável.
Monte sender e receiver em threads e teste perda/corrupção/delay via UnreliableChannel.

Exemplo de execução:
python -m testes.test_fase1 (na hora de rodar, utilize o Git bash)
"""

import threading
import time
import sys
import os

# Ajusta caminho para importar módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _test_rdt21():
    """
    Testa a implementação do protocolo rdt2.1.
    Configura canal com 20% corrupção e delay até 100ms.
    Envia 10 mensagens, verifica recepção correta e imprime estatísticas.
    """
    from utils.simulator import UnreliableChannel
    from fase1.rdt21 import RDT21Sender, RDT21Receiver

    ch = UnreliableChannel(loss_rate=0.0, corrupt_rate=0.2, delay_range=(0.0, 0.1), verbose=True)
    received = []

    def deliver(b):
        received.append(b)

    rx = RDT21Receiver(local_addr=('localhost', 12000), deliver_callback=deliver, channel=ch, verbose=True)
    s = RDT21Sender(local_addr=('localhost', 0), dest_addr=('localhost', 12000), channel=ch, verbose=True)

    msgs = [f'Mensagem {i}'.encode() for i in range(10)]
    for m in msgs:
        s.send(m)
        time.sleep(0.05)

    time.sleep(1)
    assert [m for m in received] == msgs
    print('rdt2.1 test OK, retransmissions=', s.retransmissions)
    s.close()
    rx.close()


def _test_rdt30():
    """
    Testa a implementação do protocolo rdt3.0.
    Configura canal com 15% perda e corrupção e delay de 50-200ms.
    Envia 20 mensagens, verifica recepção, imprime estatísticas de tempo e retransmissões.
    """
    from utils.simulator import UnreliableChannel
    from fase1.rdt30 import RDT30Sender, RDT21Receiver

    ch = UnreliableChannel(loss_rate=0.15, corrupt_rate=0.15, delay_range=(0.05, 0.2), verbose=True)
    received = []

    def deliver(b):
        received.append(b)

    rx = RDT21Receiver(local_addr=('localhost', 13000), deliver_callback=deliver, channel=ch, verbose=True)
    s = RDT30Sender(local_addr=('localhost', 0), dest_addr=('localhost', 13000), channel=ch, timeout=2.0, verbose=True)

    msgs = [f'Msg {i}'.encode() for i in range(20)]
    t0 = time.time()
    for m in msgs:
        s.send(m)
    t1 = time.time()
    time.sleep(1)
    assert [m for m in received] == msgs
    print('rdt3.0 test OK, retransmissions=', s.retransmissions, 'time=', t1 - t0)
    s.close()
    rx.close()


if __name__ == '__main__':
    print('Running rdt2.1 test...')
    _test_rdt21()
    print('Running rdt3.0 test...')
    _test_rdt30()
