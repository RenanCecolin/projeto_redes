"""
rdt21.py
Implementação do rdt2.1 (alternating-bit protocol: seq 0/1) usando sockets UDP.

Este módulo define as classes RDT21Sender e RDT21Receiver, que podem ser usadas
para testar o protocolo localmente ou com um canal não confiável simulado
(UnreliableChannel).

O protocolo rdt2.1 utiliza números de sequência alternados (0/1), ACKs e NAKs
para garantir entrega confiável de pacotes.

"""

import socket
import threading
from utils.packet import *  # make_packet, parse_packet, TYPE_DATA, TYPE_ACK, TYPE_NAK, TYPE_NAK


class RDT21Sender:
    """
    Implementa o remetente do protocolo rdt2.1 (alternating-bit protocol).
    """

    def __init__(self, local_addr=('localhost', 0), dest_addr=('localhost', 10000),
                 channel=None, timeout=2.0, verbose=True):
        """
        Inicializa o remetente bindando o socket local e configurando parâmetros.

        Args:
            local_addr (tuple): Endereço local (host, porta) para bind.
            dest_addr (tuple): Endereço de destino (host, porta).
            channel: Canal simulado (opcional) para envio.
            timeout (float): Timeout em segundos para retransmissão.
            verbose (bool): Se True, imprime logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.dest = dest_addr
        self.channel = channel
        self.timeout = timeout
        self.seq = 0  # Número de sequência atual
        self.lock = threading.Lock()
        self.waiting_for_ack = threading.Event()
        self.last_packet = None
        self.retransmissions = 0
        self.verbose = verbose
        self.running = True
        self.bytes_sent = 0  # Contador de bytes enviados

        # Inicia thread para receber ACKs
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """
        Envia dados usando o protocolo alternating-bit, aguardando ACK.

        Retransmite pacotes em caso de timeout até receber ACK correto.
        """
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
        """
        Envia o pacote via socket ou canal simulado.
        """
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)

        self.bytes_sent += len(pkt)
        if self.verbose:
            print('[SENDER] Pacote enviado seq=', self.seq, 'len=', len(pkt))

    def _recv_loop(self):
        """
        Loop para receber ACKs e atualizar estado do protocolo.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            # Processa ACK correto
            if info['type'] == TYPE_ACK and not info['corrupt'] and info['seq'] == self.seq:
                if self.verbose:
                    print('[SENDER] ACK recebido seq', info['seq'])
                with self.lock:
                    self.seq = 1 - self.seq
                    self.waiting_for_ack.set()
            else:
                if self.verbose:
                    print('[SENDER] Pacote ignorado (type, corrupt, seq)=',
                          info['type'], info['corrupt'], info['seq'])

    def close(self):
        """Encerra o remetente fechando o socket."""
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class RDT21Receiver:
    """
    Implementa o receptor do protocolo rdt2.1 (alternating-bit protocol).
    """

    def __init__(self, local_addr=('localhost', 10000), deliver_callback=None,
                 channel=None, verbose=True):
        """
        Inicializa o receptor bindando o socket local.

        Args:
            local_addr (tuple): Endereço local (host, porta) para bind.
            deliver_callback (callable): Função chamada ao receber payload.
            channel: Canal simulado (opcional) para envio.
            verbose (bool): Se True, imprime logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0  # Número de sequência esperado
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        self.bytes_received = 0  # Contador de bytes recebidos

        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq: int, addr):
        """
        Envia ACK para o número de sequência informado.

        Args:
            seq (int): Número de sequência do ACK.
            addr (tuple): Endereço de destino (host, porta).
        """
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print('[RECV] ACK enviado seq', seq)

    def _recv_loop(self):
        """
        Loop para recepção e processamento de pacotes.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue

            self.bytes_received += len(data)

            if info['type'] == TYPE_DATA:
                if not info['corrupt'] and info['seq'] == self.expected:
                    # Pacote esperado e íntegro: entrega e envia ACK
                    if self.verbose:
                        print(f'[RECV] Pacote esperado seq {info["seq"]} len={len(info["payload"])}')
                    self.deliver_callback(info['payload'])
                    self._send_ack(self.expected, addr)
                    self.expected = 1 - self.expected
                elif info['corrupt']:
                    # Pacote corrompido: envia NAK
                    if self.verbose:
                        print('[RECV] Pacote corrompido -> envia NAK')
                    nak = make_packet(TYPE_NAK, 0, b'')
                    if self.channel:
                        self.channel.send(nak, self.sock, addr)
                    else:
                        self.sock.sendto(nak, addr)
                else:
                    # Pacote duplicado: reenvia ACK último
                    if self.verbose:
                        print(f'[RECV] Pacote duplicado seq {info["seq"]} -> re-ACK último')
                    self._send_ack(1 - self.expected, addr)

    def close(self):
        """Encerra o receptor fechando o socket."""
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
