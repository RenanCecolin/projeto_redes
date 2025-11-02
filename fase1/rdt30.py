"""
rdt30.py
Implementação do rdt3.0: rdt2.1 + timer + perda de pacotes
Timer implementado no lado do remetente, e modelo Stop-and-Wait.
Simula perda de 15% dos pacotes DATA e ACKs, e atraso variável de 50-500 ms.

Uso de exemplo:
    - Rodar em terminais diferentes utilizando Git bash:
        -> python -m fase1.rdt30 receiver --local-port 10000 --verbose
        -> python -m fase1.rdt30 sender --local-port 0 --dest-port 10000 --verbose
"""

import socket
import threading
import time
import random
import argparse
from typing import Optional, Tuple, Callable
from utils.packet import *  # Assumindo make_packet, parse_packet e constantes TYPE_DATA, TYPE_ACK, TYPE_NAK


class UnreliableChannel:
    """
    Simula perda e atraso variável para pacotes e ACKs.
    """

    def __init__(self, loss_data=0.15, loss_ack=0.15, delay_range=(0.05, 0.5)):
        """
        Args:
            loss_data (float): Probabilidade de perda de pacotes DATA.
            loss_ack (float): Probabilidade de perda de ACKs.
            delay_range (tuple): Intervalo (s) de atraso para os pacotes.
        """
        self.loss_data = loss_data
        self.loss_ack = loss_ack
        self.delay_range = delay_range

    def send(self, pkt: bytes, sock: socket.socket, addr: Tuple[str, int]):
        """
        Envia pacotes com simulação de perda e atraso.
        Identifica DATA/ACK pelo tipo no pacote.

        Args:
            pkt (bytes): Pacote pronto para envio.
            sock (socket.socket): Socket UDP para envio.
            addr (tuple): Endereço destino (host, porto).
        """
        info = parse_packet(pkt)
        if info is None:
            return

        ptype = info['type']

        # Decide se o pacote será perdido
        if ptype == TYPE_DATA and random.random() < self.loss_data:
            print("[CHANNEL] Perda simulada de pacote DATA")
            return  # pacote perdido

        if ptype == TYPE_ACK and random.random() < self.loss_ack:
            print("[CHANNEL] Perda simulada de ACK")
            return  # ACK perdido

        # Simula atraso variável
        delay = random.uniform(*self.delay_range)

        def delayed_send():
            sock.sendto(pkt, addr)
            print(f"[CHANNEL] Pacote tipo {ptype} enviado após delay {delay:.3f}s")

        threading.Timer(delay, delayed_send).start()


class RDT30Sender:
    """
    Implementa o remetente rdt3.0 com timer e simulação de perda/atraso.
    """

    def __init__(
        self,
        local_addr=('localhost', 0),
        dest_addr=('localhost', 10000),
        channel: Optional[UnreliableChannel] = None,
        timeout=2.0,
        verbose=True,
    ):
        """
        Inicializa socket, timer e configura canal simulado.

        Args:
            local_addr (tuple): Endereço local para bind do socket.
            dest_addr (tuple): Endereço destino dos pacotes.
            channel (UnreliableChannel, opcional): Canal para simular perda e atraso.
            timeout (float): Tempo de timeout (s) para retransmissão.
            verbose (bool): Ativa mensagens de log.
        """
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
        self.timer = None
        self.running = True
        self.start_time = None
        self.bytes_sent = 0

        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """
        Envia dados garantindo confiabilidade via timer e retransmissões.

        Args:
            data (bytes): Dados a transmitir.
        """
        with self.lock:
            pkt = make_packet(TYPE_DATA, self.seq, data)
            self.last_packet = pkt
            self._send_packet(pkt)
            self.bytes_sent += len(data)
            self._start_timer()
            self.waiting_for_ack.clear()

            if self.start_time is None:
                self.start_time = time.time()

        while True:
            got_ack = self.waiting_for_ack.wait(timeout=self.timeout)
            if got_ack:
                self._stop_timer()
                self.seq = 1 - self.seq
                return
            else:
                self.retransmissions += 1
                if self.verbose:
                    print(f"[SENDER] Timeout, retransmit seq {self.seq}")
                with self.lock:
                    self._send_packet(self.last_packet)
                    self._start_timer()

    def _send_packet(self, pkt: bytes):
        """
        Envia o pacote via canal simulado ou socket direto.

        Args:
            pkt (bytes): Pacote a enviar.
        """
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)
        if self.verbose:
            info = parse_packet(pkt)
            print(f"[SENDER] Enviou pacote seq={info['seq']} len={len(pkt)}")

    def _start_timer(self):
        """Inicia o timer para retransmissão."""
        self._stop_timer()
        self.timer = threading.Timer(self.timeout, self._on_timeout)
        self.timer.start()

    def _stop_timer(self):
        """Para o timer se ativo."""
        if self.timer:
            try:
                self.timer.cancel()
            except Exception:
                pass
            self.timer = None

    def _on_timeout(self):
        """Callback chamado no timeout, força retransmissão."""
        self.waiting_for_ack.clear()

    def _recv_loop(self):
        """Recebe pacotes ACK e verifica integridade e sequência."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            if (
                info['type'] == TYPE_ACK
                and not info['corrupt']
                and info['seq'] == self.seq
            ):
                if self.verbose:
                    print(f"[SENDER] Recebeu ACK seq {info['seq']}")
                with self.lock:
                    self._stop_timer()
                    self.waiting_for_ack.set()
            else:
                if self.verbose:
                    print(
                        "[SENDER] Ignorado pacote (type, corrupt, seq)=",
                        info['type'],
                        info['corrupt'],
                        info['seq'],
                    )

    def close(self):
        """Fecha o socket e para o remetente."""
        self.running = False
        self._stop_timer()
        try:
            self.sock.close()
        except Exception:
            pass

    def get_stats(self) -> Tuple[int, float]:
        """
        Retorna estatísticas do envio.

        Returns:
            tuple: (número de retransmissões, throughput em bytes por segundo)
        """
        elapsed = time.time() - self.start_time if self.start_time else 0.0001
        throughput = self.bytes_sent / elapsed
        return self.retransmissions, throughput


class RDT21Receiver:
    """
    Receptor rdt2.1 (inalterado para rdt3.0).
    """

    def __init__(
        self,
        local_addr=('localhost', 10000),
        deliver_callback: Optional[Callable[[bytes], None]] = None,
        channel: Optional[UnreliableChannel] = None,
        verbose=True,
    ):
        """
        Configura socket e parâmetros.

        Args:
            local_addr (tuple): Endereço local para bind.
            deliver_callback (callable, opcional): Função para entrega dos dados.
            channel (UnreliableChannel, opcional): Canal para simulação.
            verbose (bool): Para logs detalhados.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(local_addr)
        self.channel = channel
        self.expected = 0
        self.deliver_callback = deliver_callback or (lambda b: None)
        self.running = True
        self.verbose = verbose
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_ack(self, seq: int, addr: Tuple[str, int]):
        """Envia ACK dado um número de sequência."""
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print(f"[RECV] Enviou ACK {seq}")

    def _recv_loop(self):
        """Loop para receber pacotes DATA, entregá-los e enviar ACKs."""
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
                        print(f"[RECV] Recebeu seq esperado {info['seq']} len={len(info['payload'])}")
                    self.deliver_callback(info['payload'])
                    self._send_ack(self.expected, addr)
                    self.expected = 1 - self.expected
                else:
                    # Pacote duplicado ou corrompido: re-ACK último correto
                    if self.verbose:
                        print(f"[RECV] Pacote duplicado/corrompido seq {info['seq']} -> re-ACK {1 - self.expected}")
                    self._send_ack(1 - self.expected, addr)

    def close(self):
        """Encerra receptor e fecha socket."""
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="rdt3.0 protocol with timer and loss simulation")
    parser.add_argument("role", choices=["sender", "receiver"], help="Função para executar: sender ou receiver")
    parser.add_argument("--local-host", default="localhost", help="Host local")
    parser.add_argument("--local-port", type=int, default=0, help="Porta local (0 para aleatória no sender, 10000 padrão receiver)")
    parser.add_argument("--dest-host", default="localhost", help="Host destino para sender")
    parser.add_argument("--dest-port", type=int, default=10000, help="Porta destino para sender")
    parser.add_argument("--verbose", action="store_true", help="Ativa logs detalhados")

    args = parser.parse_args()

    channel = UnreliableChannel(loss_data=0.15, loss_ack=0.15, delay_range=(0.05, 0.5))

    if args.role == "receiver":
        def deliver(data: bytes):
            print(f"[RECEIVER] Mensagem recebida: {data.decode(errors='replace')}")

        local_port = args.local_port if args.local_port != 0 else 10000

        receiver = RDT21Receiver(
            local_addr=(args.local_host, local_port),
            deliver_callback=deliver,
            channel=channel,
            verbose=args.verbose
        )
        print(f"Receptor rodando em {args.local_host}:{local_port} (Ctrl+C para sair)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            receiver.close()
            print("Receptor finalizado.")

    elif args.role == "sender":
        sender = RDT30Sender(
            local_addr=(args.local_host, args.local_port),
            dest_addr=(args.dest_host, args.dest_port),
            channel=channel,
            verbose=args.verbose,
        )

        messages = [f"Mensagem {i}" for i in range(10)]

        for msg in messages:
            print(f"[SENDER] Enviando: {msg}")
            sender.send(msg.encode())
            time.sleep(0.1)

        sender.close()
        print("Remetente finalizado.")


if __name__ == "__main__":
    main()
