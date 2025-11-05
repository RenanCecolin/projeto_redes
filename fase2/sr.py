import socket
import threading
import time
from utils.packet import make_packet, parse_packet, is_corrupt, TYPE_DATA, TYPE_ACK
from utils.simulator import sendto_via_channel

TIMEOUT = 2.0

def seq_in_range(seq, start, end, max_seq):
    """Verifica se um número de sequência está dentro da janela circular."""
    if start <= end:
        return start <= seq < end
    else:
        return seq >= start or seq < end


class SR_Sender:
    def __init__(self, sender_addr=('localhost', 12000), receiver_addr=('localhost', 12001),
                 channel=None, window_size=4, timeout=TIMEOUT):
        self.sender_addr = sender_addr
        self.receiver_addr = receiver_addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(sender_addr)

        self.channel = channel
        self.window_size = window_size
        self.timeout = timeout

        self.base = 0
        self.next_seq = 0
        self.lock = threading.Lock()
        self.buffer = {}          # pacotes não confirmados
        self.acked = {}           # flags de ACK
        self.total_chunks = 0

    def send(self, data_chunks):
        self.total_chunks = len(data_chunks)
        recv_thread = threading.Thread(target=self._receive_acks, daemon=True)
        recv_thread.start()

        while self.base < self.total_chunks:
            with self.lock:
                # Envia pacotes dentro da janela
                while seq_in_range(self.next_seq % 256,
                                self.base % 256,
                                (self.base + self.window_size) % 256,
                                256) and (self.next_seq < self.total_chunks):
                    payload = data_chunks[self.next_seq]
                    if isinstance(payload, str):
                        payload = payload.encode()
                    elif isinstance(payload, int):
                        payload = str(payload).encode()
                    elif payload is None:
                        payload = b""

                    # Apenas o campo do pacote usa %256
                    pkt = make_packet(TYPE_DATA, self.next_seq % 256, payload)
                    self.buffer[self.next_seq] = pkt
                    print(f"[SR_Sender] Enviando pacote {self.next_seq}.")
                    sendto_via_channel(self.sock, pkt, self.receiver_addr, self.channel)
                    self._start_timer(self.next_seq)
                    self.next_seq += 1  # sem módulo aqui

            time.sleep(0.05)

        # Espera todos ACKs
        while self.base < self.total_chunks:
            time.sleep(0.05)
        print("[SR_Sender] Todos os pacotes foram enviados e confirmados.")

    def _start_timer(self, seq):
        t = threading.Thread(target=self._timeout_thread, args=(seq,), daemon=True)
        t.start()

    def _timeout_thread(self, seq):
        time.sleep(self.timeout)
        with self.lock:
            if seq not in self.acked:
                print(f"[SR_Sender] Timeout seq={seq}, retransmitindo.")
                pkt = self.buffer[seq]
                sendto_via_channel(self.sock, pkt, self.receiver_addr, self.channel)
                self._start_timer(seq)

    def _receive_acks(self):
        while True:
            try:
                pkt_bytes, _ = self.sock.recvfrom(2048)
            except OSError:
                break

            pkt = parse_packet(pkt_bytes)
            if not pkt or is_corrupt(pkt):
                continue
            if pkt['type'] == TYPE_ACK:
                ack_mod = pkt['seq']

                with self.lock:
                    # Procura qual seq lógico corresponde a esse ack_mod
                    # Encontrar o pacote mais recente com mesmo número mod 256
                    matches = [seq for seq in self.buffer.keys() if seq % 256 == ack_mod]
                    if matches:
                        seq = max(matches)  # sempre pega o mais novo (ex: 256 em vez de 0)
                        self.acked[seq] = True
                        print(f"[SR_Sender] ACK recebido {seq} (mod={ack_mod}).")

                        # Atualiza base
                        while self.base in self.acked and self.acked[self.base]:
                            self.base += 1

                    # Atualiza base
                    while self.base in self.acked and self.acked[self.base]:
                        self.base += 1


class SR_Receiver:
    def __init__(self, sender_addr=('localhost', 12000), receiver_addr=('localhost', 12001),
                 channel=None, window_size=4):
        self.sender_addr = sender_addr
        self.receiver_addr = receiver_addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(receiver_addr)

        self.channel = channel
        self.window_size = window_size
        self.expected_seq = 0
        self.buffer = {}
        self.delivered_data = []

    def receive(self):
        while True:
            pkt_bytes, addr = self.sock.recvfrom(2048)
            pkt = parse_packet(pkt_bytes)
            if not pkt or is_corrupt(pkt):
                continue
            if pkt['type'] == TYPE_DATA:
                seq_mod = pkt['seq']
                data = pkt['payload']

                # Envia ACK
                ack_pkt = make_packet(TYPE_ACK, seq_mod, b'')
                sendto_via_channel(self.sock, ack_pkt, addr, self.channel)
                print(f"[SR_Receiver] ACK enviado {seq_mod}.")

                # Ignora pacotes duplicados já entregues
                if seq_mod in self.buffer:
                    continue

                # Entrega se dentro da janela esperada
                if seq_mod == (self.expected_seq % 256):
                    self.buffer[seq_mod] = data
                    while (self.expected_seq % 256) in self.buffer:
                        msg = self.buffer[self.expected_seq % 256]
                        self.delivered_data.append(msg)
                        print(f"[SR_Receiver] Entregando pacote {self.expected_seq}.")
                        del self.buffer[self.expected_seq % 256]
                        self.expected_seq += 1
                else:
                    # Armazena fora de ordem (selective repeat)
                    if seq_in_range(seq_mod,
                                    self.expected_seq % 256,
                                    (self.expected_seq + self.window_size) % 256,
                                    256):
                        self.buffer[seq_mod] = data
