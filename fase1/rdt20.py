"""
rdt20.py
Implementação simples de rdt2.0 (stop-and-wait com ACK/NAK) sobre UDP.
Inclui um simulador de canal não confiável com perda, corrupção e delay.

Como usar (em dois terminais locais):

# Terminal A (Receiver)
python rdt20.py receiver --port 10000

# Terminal B (Sender)
python rdt20.py sender --dest-host 127.0.0.1 --dest-port 10000 --bind-port 10001

O sender enviará 10 mensagens de teste por padrão.
"""

import socket
import threading
import struct
import hashlib
import random
import time
import argparse
from typing import Tuple

# Packet types
TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NAK = 2

# Packet format: | Type (1 byte) | Checksum (4 bytes) | Data (variable) |
# Checksum: first 4 bytes of MD5 over (type byte + data)
PACKET_HDR_FMT = "!B I"  # unsigned char, unsigned int (network byte order)
PACKET_HDR_SIZE = struct.calcsize(PACKET_HDR_FMT)


def make_checksum(packet_type: int, data: bytes) -> int:
    """
    Gera o checksum como os primeiros 4 bytes do MD5 do tipo e dados do pacote.

    Args:
        packet_type (int): Tipo do pacote (0=DATA, 1=ACK, 2=NAK).
        data (bytes): Conteúdo de dados do pacote.

    Returns:
        int: Checksum calculado como uint32.
    """
    m = hashlib.md5()
    m.update(struct.pack("!B", packet_type))
    m.update(data)
    digest = m.digest()
    # Usa os primeiros 4 bytes como uint32
    return struct.unpack("!I", digest[:4])[0]


def build_packet(packet_type: int, data: bytes = b"") -> bytes:
    """
    Monta um pacote concatenando o cabeçalho e os dados.

    Args:
        packet_type (int): Tipo do pacote.
        data (bytes, opcional): Dados do pacote. Defaults to b"".

    Returns:
        bytes: Pacote pronto para envio.
    """
    cs = make_checksum(packet_type, data)
    return struct.pack(PACKET_HDR_FMT, packet_type, cs) + data


def parse_packet(packet: bytes) -> Tuple[int, int, bytes]:
    """
    Desmonta um pacote recebido em tipo, checksum e dados.

    Args:
        packet (bytes): Pacote recebido.

    Raises:
        ValueError: Se o pacote for muito curto.

    Returns:
        Tuple[int, int, bytes]: Tipo do pacote, checksum e dados.
    """
    if len(packet) < PACKET_HDR_SIZE:
        raise ValueError("Packet too short")
    ptype, cs = struct.unpack(PACKET_HDR_FMT, packet[:PACKET_HDR_SIZE])
    data = packet[PACKET_HDR_SIZE:]
    return ptype, cs, data



class UnreliableChannel:
    """
    Simula perda, corrupção e atraso antes de enviar via UDP.
    O método send() agenda um sendto() com delay (threading.Timer).
    """

    def __init__(self, loss_rate=0.0, corrupt_rate=0.0, delay_range=(0.0, 0.0)):
        """
        Inicializa o canal com parâmetros de simulação.

        Args:
            loss_rate (float, opcional): Probabilidade de perda [0..1]. Defaults to 0.0.
            corrupt_rate (float, opcional): Probabilidade de corrupção [0..1]. Defaults to 0.0.
            delay_range (tuple, opcional): Tupla (mínimo, máximo) em segundos para delay. Defaults to (0.0, 0.0).
        """
        self.loss_rate = loss_rate
        self.corrupt_rate = corrupt_rate
        self.delay_range = delay_range
        self.lock = threading.Lock()

    def send(self, packet: bytes, dest_socket: socket.socket, dest_addr):
        """
        Envia o pacote simulando perda, corrupção e atraso.

        Args:
            packet (bytes): Pacote a enviar.
            dest_socket (socket.socket): Socket para envio.
            dest_addr (tuple): Endereço de destino (host, port).
        """
        # Simula perda
        if random.random() < self.loss_rate:
            print("[SIM] Pacote perdido pelo canal")
            return

        # Simula corrupção
        if random.random() < self.corrupt_rate:
            packet = self._corrupt_packet(packet)
            print("[SIM] Pacote corrompido pelo canal")

        # Simula atraso
        delay = random.uniform(*self.delay_range)
        threading.Timer(delay, lambda: dest_socket.sendto(packet, dest_addr)).start()

    def _corrupt_packet(self, packet: bytes) -> bytes:
        """
        Corrompe aleatoriamente alguns bytes do pacote.

        Args:
            packet (bytes): Pacote original.

        Returns:
            bytes: Pacote corrompido.
        """
        if len(packet) == 0:
            return packet
        b = bytearray(packet)
        # Inverte alguns bytes aleatórios
        num_corruptions = random.randint(1, max(1, min(5, len(b))))
        for _ in range(num_corruptions):
            idx = random.randint(0, len(b) - 1)
            b[idx] = b[idx] ^ 0xFF
        return bytes(b)


class RDT20Receiver:
    """
    Implementação do receptor do protocolo rdt2.0.
    """

    def __init__(self, listen_port: int, channel: UnreliableChannel):
        """
        Inicializa o receptor.

        Args:
            listen_port (int): Porta para escutar.
            channel (UnreliableChannel): Canal para enviar ACK/NAK.
        """
        self.port = listen_port
        self.channel = channel
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.port))
        self.received_messages = []
        self.running = True
        print(f"[RECV] Listening on port {self.port}")

    def start(self):
        """
        Inicia o loop principal de recepção e processamento de pacotes.
        """
        try:
            while self.running:
                try:
                    packet, addr = self.sock.recvfrom(65536)
                except OSError:
                    break
                try:
                    ptype, cs, data = parse_packet(packet)
                except Exception as e:
                    print(f"[RECV] Packet parse error: {e}")
                    continue

                calc_cs = make_checksum(ptype, data)
                if calc_cs != cs:
                    # checksum mismatch -> corrupted
                    print(f"[RECV] Received CORRUPTED packet from {addr}. Sending NAK.")
                    nak_pkt = build_packet(TYPE_NAK, b"")
                    # usa o canal para simular caminho de volta
                    self.channel.send(nak_pkt, self.sock, addr)
                    continue

                if ptype == TYPE_DATA:
                    # entrega para aplicação
                    msg = data.decode(errors="replace")
                    print(f"[RECV] Delivered message from {addr}: {msg}")
                    self.received_messages.append(msg)
                    # envia ACK
                    ack_pkt = build_packet(TYPE_ACK, b"")
                    self.channel.send(ack_pkt, self.sock, addr)
                else:
                    # ignora tipos inesperados no receptor
                    print(f"[RECV] Received unexpected packet type {ptype} from {addr}")
        except KeyboardInterrupt:
            print("[RECV] Interrupted, shutting down.")
        finally:
            self.sock.close()

    def stop(self):
        """
        Para a execução do receptor e fecha o socket.
        """
        self.running = False
        self.sock.close()


class RDT20Sender:
    """
    Implementação do remetente do protocolo rdt2.0.
    """

    def __init__(self, bind_port: int, dest_host: str, dest_port: int, channel: UnreliableChannel, timeout=2.0):
        """
        Inicializa o remetente.

        Args:
            bind_port (int): Porta local para bind.
            dest_host (str): Host de destino.
            dest_port (int): Porta de destino.
            channel (UnreliableChannel): Canal para enviar pacotes.
            timeout (float, opcional): Timeout de espera por ACK/NAK. Defaults to 2.0.
        """
        self.bind_port = bind_port
        self.dest = (dest_host, dest_port)
        self.channel = channel
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind para permitir resposta do receptor
        self.sock.bind(("0.0.0.0", self.bind_port))
        self.timeout = timeout
        self.sock.settimeout(self.timeout)
        self.retransmissions = 0
        print(f"[SEND] Sender bound on port {self.bind_port} -> dest {self.dest}")

    def send_message(self, message: str) -> bool:
        """
        Envia uma mensagem com retransmissão até receber ACK.

        Args:
            message (str): Mensagem a enviar.

        Returns:
            bool: True se recebido ACK, False caso contrário.
        """
        data = message.encode()
        pkt = build_packet(TYPE_DATA, data)

        while True:
            # envia via canal não confiável
            self.channel.send(pkt, self.sock, self.dest)
            send_time = time.time()
            try:
                resp, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                # timeout -> retransmite
                self.retransmissions += 1
                print(f"[SEND] Timeout waiting ACK/NAK, retransmitting (total retrans={self.retransmissions})")
                continue

            try:
                rtype, rcs, rdata = parse_packet(resp)
            except Exception as e:
                print(f"[SEND] Parse error on response: {e}. Retransmitting.")
                self.retransmissions += 1
                continue

            # verifica checksum da resposta
            calc = make_checksum(rtype, rdata)
            if calc != rcs:
                print("[SEND] Received corrupted ACK/NAK -> retransmit")
                self.retransmissions += 1
                continue

            if rtype == TYPE_ACK:
                sample_rtt = time.time() - send_time
                print(f"[SEND] Received ACK from {addr} (RTT sample {sample_rtt:.3f}s)")
                return True
            elif rtype == TYPE_NAK:
                print("[SEND] Received NAK -> retransmit")
                self.retransmissions += 1
                continue
            else:
                print(f"[SEND] Unexpected response type {rtype} -> ignore and retransmit")
                self.retransmissions += 1
                continue

    def close(self):
        """
        Fecha o socket do remetente.
        """
        self.sock.close()


def run_receiver(port: int, loss: float, corrupt: float, mindelay: float, maxdelay: float):
    """
    Função auxiliar para executar o receptor com parâmetros configurados.

    Args:
        port (int): Porta para escutar.
        loss (float): Probabilidade de perda.
        corrupt (float): Probabilidade de corrupção.
        mindelay (float): Delay mínimo em segundos.
        maxdelay (float): Delay máximo em segundos.
    """
    channel = UnreliableChannel(loss_rate=loss, corrupt_rate=corrupt, delay_range=(mindelay, maxdelay))
    receiver = RDT20Receiver(port, channel)
    try:
        receiver.start()
    except KeyboardInterrupt:
        receiver.stop()


def run_sender(dest_host: str, dest_port: int, bind_port: int, loss: float, corrupt: float,
               mindelay: float, maxdelay: float, messages_count: int = 10):
    """
    Função auxiliar para executar o remetente com parâmetros configurados.

    Args:
        dest_host (str): Host de destino.
        dest_port (int): Porta de destino.
        bind_port (int): Porta local para bind.
        loss (float): Probabilidade de perda.
        corrupt (float): Probabilidade de corrupção.
        mindelay (float): Delay mínimo em segundos.
        maxdelay (float): Delay máximo em segundos.
        messages_count (int, opcional): Número de mensagens a enviar. Defaults to 10.
    """
    channel = UnreliableChannel(loss_rate=loss, corrupt_rate=corrupt, delay_range=(mindelay, maxdelay))
    sender = RDT20Sender(bind_port, dest_host, dest_port, channel, timeout=1.0)

    stats = {
        "sent": 0,
        "retransmissions": 0
    }

    for i in range(messages_count):
        msg = f"Mensagem {i}"
        print(f"[TEST] Enviando: '{msg}'")
        stats["sent"] += 1
        ok = sender.send_message(msg)
        # no protocolo, send_message retorna apenas após ACK
        if not ok:
            print("[TEST] Falha ao enviar mensagem (sem ACK).")
        time.sleep(0.05)  # pequena pausa entre mensagens

    stats["retransmissions"] = sender.retransmissions
    print("==== TEST SUMMARY ====")
    print(f"Mensagens intentadas: {stats['sent']}")
    print(f"Retransmissões: {stats['retransmissions']}")
    sender.close()


def parse_args():
    """
    Parseia os argumentos de linha de comando para configurar sender ou receiver.

    Returns:
        argparse.Namespace: Argumentos parseados.
    """
    ap = argparse.ArgumentParser(description="rdt2.0 demo (stop-and-wait) with UnreliableChannel")
    sub = ap.add_subparsers(dest="role", required=True)

    recv_p = sub.add_parser("receiver")
    recv_p.add_argument("--port", type=int, default=10000)
    recv_p.add_argument("--loss", type=float, default=0.0, help="loss probability [0..1]")
    recv_p.add_argument("--corrupt", type=float, default=0.0, help="corruption probability [0..1]")
    recv_p.add_argument("--mindelay", type=float, default=0.0)
    recv_p.add_argument("--maxdelay", type=float, default=0.0)

    send_p = sub.add_parser("sender")
    send_p.add_argument("--dest-host", type=str, default="127.0.0.1")
    send_p.add_argument("--dest-port", type=int, default=10000)
    send_p.add_argument("--bind-port", type=int, default=10001)
    send_p.add_argument("--loss", type=float, default=0.0, help="loss probability [0..1]")
    send_p.add_argument("--corrupt", type=float, default=0.0, help="corruption probability [0..1]")
    send_p.add_argument("--mindelay", type=float, default=0.0)
    send_p.add_argument("--maxdelay", type=float, default=0.0)
    send_p.add_argument("--count", type=int, default=10, help="how many messages to send")

    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.role == "receiver":
        run_receiver(args.port, args.loss, args.corrupt, args.mindelay, args.maxdelay)
    elif args.role == "sender":
        run_sender(args.dest_host, args.dest_port, args.bind_port,
                   args.loss, args.corrupt, args.mindelay, args.maxdelay, args.count)
