"""
fase2/gbn.py
Implementação Go-Back-N (GBN) sobre UDP usando janela de envio N e ACKs cumulativos.
Classes: GBNSender, GBNReceiver.
"""

import socket
import threading
import time
from utils.packet import *

class GBNSender:
    """
    Remetente Go-Back-N com janela N e ACKs cumulativos.
    Gerencia o envio, retransmissão e janela.
    """

    def __init__(self, local_addr=('localhost', 0), dest_addr=('localhost', 14000),
                 channel=None, N=5, timeout=2.0, verbose=True):
        """
        Inicializa o sender GBN.

        Args:
            local_addr (tuple): Endereço local p/ bind.
            dest_addr (tuple): Endereço do receptor.
            channel (UnreliableChannel): Canal para simulação (opcional).
            N (int): Tamanho da janela de envio.
            timeout (float): Timeout para retransmissão.
            verbose (bool): Se True, mostra logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.dest = dest_addr
        self.channel = channel
        self.N = N
        self.timeout = timeout
        self.base = 0
        self.nextseq = 0
        self.lock = threading.Lock()
        self.timer = None
        self.buffer = {}
        self.running = True
        self.verbose = verbose
        self.retransmissions = 0
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """
        Envia dados usando o protocolo GBN.
        Aguarda janela disponível para inserir o novo pacote.

        Args:
            data (bytes): Dados para transmissão.
        """
        with self.lock:
            while self.nextseq >= self.base + self.N:
                if self.verbose:
                    print('[GBN SENDER] Window full, waiting... base =', self.base)
                self.lock.release()
                time.sleep(0.01)
                self.lock.acquire()
            seq = self.nextseq
            pkt = make_packet(TYPE_DATA, seq, data)
            self.buffer[seq] = pkt
            self._send_packet(pkt)
            if self.base == self.nextseq:
                self._start_timer()
            self.nextseq += 1

    def _send_packet(self, pkt: bytes):
        """
        Envia um pacote usando canal simulado ou diretamente.

        Args:
            pkt (bytes): Pacote a enviar.
        """
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)
        if self.verbose:
            info = parse_packet(pkt)
            print('[GBN SENDER] Sent seq =', info['seq'])

    def _start_timer(self):
        """
        Inicia o timer para retransmissão dos pacotes em janela.
        """
        self._stop_timer()
        self.timer = threading.Timer(self.timeout, self._on_timeout)
        self.timer.start()

    def _stop_timer(self):
        """
        Para e limpa o timer ativo, se existir.
        """
        try:
            if self.timer:
                self.timer.cancel()
        except Exception:
            pass

    def _on_timeout(self):
        """
        Callback do timeout. Retransmite todos os pacotes não confirmados.
        """
        with self.lock:
            if self.verbose:
                print('[GBN SENDER] Timeout: retransmitting from base', self.base)
            for seq in range(self.base, self.nextseq):
                pkt = self.buffer[seq]
                self._send_packet(pkt)
                self.retransmissions += 1
            self._start_timer()

    def _recv_loop(self):
        """
        Loop do remetente: escuta e processa ACKs cumulativos.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            if info['type'] == TYPE_ACK and not info['corrupt']:
                acknum = info['seq']
                with self.lock:
                    if self.verbose:
                        print('[GBN SENDER] Received ACK', acknum)
                    self.base = acknum + 1
                    if self.base == self.nextseq:
                        self._stop_timer()
                    else:
                        self._start_timer()

    def close(self):
        """
        Finaliza sockets e encerra threads do sender.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class GBNReceiver:
    """
    Receptor Go-Back-N que entrega dados na ordem e envia ACKs cumulativos.
    """

    def __init__(self, local_addr=('localhost', 14000), deliver_callback=None,
                 channel=None, verbose=True):
        """
        Inicializa receptor e configura processamento de dados.

        Args:
            local_addr (tuple): Endereço local do receptor.
            deliver_callback (callable): Função para entrega dos dados.
            channel (UnreliableChannel): Canal simulado (opcional).
            verbose (bool): Se True, mostra logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq, addr):
        """
        Envia ACK cumulativo para o remetente.

        Args:
            seq (int): Número de sequência a confirmar.
            addr (tuple): Endereço para envio do ACK.
        """
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print('[GBN RECV] Sent ACK', seq)

    def _recv_loop(self):
        """
        Loop principal do receptor: recebe dados, entrega na ordem ou descarta e reenvia ACK.
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
                    if self.verbose:
                        print('[GBN RECV] Received expected seq', info['seq'])
                    self.deliver_callback(info['payload'])
                    self._send_ack(self.expected, addr)
                    self.expected += 1
                else:
                    if self.verbose:
                        print('[GBN RECV] Received unexpected/corrupt seq', info['seq'], 'expected', self.expected)
                    self._send_ack(self.expected - 1 if self.expected > 0 else 0, addr)

    def close(self):
        """
        Finaliza sockets e encerra loop da thread receptor.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
