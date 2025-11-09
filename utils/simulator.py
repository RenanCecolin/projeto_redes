"""
utils/simulator.py

Simulador de canal não confiável (UnreliableChannel) para protocolos de rede confiáveis.
Permite simular:
    - perda de pacotes
    - corrupção de pacotes
    - atraso de entrega
    - envio seguro via socket UDP

Inclui função utilitária sendto_via_channel para integrar com sockets.
"""

import random
import threading
import time


class UnreliableChannel:
    """
    Classe que simula um canal de comunicação não confiável.

    Pode causar perda, corrupção e atraso de pacotes, além de fornecer logs opcionais.
    """

    def __init__(
        self,
        loss_rate: float = 0.0,
        corrupt_rate: float = 0.0,
        delay_range: tuple = (0.0, 0.0),
        verbose: bool = False
    ):
        """
        Inicializa o canal com parâmetros de perda, corrupção e atraso.

        Args:
            loss_rate (float): Probabilidade de perda de pacotes (0.0 a 1.0).
            corrupt_rate (float): Probabilidade de corrupção de pacotes (0.0 a 1.0).
            delay_range (tuple): Intervalo (min, max) de atraso em segundos.
            verbose (bool): Ativa logs detalhados de eventos do canal.
        """
        self.loss_rate = loss_rate
        self.corrupt_rate = corrupt_rate
        self.delay_range = delay_range
        self.verbose = verbose

    def send(self, packet: bytes, dest_socket, dest_addr):
        """
        Envia um pacote simulando possíveis falhas no canal.

        Args:
            packet (bytes): Pacote a enviar.
            dest_socket (socket.socket): Socket de destino.
            dest_addr (tuple): Endereço de destino (host, porta).
        """
        # Simular perda de pacote
        if random.random() < self.loss_rate:
            if self.verbose:
                print('[SIM] Pacote perdido')
            return

        # Simular corrupção do pacote
        send_packet = packet
        if random.random() < self.corrupt_rate:
            send_packet = self._corrupt_packet(packet)
            if self.verbose:
                print('[SIM] Pacote corrompido')

        # Simular atraso
        delay = random.uniform(*self.delay_range)
        if delay <= 0:
            self.safe_sendto(dest_socket, send_packet, dest_addr)
        else:
            if self.verbose:
                print(f'[SIM] Envio atrasado por {delay:.3f}s')
            threading.Timer(
                delay, lambda: self.safe_sendto(dest_socket, send_packet, dest_addr)
            ).start()

    def safe_sendto(self, sock, packet, addr):
        """
        Envia pacote pelo socket UDP ignorando erros (socket fechado).

        Args:
            sock (socket.socket): Socket UDP.
            packet (bytes): Pacote a enviar.
            addr (tuple): Endereço de destino.
        """
        try:
            sock.sendto(packet, addr)
        except OSError:
            pass

    def _corrupt_packet(self, packet: bytes) -> bytes:
        """
        Inverte bits aleatórios do pacote para simular corrupção.

        Args:
            packet (bytes): Pacote original.

        Returns:
            bytes: Pacote corrompido.
        """
        if len(packet) == 0:
            return packet

        lst = bytearray(packet)
        num = random.randint(1, max(1, min(5, len(lst))))  # altera até 5 bytes
        for _ in range(num):
            idx = random.randrange(0, len(lst))
            lst[idx] ^= 0xFF  # inverte todos os bits do byte
        return bytes(lst)


def sendto_via_channel(sock, data: bytes, addr, channel: UnreliableChannel):
    """
    Envia dados usando o canal não confiável.

    Compatível com a interface socket.sendto, mas com simulação de perda,
    corrupção e atraso.

    Args:
        sock (socket.socket): Socket UDP.
        data (bytes): Dados a enviar.
        addr (tuple): Endereço de destino.
        channel (UnreliableChannel): Canal de simulação.
    """
    channel.send(data, sock, addr)
