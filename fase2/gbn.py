# fase2/gbn.py
"""
Go-Back-N (GBN) compatível com o seu simulator UnreliableChannel.
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
        """
        Envia UM pacote (chave de API igual ao seu original).
        Use repetidamente para enviar uma sequência de pacotes.
        """
        with self.lock:
            # espera janela disponível
            while self.nextseq >= self.base + self.N:
                if self.verbose:
                    print('[GBN SENDER] Window full, waiting... base =', self.base)
                # liberta lock e espera curto
                self.lock.release()
                time.sleep(0.01)
                self.lock.acquire()

            seq_abs = self.nextseq
            # campo de seq no pacote deve caber em 1 byte -> modulo 256
            seq_field = seq_abs % 256
            pkt = make_packet(TYPE_DATA, seq_field, data)
            self.buffer[seq_abs] = pkt

            # envia via canal (mantendo API channel.send(packet, sock, dest))
            if self.channel:
                self.channel.send(pkt, self.sock, self.dest)
            else:
                self.sock.sendto(pkt, self.dest)

            if self.verbose:
                print('[GBN SENDER] Sent seq_abs=', seq_abs, 'mod=', seq_field, 'len=', len(pkt))

            if self.base == self.nextseq:
                # inicia timer só quando pacotes não confirmados existirem
                self._start_timer()

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
                print('[GBN SENDER] Timeout: retransmitting window from base', self.base)
            for seq in range(self.base, self.nextseq):
                pkt = self.buffer.get(seq)
                if pkt is None:
                    continue
                self._send_packet_bytes(pkt)
                self.retransmissions += 1
                if self.verbose:
                    print('[GBN SENDER] Retransmit seq_abs=', seq, 'mod=', seq % 256)
            # reinicia timer
            self._start_timer()

    def _recv_loop(self):
        """
        Recebe ACKs via socket; parse_packet devolve {'type','seq','payload','corrupt'}.
        ACK seq vem como valor 0..255; mapeamos para seq absoluto procurando na janela.
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
                ack_mod = info['seq']  # 0..255
                with self.lock:
                    # procurar seq_abs em [base, nextseq-1] tal que seq_abs % 256 == ack_mod
                    mapped = None
                    for seq in range(self.base, self.nextseq):
                        if (seq % 256) == ack_mod:
                            mapped = seq
                            # importante: queremos o MAIOR seq dentro da janela que corresponda,
                            # porque ACK é cumulativo. Assim continuamos procurando para
                            # encontrar o maior (último) correspondente.
                    if mapped is None:
                        if self.verbose:
                            print('[GBN SENDER] Received ACK mod', ack_mod, 'but no match in window (base..nextseq-1). Ignored.')
                        continue

                    # avança base até mapped+1
                    if self.verbose:
                        print('[GBN SENDER] Received ACK mod', ack_mod, '-> mapped to seq_abs', mapped)
                    self.base = mapped + 1

                    # remove pacotes confirmados do buffer
                    for s in list(self.buffer.keys()):
                        if s < self.base:
                            del self.buffer[s]

                    if self.base == self.nextseq:
                        self._stop_timer()
                    else:
                        self._start_timer()

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        self._stop_timer()


class GBNReceiver:
    def __init__(self, local_addr=('localhost', 14000), deliver_callback=None,
                 channel=None, verbose=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0            # seq absoluta esperada (usamos modulo 256 para comparar)
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq_field, addr):
        pkt = make_packet(TYPE_ACK, seq_field, b'')
        if self.channel:
            # channel.send(pkt, sock, destaddr)
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print('[GBN RECV] Sent ACK', seq_field)

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
                        print('[GBN RECV] Packet corrupt -> ignore (send NAK optional).')
                    # no GBN não enviamos NAK normalmente — apenas ignoramos (ou reenviamos ACK do último)
                    # reenviar ACK do último recebido em ordem
                    last_ack = (self.expected - 1) % 256
                    self._send_ack(last_ack, addr)
                    continue

                recv_seq_field = info['seq']  # 0..255
                # comparar com expected modulo 256
                if recv_seq_field == (self.expected % 256):
                    # pacote esperado
                    if self.verbose:
                        print('[GBN RECV] Received expected seq (mod)', recv_seq_field)
                    # entrega payload
                    self.deliver_callback(info['payload'])
                    # enviar ACK do seq recebido (mod)
                    self._send_ack(recv_seq_field, addr)
                    self.expected += 1
                else:
                    # fora de ordem: reenviar ACK do último recebido em ordem
                    last_ack = (self.expected - 1) % 256
                    if self.verbose:
                        print(f'[GBN RECV] Received out-of-order seq {recv_seq_field}, expected {(self.expected % 256)}. Re-ACK {last_ack}')
                    self._send_ack(last_ack, addr)

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
