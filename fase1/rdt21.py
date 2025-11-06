"""
fase1/rdt21.py
Implementação do rdt2.1 (alternating-bit protocol: seq 0/1) usando UDP sockets.
Design: Sender e Receiver classes que podem ser instanciadas em máquinas locais para testes.
O remetente e receptor podem opcionalmente usar um UnreliableChannel para enviar pacotes (simulação).

Uso de exemplo (executar em terminais separados):
python -c "from fase1.rdt21 import RDT21Receiver; import time; r=RDT21Receiver(local_addr=('localhost',10000), verbose=True); print('Receiver rodando na porta 10000'); time.sleep(600)"
python -c "from fase1.rdt21 import RDT21Sender; s=RDT21Sender(local_addr=('localhost',0), dest_addr=('localhost',10000), verbose=True); s.send(b'Teste rdt2.1'); s.close()"

Este arquivo foi desenhado para ser simples de testar localmente via threads.
"""

"""
fase1/rdt21.py
Implementação do rdt2.1 (alternating-bit protocol: seq 0/1) usando UDP sockets.
"""

import socket
import threading
from utils.packet import *  # make_packet, parse_packet, TYPE_DATA, TYPE_ACK, TYPE_NAK


class RDT21Sender:
    """Implementa o remetente do protocolo rdt2.1"""

    def __init__(self, local_addr=('localhost', 0), dest_addr=('localhost', 10000),
                 channel=None, timeout=2.0, verbose=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.dest = dest_addr
        self.channel = channel
        self.timeout = timeout
        self.seq = 0
        self.lock = threading.Lock()
        self.waiting_for_ack = threading.Event()
        self.last_packet = None
        self.retransmissions = 0
        self.verbose = verbose
        self.running = True

        # 🔹 Novo: contador de bytes enviados
        self.bytes_sent = 0

        # Inicia thread para escuta de ACKs
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """Envia dados usando o protocolo alternating-bit, esperando e retransmitindo se necessário."""
        with self.lock:
            pkt = make_packet(TYPE_DATA, self.seq, data)
            self.last_packet = pkt
            self._send_packet(pkt)
            self.waiting_for_ack.clear()

        while True:
            got_ack = self.waiting_for_ack.wait(timeout=self.timeout)
            if got_ack:
                return
            else:
                self.retransmissions += 1
                if self.verbose:
                    print('[SENDER] Timeout, retransmit seq', self.seq)
                with self.lock:
                    self._send_packet(self.last_packet)

    def _send_packet(self, pkt: bytes):
        """Envia o pacote pela rede ou canal simulado."""
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)

        # 🔹 Soma bytes enviados
        self.bytes_sent += len(pkt)

        if self.verbose:
            print('[SENDER] Sent packet seq=', self.seq, 'len=', len(pkt))

    def _recv_loop(self):
        """Loop para receber ACKs e gerenciar estado do protocolo."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            if (info['type'] == TYPE_ACK and not info['corrupt'] and info['seq'] == self.seq):
                if self.verbose:
                    print('[SENDER] Received ACK for seq', info['seq'])
                with self.lock:
                    self.seq = 1 - self.seq
                    self.waiting_for_ack.set()
            else:
                if self.verbose:
                    print('[SENDER] Ignored packet (type, corrupt, seq) =',
                          info['type'], info['corrupt'], info['seq'])

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class RDT21Receiver:
    """Implementa o receptor do protocolo rdt2.1"""

    def __init__(self, local_addr=('localhost', 10000), deliver_callback=None,
                 channel=None, verbose=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose

        # 🔹 Novo: contador de bytes recebidos
        self.bytes_received = 0

        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq: int, addr):
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print('[RECV] Sent ACK', seq)

    def _recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue

            # 🔹 Soma bytes recebidos
            self.bytes_received += len(data)

            if info['type'] == TYPE_DATA:
                if not info['corrupt'] and info['seq'] == self.expected:
                    if self.verbose:
                        print(f'[RECV] Received expected seq {info["seq"]} len= {len(info["payload"])}')
                    self.deliver_callback(info['payload'])
                    self._send_ack(self.expected, addr)
                    self.expected = 1 - self.expected
                elif info['corrupt']:
                    if self.verbose:
                        print('[RECV] Packet corrupt -> send NAK')
                    nak = make_packet(TYPE_NAK, 0, b'')
                    if self.channel:
                        self.channel.send(nak, self.sock, addr)
                    else:
                        self.sock.sendto(nak, addr)
                else:
                    if self.verbose:
                        print(f'[RECV] Duplicate packet seq {info["seq"]} -> re-ACK last')
                    self._send_ack(1 - self.expected, addr)

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class RDT21Receiver:
    """
    Implementa o receptor do protocolo rdt2.1 (alternating-bit protocol)
    """

    def __init__(self, local_addr=('localhost', 10000), deliver_callback=None,
                 channel=None, verbose=True):
        """
        Inicializa o receptor bindando socket e configurando parâmetros.

        Args:
            local_addr (tuple, opcional): Endereço local (host, porta) para bind. Default: ('localhost', 10000).
            deliver_callback (callable, opcional): Função para entregar dados recebidos.
            channel (UnreliableChannel, opcional): Canal simulado.
            verbose (bool, opcional): Se True, imprime logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq: int, addr):
        """
        Envia ACK para certo seq ao endereço.

        Args:
            seq (int): Número de sequência do ACK.
            addr (tuple): Endereço (host, porta) para envio.
        """
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print('[RECV] Sent ACK', seq)

    def _recv_loop(self):
        """
        Loop para recepção e processamento dos pacotes.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            if info['type'] == TYPE_DATA:
                if not info['corrupt'] and info['seq'] == self.expected:
                    # Pacote esperado e íntegro, entrega e ACK
                    if self.verbose:
                        print(f'[RECV] Received expected seq {info["seq"]} len= {len(info["payload"])}')
                    self.deliver_callback(info['payload'])
                    self._send_ack(self.expected, addr)
                    self.expected = 1 - self.expected
                elif info['corrupt']:
                    # Pacote corrompido - envia NAK
                    if self.verbose:
                        print('[RECV] Packet corrupt -> send NAK')
                    nak = make_packet(TYPE_NAK, 0, b'')
                    if self.channel:
                        self.channel.send(nak, self.sock, addr)
                    else:
                        self.sock.sendto(nak, addr)
                else:
                    # Pacote duplicado (seq != expected), reenvia ACK último
                    if self.verbose:
                        print(f'[RECV] Duplicate packet seq {info["seq"]} -> re-ACK last')
                    self._send_ack(1 - self.expected, addr)

    def close(self):
        """
        Encerra o receptor fechando socket e thread.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
