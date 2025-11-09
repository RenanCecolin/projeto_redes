"""
rdt20.py

Este módulo implementa um sender e um receiver simples que utilizam um
canal não confiável (perda, corrupção e atraso) para testar a
lógica de retransmissão do rdt2.0.

"""

from __future__ import annotations

import argparse
import hashlib
import random
import socket
import struct
import threading
import time
from typing import Tuple

# Tipos de pacote
TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NAK = 2

# Formato do cabeçalho: | Type (1 byte) | Checksum (4 bytes) |
# O checksum é os primeiros 4 bytes do MD5 sobre (type byte + data)
PACKET_HDR_FMT = "!B I"  # unsigned char, unsigned int (network order)
PACKET_HDR_SIZE = struct.calcsize(PACKET_HDR_FMT)


def make_checksum(packet_type: int, data: bytes) -> int:
    """
    Gera o checksum de um pacote.

    O checksum é calculado como os primeiros 4 bytes do digest MD5 do
    tipo de pacote seguido dos bytes de dados. O valor retornado é um
    inteiro sem sinal de 32 bits (uint32).

    Args:
        packet_type: Tipo do pacote (0=DATA, 1=ACK, 2=NAK).
        data: Conteúdo do pacote em bytes.

    Returns:
        Um inteiro representando o checksum (uint32).
    """
    m = hashlib.md5()
    m.update(struct.pack("!B", packet_type))
    m.update(data)
    digest = m.digest()
    return struct.unpack("!I", digest[:4])[0]


def build_packet(packet_type: int, data: bytes = b"") -> bytes:
    """
    Monta um pacote pré-pronto para envio pela rede.

    Layout: cabeçalho (tipo + checksum) seguido pelo payload.

    Args:
        packet_type: Tipo do pacote (TYPE_DATA, TYPE_ACK, TYPE_NAK).
        data: Dados opcionais como bytes.

    Returns:
        Bytes contendo o pacote serializado.
    """
    cs = make_checksum(packet_type, data)
    header = struct.pack(PACKET_HDR_FMT, packet_type, cs)
    return header + data


def parse_packet(packet: bytes) -> Tuple[int, int, bytes]:
    """
    Desmonta um pacote recebido em (tipo, checksum, dados).

    Args:
        packet: Bytes recebidos do socket.

    Raises:
        ValueError: Se o pacote for menor do que o cabeçalho esperado.

    Returns:
        Tupla (packet_type, checksum, data).
    """
    if len(packet) < PACKET_HDR_SIZE:
        raise ValueError("Packet too short")

    packet_type, checksum = struct.unpack(
        PACKET_HDR_FMT, packet[:PACKET_HDR_SIZE]
    )
    data = packet[PACKET_HDR_SIZE:]
    return packet_type, checksum, data


class UnreliableChannel:
    """
    Canal não confiável que simula perda, corrupção e atraso.

    Esse objeto não substitui o socket; em vez disso, ele encapsula
    chamadas a socket.sendto() e aplica a simulação antes de
    efetivamente enviar os bytes. O envio atrasado é feito com
    threading.Timer para não bloquear a thread chamadora.
    """

    def __init__(
        self,
        loss_rate: float = 0.0,
        corrupt_rate: float = 0.0,
        delay_range: Tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """
        Inicializa o canal com as probabilidades e intervalo de delay.

        Args:
            loss_rate: Probabilidade de perda [0..1].
            corrupt_rate: Probabilidade de corrupção [0..1].
            delay_range: (min_delay, max_delay) em segundos.
        """
        self.loss_rate = float(loss_rate)
        self.corrupt_rate = float(corrupt_rate)
        self.delay_range = (
            float(delay_range[0]), float(delay_range[1])
        )
        self.lock = threading.Lock()

    def send(self, packet: bytes, dest_socket: socket.socket, dest_addr) -> None:
        """
        Envia o pacote simulando perda, corrupção e atraso.

        A função pode optar por dropar o pacote (simular perda),
        corrompê-lo, ou agendar um envio atrasado usando threading.

        Args:
            packet: Bytes do pacote a enviar.
            dest_socket: Socket UDP usado para enviar.
            dest_addr: Tupla (host, port) de destino.
        """
        # Simula perda
        if random.random() < self.loss_rate:
            print("[SIM] Pacote perdido pelo canal")
            return

        # Simula corrupcao
        if random.random() < self.corrupt_rate:
            packet = self._corrupt_packet(packet)
            print("[SIM] Pacote corrompido pelo canal")

        # Simula atraso aleatorio
        delay = random.uniform(self.delay_range[0], self.delay_range[1])

        def _delayed_send() -> None:
            try:
                dest_socket.sendto(packet, dest_addr)
            except OSError as exc:
                # Erros ao enviar (por exemplo socket fechado) são
                # ignorados para não interromper a simulação.
                print(f"[SIM] Falha ao enviar pacote: {exc}")

        timer = threading.Timer(delay, _delayed_send)
        timer.daemon = True
        timer.start()

    def _corrupt_packet(self, packet: bytes) -> bytes:
        """
        Corrompe alguns bytes aleatoriamente no pacote.

        A corrupção é feita invertendo bits em posições aleatórias
        do array de bytes, preservando o tamanho original.

        Args:
            packet: Bytes originais.

        Returns:
            Bytes corrompidos.
        """
        if not packet:
            return packet

        b = bytearray(packet)
        max_corrupt = min(5, len(b))
        num_corruptions = random.randint(1, max(1, max_corrupt))

        for _ in range(num_corruptions):
            idx = random.randint(0, len(b) - 1)
            b[idx] ^= 0xFF

        return bytes(b)


class RDT20Receiver:
    """
    Receptor do protocolo rdt2.0 (stop-and-wait com ACK/NAK).

    O receptor valida o checksum dos pacotes recebidos e responde com
    ACK se o pacote estiver integro ou NAK se for detectada corrupção.
    Pacotes de dados vão para a aplicação local (lista interna).
    """

    def __init__(self, listen_port: int, channel: UnreliableChannel) -> None:
        """
        Inicializa o receptor e faz o bind do socket UDP.

        Args:
            listen_port: Porta local para escuta UDP.
            channel: Canal não confiável para enviar ACK/NAK.
        """
        self.port = int(listen_port)
        self.channel = channel
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Faz bind em todas interfaces para a porta indicada.
        self.sock.bind(("0.0.0.0", self.port))
        self.received_messages: list[str] = []
        self.running = True
        print(f"[RECV] Escutando na porta {self.port}")

    def start(self) -> None:
        """
        Loop principal de recepcao. Bloqueia a thread atual e processa
        pacotes até que stop() seja chamado ou ocorra interrupção.
        """
        try:
            while self.running:
                try:
                    packet, addr = self.sock.recvfrom(65536)
                except OSError:
                    # Socket fechado externamente; encerra loop.
                    break

                try:
                    ptype, cs, data = parse_packet(packet)
                except Exception as exc:
                    # Erros de parse não devem interromper o receptor.
                    print(f"[RECV] Erro ao parsear pacote: {exc}")
                    continue

                calc_cs = make_checksum(ptype, data)
                if calc_cs != cs:
                    # Pacote corrompido: envia NAK usando o canal.
                    print(
                        f"[RECV] Pacote CORROMPIDO de {addr}. Enviando NAK."
                    )
                    nak_pkt = build_packet(TYPE_NAK, b"")
                    self.channel.send(nak_pkt, self.sock, addr)
                    continue

                if ptype == TYPE_DATA:
                    # Entrega a carga para a aplicação.
                    msg = data.decode(errors="replace")
                    print(f"[RECV] Mensagem entregue de {addr}: {msg}")
                    self.received_messages.append(msg)
                    # Envia ACK em resposta.
                    ack_pkt = build_packet(TYPE_ACK, b"")
                    self.channel.send(ack_pkt, self.sock, addr)
                else:
                    # Ignora tipos inesperados (ACK/NAK no receptor).
                    print(
                        f"[RECV] Tipo inesperado {ptype} vindo de {addr}"
                    )
        except KeyboardInterrupt:
            print("[RECV] Interrompido pelo usuario, encerrando.")
        finally:
            try:
                self.sock.close()
            except OSError:
                pass

    def stop(self) -> None:
        """
        Encerra o loop de recepcao e fecha o socket.
        """
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class RDT20Sender:
    """
    Remetente do protocolo rdt2.0 (stop-and-wait com ACK/NAK).

    O remetente envia um pacote DATA e aguarda um ACK; em caso de
    timeout ou NAK ele retransmite repetidamente até receber um ACK
    válido.
    """

    def __init__(
        self,
        bind_port: int,
        dest_host: str,
        dest_port: int,
        channel: UnreliableChannel,
        timeout: float = 2.0,
    ) -> None:
        """
        Inicializa o remetente e faz o bind do socket para receber
        respostas (ACK/NAK).

        Args:
            bind_port: Porta local para receber respostas.
            dest_host: Host de destino.
            dest_port: Porta de destino.
            channel: Canal não confiável para enviar pacotes.
            timeout: Timeout em segundos para aguardar resposta.
        """
        self.bind_port = int(bind_port)
        self.dest = (str(dest_host), int(dest_port))
        self.channel = channel
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind para poder receber respostas do receptor.
        self.sock.bind(("0.0.0.0", self.bind_port))
        self.timeout = float(timeout)
        self.sock.settimeout(self.timeout)
        self.retransmissions = 0
        print(
            f"[SEND] Sender bound on port {self.bind_port} -> "
            f"dest {self.dest}"
        )

    def send_message(self, message: str) -> bool:
        """
        Envia uma mensagem e aguarda ACK; retransmite em caso de
        timeout, NAK ou pacote de resposta corrompido.

        Args:
            message: Texto a ser enviado como payload.

        Returns:
            True se ACK recebido; False se ocorrer falha grave.
        """
        data = message.encode()
        pkt = build_packet(TYPE_DATA, data)

        while True:
            # Envia via canal não confiável (simula perda/corrupcao).
            self.channel.send(pkt, self.sock, self.dest)
            send_time = time.time()

            try:
                resp, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                # Timeout: incrementa contador e retransmite.
                self.retransmissions += 1
                print(
                    "[SEND] Timeout esperando ACK/NAK, retransmitindo"
                )
                continue

            try:
                rtype, rcs, rdata = parse_packet(resp)
            except Exception as exc:
                # Resposta mal-formada: retransmite.
                print(f"[SEND] Erro ao parsear resposta: {exc}. Retransmit.")
                self.retransmissions += 1
                continue

            # Verifica checksum da resposta.
            calc = make_checksum(rtype, rdata)
            if calc != rcs:
                print("[SEND] ACK/NAK corrompido recebido -> retransmit")
                self.retransmissions += 1
                continue

            if rtype == TYPE_ACK:
                sample_rtt = time.time() - send_time
                print(
                    f"[SEND] ACK recebido de {addr} (RTT amostra "
                    f"{sample_rtt:.3f}s)"
                )
                return True

            if rtype == TYPE_NAK:
                print("[SEND] NAK recebido -> retransmit")
                self.retransmissions += 1
                continue

            # Tipo inesperado: contabiliza e retransmite.
            print(
                f"[SEND] Tipo de resposta inesperado {rtype} de {addr} "
                "-> retransmit"
            )
            self.retransmissions += 1

    def close(self) -> None:
        """
        Fecha o socket do remetente.
        """
        try:
            self.sock.close()
        except OSError:
            pass


def run_receiver(
    port: int, loss: float, corrupt: float, mindelay: float, maxdelay: float
) -> None:
    """
    Função auxiliar que configura o canal e inicia o receptor.

    Args:
        port: Porta para escutar.
        loss: Probabilidade de perda [0..1].
        corrupt: Probabilidade de corrupção [0..1].
        mindelay: Delay mínimo em segundos.
        maxdelay: Delay máximo em segundos.
    """
    channel = UnreliableChannel(
        loss_rate=loss, corrupt_rate=corrupt, delay_range=(mindelay, maxdelay)
    )
    receiver = RDT20Receiver(port, channel)

    try:
        receiver.start()
    except KeyboardInterrupt:
        receiver.stop()


def run_sender(
    dest_host: str,
    dest_port: int,
    bind_port: int,
    loss: float,
    corrupt: float,
    mindelay: float,
    maxdelay: float,
    messages_count: int = 10,
) -> None:
    """
    Função auxiliar que configura o canal e envia uma série de
    mensagens de teste pelo remetente.

    Args:
        dest_host: Host de destino.
        dest_port: Porta de destino.
        bind_port: Porta local para bind.
        loss: Probabilidade de perda.
        corrupt: Probabilidade de corrupção.
        mindelay: Delay mínimo em segundos.
        maxdelay: Delay máximo em segundos.
        messages_count: Quantas mensagens enviar (padrão 10).
    """
    channel = UnreliableChannel(
        loss_rate=loss, corrupt_rate=corrupt, delay_range=(mindelay, maxdelay)
    )
    sender = RDT20Sender(bind_port, dest_host, dest_port, channel, timeout=1.0)

    stats = {"sent": 0, "retransmissions": 0}

    for i in range(messages_count):
        msg = f"Mensagem {i}"
        print(f"[TEST] Enviando: '{msg}'")
        stats["sent"] += 1
        ok = sender.send_message(msg)
        if not ok:
            print("[TEST] Falha ao enviar mensagem (sem ACK).")
        # Pequena pausa entre envios para nao saturar o socket.
        time.sleep(0.05)

    stats["retransmissions"] = sender.retransmissions
    print("==== RESUMO DO TESTE ====")
    print(f"Mensagens tentadas: {stats['sent']}")
    print(f"Retransmissoes: {stats['retransmissions']}")
    sender.close()


def parse_args() -> argparse.Namespace:
    """
    Parseia argumentos de linha de comando para configurar sender ou
    receiver.

    Returns:
        argparse.Namespace com os argumentos parseados.
    """
    ap = argparse.ArgumentParser(
        description=(
            "rdt2.0 demo (stop-and-wait) com UnreliableChannel - PEP8"
        )
    )
    sub = ap.add_subparsers(dest="role", required=True)

    recv_p = sub.add_parser("receiver")
    recv_p.add_argument("--port", type=int, default=10000)
    recv_p.add_argument(
        "--loss", type=float, default=0.0, help="probabilidade de perda"
    )
    recv_p.add_argument(
        "--corrupt", type=float, default=0.0,
        help="probabilidade de corrupcao"
    )
    recv_p.add_argument("--mindelay", type=float, default=0.0)
    recv_p.add_argument("--maxdelay", type=float, default=0.0)

    send_p = sub.add_parser("sender")
    send_p.add_argument("--dest-host", type=str, default="127.0.0.1")
    send_p.add_argument("--dest-port", type=int, default=10000)
    send_p.add_argument("--bind-port", type=int, default=10001)
    send_p.add_argument(
        "--loss", type=float, default=0.0, help="probabilidade de perda"
    )
    send_p.add_argument(
        "--corrupt", type=float, default=0.0,
        help="probabilidade de corrupcao"
    )
    send_p.add_argument("--mindelay", type=float, default=0.0)
    send_p.add_argument("--maxdelay", type=float, default=0.0)
    send_p.add_argument(
        "--count", type=int, default=10, help="quantas mensagens enviar"
    )

    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.role == "receiver":
        run_receiver(args.port, args.loss, args.corrupt, args.mindelay,
                     args.maxdelay)
    elif args.role == "sender":
        run_sender(
            args.dest_host,
            args.dest_port,
            args.bind_port,
            args.loss,
            args.corrupt,
            args.mindelay,
            args.maxdelay,
            args.count,
        )
