"""
Selective Repeat (SR) sender/receiver usando UDP.

Implementa controle de janela deslizante, retransmissão por timeout
e ACK cumulativo, compatível com canais não confiáveis.
"""

import socket
import threading
import time
from utils.packet import make_packet, parse_packet, is_corrupt, TYPE_DATA, TYPE_ACK
from utils.simulator import sendto_via_channel


def seq_in_range(seq, start, end, max_seq=256):
    """
    Verifica se um número de sequência está dentro da janela circular.

    Args:
        seq (int): Número de sequência a verificar.
        start (int): Início da janela.
        end (int): Fim da janela (não inclusivo).
        max_seq (int): Número máximo de sequência antes do wrap-around.

    Returns:
        bool: True se seq estiver dentro da janela.
    """
    if start <= end:
        return start <= seq < end
    else:
        return seq >= start or seq < end


# ===================== Sender =====================
class SR_Sender:
    """
    Transmissor Selective Repeat (SR).

    Envia pacotes em sequência, mantém controle de janela, timers
    para retransmissão e processa ACKs recebidos.
    """

    def __init__(self, channel, window_size=4, timeout=1.0,
                 local_addr=('localhost', 0), dest_addr=None):
        """
        Inicializa o SR_Sender.

        Args:
            channel: Canal de envio (simulador de perda opcional).
            window_size (int): Tamanho da janela deslizante.
            timeout (float): Timeout em segundos para retransmissão.
            local_addr (tuple): Endereço local (host, port).
            dest_addr (tuple): Endereço do receptor.
        """
        self.channel = channel
        self.window_size = window_size
        self.timeout = timeout
        self.dest_addr = dest_addr

        # Socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.sock.settimeout(0.2)

        # Controle de janela
        self.base = 0
        self.next_seq_num = 0
        self.buffer = {}     # seq -> pacote enviado
        self.timers = {}     # seq -> tempo de envio
        self.acks = {}       # seq -> bool (ack recebido)
        self.retransmissions = 0

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        # Thread para receber ACKs
        self.recv_thread = threading.Thread(target=self._receive_acks, daemon=True)
        self.recv_thread.start()

    def send(self, data_chunks):
        """
        Envia uma sequência de pacotes.

        Args:
            data_chunks (list): Lista de bytes, str ou int a enviar.
        """
        for data in data_chunks:
            if isinstance(data, int):
                data = data.to_bytes(4, 'big')
            elif isinstance(data, str):
                data = data.encode()

            sent = False
            while not sent:
                with self.lock:
                    if len(self.buffer) < self.window_size:
                        seq = self.next_seq_num % 256
                        pkt = make_packet(TYPE_DATA, seq, data)
                        sendto_via_channel(self.sock, pkt, self.dest_addr, self.channel)
                        self.buffer[seq] = pkt
                        self.timers[seq] = time.time()
                        self.acks[seq] = False
                        self.next_seq_num += 1
                        sent = True
                self._check_timeouts()
                time.sleep(0.01)

        # Espera todos os ACKs antes de retornar
        while True:
            with self.lock:
                if not self.buffer:
                    break
            self._check_timeouts()
            time.sleep(0.05)

    def _check_timeouts(self):
        """Verifica se algum pacote excedeu o timeout e retransmite."""
        with self.lock:
            for seq in list(self.buffer.keys()):
                if not self.acks[seq] and time.time() - self.timers[seq] > self.timeout:
                    sendto_via_channel(self.sock, self.buffer[seq], self.dest_addr, self.channel)
                    self.timers[seq] = time.time()
                    self.retransmissions += 1

    def _receive_acks(self):
        """Loop para receber ACKs e atualizar o estado da janela."""
        while not self.stop_event.is_set():
            try:
                ack_pkt, _ = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue

            pkt = parse_packet(ack_pkt)
            if pkt and pkt["type"] == TYPE_ACK:
                ack_seq = pkt["seq"]
                with self.lock:
                    if ack_seq in self.buffer:
                        self.acks[ack_seq] = True
                        del self.buffer[ack_seq]
                        del self.timers[ack_seq]

    def close(self):
        """Fecha o socket e encerra a thread de recebimento."""
        self.stop_event.set()
        time.sleep(0.2)
        try:
            self.sock.close()
        except Exception:
            pass


# ===================== Receiver =====================
class SR_Receiver:
    """
    Receptor Selective Repeat (SR).

    Recebe pacotes DATA, envia ACKs imediatos, armazena pacotes fora de ordem
    e entrega os dados na ordem correta usando callback opcional.
    """

    def __init__(self, channel, window_size=4,
                 local_addr=('localhost', 0), sender_addr=None,
                 deliver_callback=None):
        """
        Inicializa o SR_Receiver.

        Args:
            channel: Canal de envio (simulador de perda opcional).
            window_size (int): Tamanho da janela de recepção.
            local_addr (tuple): Endereço local (host, port).
            sender_addr (tuple): Endereço do remetente.
            deliver_callback (callable): Função chamada ao entregar payload.
        """
        self.channel = channel
        self.window_size = window_size
        self.deliver_callback = deliver_callback
        self.sender_addr = sender_addr

        # Socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.sock.settimeout(0.2)

        self.expected_seq = 0
        self.buffer = {}  # seq -> payload
        self.delivered_data = []

        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.receive, daemon=True)
        self.thread.start()

    def receive(self):
        """Loop principal de recepção, envio de ACKs e entrega de pacotes."""
        while not self.stop_event.is_set():
            try:
                pkt_bytes, addr = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue

            pkt = parse_packet(pkt_bytes)
            if not pkt or is_corrupt(pkt):
                continue

            if pkt['type'] == TYPE_DATA:
                seq = pkt['seq']
                data = pkt['payload']

                # Sempre envia ACK
                ack_pkt = make_packet(TYPE_ACK, seq, b'')
                sendto_via_channel(self.sock, ack_pkt, addr, self.channel)

                # Aceita se dentro da janela
                if seq_in_range(seq, self.expected_seq % 256,
                                (self.expected_seq + self.window_size) % 256):
                    self.buffer[seq] = data

                    # Entrega pacotes em ordem
                    while self.expected_seq % 256 in self.buffer:
                        seq_mod = self.expected_seq % 256
                        msg = self.buffer[seq_mod]
                        self.delivered_data.append(msg)
                        if self.deliver_callback:
                            self.deliver_callback(seq_mod, msg)
                        del self.buffer[seq_mod]
                        self.expected_seq += 1

    def get_received_chunks(self):
        """
        Retorna os dados entregues em ordem.

        Returns:
            list: Lista de payloads recebidos.
        """
        return self.delivered_data.copy()

    def close(self):
        """Fecha o socket e encerra a thread de recepção."""
        self.stop_event.set()
        time.sleep(0.1)
        try:
            self.sock.close()
        except Exception:
            pass
