import socket
import threading
import time
from utils.packet import make_packet, parse_packet, is_corrupt, TYPE_DATA, TYPE_ACK
from utils.simulator import sendto_via_channel

def seq_in_range(seq, start, end, max_seq=256):
    """Verifica se um número de sequência está dentro da janela circular."""
    if start <= end:
        return start <= seq < end
    else:
        return seq >= start or seq < end

# ===================== Sender =====================
class SR_Sender:
    def __init__(self, channel, window_size=4, timeout=1.0,
                 local_addr=('localhost', 0), dest_addr=None):
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
        self.buffer = {}  # seq -> packet
        self.timers = {}  # seq -> start_time
        self.acks = {}    # seq -> bool
        self.retransmissions = 0

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        # Thread para receber ACKs
        self.recv_thread = threading.Thread(target=self._receive_acks, daemon=True)
        self.recv_thread.start()

    def send(self, data_chunks):
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

        # Espera todos os ACKs
        while True:
            with self.lock:
                if not self.buffer:
                    break
            self._check_timeouts()
            time.sleep(0.05)

    def _check_timeouts(self):
        with self.lock:
            for seq in list(self.buffer.keys()):
                if not self.acks[seq] and time.time() - self.timers[seq] > self.timeout:
                    sendto_via_channel(self.sock, self.buffer[seq], self.dest_addr, self.channel)
                    self.timers[seq] = time.time()
                    self.retransmissions += 1

    def _receive_acks(self):
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
        self.stop_event.set()
        time.sleep(0.2)
        try:
            self.sock.close()
        except Exception:
            pass

# ===================== Receiver =====================
class SR_Receiver:
    def __init__(self, channel, window_size=4,
                 local_addr=('localhost', 0), sender_addr=None,
                 deliver_callback=None):
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

                    # Entrega em ordem
                    while self.expected_seq % 256 in self.buffer:
                        msg = self.buffer[self.expected_seq % 256]
                        self.delivered_data.append(msg)
                        if self.deliver_callback:
                            self.deliver_callback(msg)  # <-- chama callback do simulador
                        del self.buffer[self.expected_seq % 256]
                        self.expected_seq += 1

    def get_received_chunks(self):
        return self.delivered_data.copy()

    def close(self):
        self.stop_event.set()
        time.sleep(0.1)
        try:
            self.sock.close()
        except Exception:
            pass
