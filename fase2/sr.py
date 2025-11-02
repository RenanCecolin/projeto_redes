"""
Implementação simples do protocolo Selective Repeat (SR).
Inclui classes SR_Sender e SR_Receiver, com gerenciamento de janela e timers independentes.
"""

import threading
import time
from utils.packet import make_pkt, extract, is_corrupt

class SR_Sender:
    """
    Remetente do protocolo Selective Repeat.
    Gerencia janela deslizante, timers individuais e buffer de pacotes.
    """

    def __init__(self, channel, window_size=4, timeout=2.0):
        """
        Inicializa o SR_Sender.

        Args:
            channel (obj): Canal de comunicação que fornece udt_send(pkt).
            window_size (int): Tamanho da janela de envio.
            timeout (float): Timeout para retransmissão de pacotes.
        """
        self.channel = channel
        self.window_size = window_size
        self.timeout = timeout
        self.base = 0
        self.nextseqnum = 0
        self.buffer = {}   # buffer de pacotes enviados
        self.acks = set()  # ACKs já recebidos
        self.lock = threading.Lock()
        self.timers = {}

    def start_timer(self, seqnum):
        """
        Inicia ou reinicia o timer do pacote de número seqnum.

        Args:
            seqnum (int): Número de sequência do pacote.
        """
        def timer_thread():
            time.sleep(self.timeout)
            with self.lock:
                if seqnum not in self.acks:
                    print(f"[SR_Sender] Timeout seq={seqnum}, retransmitindo.")
                    self.channel.udt_send(self.buffer[seqnum])
                    self.start_timer(seqnum)

        t = threading.Thread(target=timer_thread)
        t.daemon = True
        t.start()
        self.timers[seqnum] = t

    def send(self, message):
        """
        Envia mensagem, respeitando limite de janela.
        Inicia timer individual para cada pacote.

        Args:
            message (str): Mensagem a ser enviada.
        """
        while self.nextseqnum >= self.base + self.window_size:
            # Janela cheia, aguarda espaço para enviar novos pacotes
            time.sleep(0.05)
        pkt = make_pkt(self.nextseqnum, message)
        with self.lock:
            self.buffer[self.nextseqnum] = pkt
            self.channel.udt_send(pkt)
            print(f"[SR_Sender] Enviando pacote {self.nextseqnum}.")
            self.start_timer(self.nextseqnum)
            self.nextseqnum += 1

    def receive_ack(self, pkt):
        """
        Processa ACK recebido; atualiza base e cancela timers conforme necessário.

        Args:
            pkt (bytes): Pacote ACK recebido.
        """
        seqnum, _ = extract(pkt)
        if not is_corrupt(pkt):
            print(f"[SR_Sender] ACK recebido {seqnum}.")
            with self.lock:
                self.acks.add(seqnum)
                while self.base in self.acks:
                    self.base += 1

class SR_Receiver:
    """
    Receptor do protocolo Selective Repeat.
    Aceita pacotes dentro da janela, bufferiza, envia ACKs e entrega em ordem.
    """

    def __init__(self, channel, window_size=4):
        """
        Inicializa o SR_Receiver.

        Args:
            channel (obj): Canal de comunicação que fornece udt_send(pkt).
            window_size (int): Tamanho da janela de recebimento.
        """
        self.channel = channel
        self.window_size = window_size
        self.expected_seqnum = 0
        self.received = {}  # buffer dos pacotes dentro da janela

    def receive(self, pkt):
        """
        Processa pacotes DATA recebidos, envia ACK e entrega em ordem.

        Args:
            pkt (bytes): Pacote recebido.
        """
        if is_corrupt(pkt):
            print("[SR_Receiver] Pacote corrompido, descartado.")
            return
        seqnum, msg = extract(pkt)
        if self.expected_seqnum <= seqnum < self.expected_seqnum + self.window_size:
            # Pacote dentro da janela e não corrompido
            self.received[seqnum] = msg
            print(f"[SR_Receiver] Pacote {seqnum} recebido.")
            ack = make_pkt(seqnum, 'ACK')
            self.channel.udt_send(ack)
            while self.expected_seqnum in self.received:
                print(f"[SR_Receiver] Entregando {self.received[self.expected_seqnum]}")
                del self.received[self.expected_seqnum]
                self.expected_seqnum += 1
