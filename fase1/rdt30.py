"""
rdt30.py
Implementação do rdt3.0: rdt2.1 + timer + perda de pacotes.
Stop-and-Wait com timer, simula perda de 15% dos pacotes DATA e ACKs,
com atraso variável de 50-500 ms.

"""

import socket
import threading
import time
import random
import argparse
from typing import Optional, Tuple, Callable
from utils.packet import *  # make_packet, parse_packet, TYPE_DATA, TYPE_ACK, TYPE_NAK


class UnreliableChannel:
    """
    Canal que simula perda e atraso de pacotes DATA e ACKs.
    """

    def __init__(
        self, loss_data: float = 0.15, loss_ack: float = 0.15, delay_range: Tuple[float, float] = (0.05, 0.5)
    ):
        """
        Inicializa parâmetros do canal.

        Args:
            loss_data (float): Probabilidade de perda de pacotes DATA.
            loss_ack (float): Probabilidade de perda de ACKs.
            delay_range (tuple): Intervalo de atraso (s) para os pacotes.
        """
        self.loss_data = loss_data
        self.loss_ack = loss_ack
        self.delay_range = delay_range

    def send(self, pkt: bytes, sock: socket.socket, addr: Tuple[str, int]):
        """
        Envia pacote simulando perda e atraso.

        Args:
            pkt (bytes): Pacote a enviar.
            sock (socket.socket): Socket UDP.
            addr (tuple): Endereço destino (host, porta).
        """
        info = parse_packet(pkt)
        if info is None:
            return

        ptype = info['type']

        # Simula perda
        if ptype == TYPE_DATA and random.random() < self.loss_data:
            print("[CHANNEL] Pacote DATA perdido")
            return

        if ptype == TYPE_ACK and random.random() < self.loss_ack:
            print("[CHANNEL] ACK perdido")
            return

        # Simula atraso
        delay = random.uniform(*self.delay_range)

        def delayed_send():
            sock.sendto(pkt, addr)
            print(f"[CHANNEL] Pacote tipo {ptype} enviado após delay {delay:.3f}s")

        threading.Timer(delay, delayed_send).start()


class RDT30Sender:
    """
    Remetente rdt3.0 (Stop-and-Wait) com timer e retransmissão automática.
    """

    def __init__(
        self,
        local_addr: Tuple[str, int] = ('localhost', 0),
        dest_addr: Tuple[str, int] = ('localhost', 10000),
        channel: Optional[UnreliableChannel] = None,
        timeout: float = 2.0,
        verbose: bool = True,
    ):
        """
        Inicializa socket, timer e canal.

        Args:
            local_addr (tuple): Endereço local (host, porta).
            dest_addr (tuple): Endereço destino.
            channel (UnreliableChannel, opcional): Canal simulado.
            timeout (float): Timeout para retransmissão (s).
            verbose (bool): Se True, exibe logs detalhados.
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
        self.start_time: Optional[float] = None
        self.bytes_sent = 0

        # Thread para receber ACKs
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data: bytes):
        """
        Envia dados de forma confiável usando timer e retransmissão.

        Args:
            data (bytes): Dados a enviar.
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
        """Envia pacote via canal simulado ou socket direto."""
        if self.channel:
            self.channel.send(pkt, self.sock, self.dest)
        else:
            self.sock.sendto(pkt, self.dest)

        if self.verbose:
            info = parse_packet(pkt)
            print(f"[SENDER] Pacote enviado seq={info['seq']} len={len(pkt)}")

    def _start_timer(self):
        """Inicia o timer para retransmissão."""
        self._stop_timer()
        self.timer = threading.Timer(self.timeout, self._on_timeout)
        self.timer.start()

    def _stop_timer(self):
        """Para o timer, se estiver ativo."""
        if self.timer:
            try:
                self.timer.cancel()
            except Exception:
                pass
            self.timer = None

    def _on_timeout(self):
        """Callback chamado no timeout, sinaliza que ACK não chegou."""
        self.waiting_for_ack.clear()

    def _recv_loop(self):
        """Recebe ACKs e atualiza estado do protocolo."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            info = parse_packet(data)
            if info is None:
                continue
            if info['type'] == TYPE_ACK and not info['corrupt'] and info['seq'] == self.seq:
                if self.verbose:
                    print(f"[SENDER] Recebeu ACK seq {info['seq']}")
                with self.lock:
                    self._stop_timer()
                    self.waiting_for_ack.set()
            else:
                if self.verbose:
                    print(
                        "[SENDER] Pacote ignorado (type, corrupt, seq)=",
                        info['type'], info['corrupt'], info['seq']
                    )

    def close(self):
        """Encerra o remetente e fecha socket."""
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
            tuple: (número de retransmissões, throughput bytes/s)
        """
        elapsed = time.time() - self.start_time if self.start_time else 0.0001
        throughput = self.bytes_sent / elapsed
        return self.retransmissions, throughput


class RDT21Receiver:
    """
    Receptor rdt2.1 adaptado para rdt3.0 (Stop-and-Wait com ACK).
    """

    def __init__(
        self,
        local_addr: Tuple[str, int] = ('localhost', 10000),
        deliver_callback: Optional[Callable[[bytes], None]] = None,
        channel: Optional[UnreliableChannel] = None,
        verbose: bool = True,
    ):
        """
        Inicializa socket, estado e canal.

        Args:
            local_addr (tuple): Endereço local para bind.
            deliver_callback (callable, opcional): Função para entrega dos dados.
            channel (UnreliableChannel, opcional): Canal simulado.
            verbose (bool): Se True, exibe logs detalhados.
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
        """Envia ACK para número de sequência fornecido."""
        pkt = make_packet(TYPE_ACK, seq, b'')
        if self.channel:
            self.channel.send(pkt, self.sock, addr)
        else:
            self.sock.sendto(pkt, addr)
        if self.verbose:
            print(f"[RECV] Enviou ACK {seq}")

    def _recv_loop(self):
        """Recebe pacotes DATA, entrega à aplicação e envia ACKs."""
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
                    # Pacote duplicado ou corrompido, re-ACK último correto
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
    """Função principal para executar sender ou receiver via linha de comando."""
    parser = argparse.ArgumentParser(description="rdt3.0 com timer e simulação de perda")
    parser.add_argument("role", choices=["sender", "receiver"], help="Função: sender ou receiver")
    parser.add_argument("--local-host", default="localhost", help="Host local")
    parser.add_argument("--local-port", type=int, default=0, help="Porta local")
    parser.add_argument("--dest-host", default="localhost", help="Host destino (sender)")
    parser.add_argument("--dest-port", type=int, default=10000, help="Porta destino (sender)")
    parser.add_argument("--verbose", action="store_true", help="Ativa logs detalhados")

    args = parser.parse_args()

    # Cria canal com perda e atraso simulados
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
