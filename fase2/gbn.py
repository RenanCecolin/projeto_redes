# fase2/gbn.py
"""
Go-Back-N (GBN) compatível com o simulator UnreliableChannel.
Uso de seqnum absoluto internamente; o campo de seq no pacote ocupa 1 byte (0..255),
logo colocamos seq % 256 no pacote. Para mapear ACKs (que vêm modulo 256) para
o seq absoluto correto, procuramos dentro da janela base..nextseq-1.
"""

import socket
import threading
import time
from utils.packet import make_packet, parse_packet, TYPE_DATA, TYPE_ACK

class GBNSender:
    def __init__(self, local_addr=('localhost', 0), dest_addr=('localhost', 14000),
                 channel=None, N=5, timeout=2.0, verbose=True):
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
        self.buffer = {}        # buffer[seq_abs] = pkt_bytes
        self.running = True
        self.verbose = verbose
        self.retransmissions = 0
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """Envia UM pacote (pode ser chamado repetidamente para sequência de pacotes)."""
        with self.lock:
            while self.nextseq >= self.base + self.N:
                if self.verbose:
                    print('[GBN SENDER] Window full, waiting... base =', self.base)
                self.lock.release()
                time.sleep(0.01)
                self.lock.acquire()

            seq_abs = self.nextseq
            seq_field = seq_abs % 256
            pkt = make_packet(TYPE_DATA, seq_field, data)
            self.buffer[seq_abs] = pkt

            self._send_packet_bytes(pkt)

            if self.verbose:
                print(f'[GBN SENDER] Sent seq_abs={seq_abs} mod={seq_field} len={len(pkt)}')

            if self.base == self.nextseq:
                self._start_timer()  # inicia timer quando primeiro pacote pendente surge

            self.nextseq += 1

    def _send_packet_bytes(self, pkt):
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)

    def _start_timer(self):
        self._stop_timer()
        self.timer = threading.Timer(self.timeout, self._on_timeout)
        self.timer.start()

    def _stop_timer(self):
        try:
            if self.timer:
                self.timer.cancel()
                self.timer = None
        except Exception:
            pass

    def _on_timeout(self):
        with self.lock:
            if self.verbose:
                print(f'[GBN SENDER] Timeout! Retransmitindo janela a partir de base={self.base}')
            for seq in range(self.base, self.nextseq):
                pkt = self.buffer.get(seq)
                if pkt:
                    self._send_packet_bytes(pkt)
                    self.retransmissions += 1
                    if self.verbose:
                        print(f'[GBN SENDER] Retransmit seq_abs={seq} mod={seq % 256}')
            self._start_timer()  # reinicia o timer após retransmitir

    def _recv_loop(self):
        """Recebe ACKs e avança base conforme confirmação cumulativa."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue

            if info['type'] == TYPE_ACK and not info['corrupt']:
                ack_mod = info['seq']  # 0..255
                with self.lock:
                    mapped = None
                    # Mapeia ACK mod 256 para seq absoluto (considerando wrap-around)
                    for seq in range(self.base, self.nextseq):
                        if (seq % 256) == ack_mod:
                            mapped = seq

                    if mapped is None:
                        # Se não achou dentro da janela, pode ser wrap-around
                        if self.verbose:
                            print(f'[GBN SENDER] ACK {ack_mod} fora da janela base={self.base}')
                        continue

                    if self.verbose:
                        print(f'[GBN SENDER] ACK {ack_mod} -> seq_abs {mapped}')

                    # avança base cumulativamente
                    old_base = self.base
                    self.base = mapped + 1

                    # remove pacotes confirmados
                    for s in list(self.buffer.keys()):
                        if s < self.base:
                            del self.buffer[s]

                    # se todos foram confirmados, parar timer
                    if self.base == self.nextseq:
                        self._stop_timer()
                    # caso contrário, manter timer atual (não reinicia)
                    elif self.base > old_base and self.timer is None:
                        self._start_timer()

    def close(self):
        """Fecha o socket após garantir envio completo."""
        # espera ACKs de todos os pacotes pendentes
        while self.base < self.nextseq and self.running:
            time.sleep(0.05)
        self.running = False
        self._stop_timer()
        try:
            self.sock.close()
        except Exception:
            pass


class GBNReceiver:
    def __init__(self, local_addr=('localhost', 14000), deliver_callback=None,
                 channel=None, verbose=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq_field, addr):
        pkt = make_packet(TYPE_ACK, seq_field, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print(f'[GBN RECV] Sent ACK {seq_field}')

    def _recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue

            if info['type'] == TYPE_DATA:
                if info['corrupt']:
                    if self.verbose:
                        print('[GBN RECV] Packet corrupt, resend last ACK.')
                    last_ack = (self.expected - 1) % 256
                    self._send_ack(last_ack, addr)
                    continue

                recv_seq = info['seq']
                if recv_seq == (self.expected % 256):
                    if self.verbose:
                        print(f'[GBN RECV] Got expected seq={recv_seq}')
                    self.deliver_callback(info['payload'])
                    self._send_ack(recv_seq, addr)
                    self.expected += 1
                else:
                    # fora de ordem → reenvia último ACK válido
                    last_ack = (self.expected - 1) % 256
                    if self.verbose:
                        print(f'[GBN RECV] Out-of-order seq={recv_seq}, expected={self.expected % 256}. Re-ACK {last_ack}')
                    self._send_ack(last_ack, addr)

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
