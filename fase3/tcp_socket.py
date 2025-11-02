import socket
import threading
import time
import struct
import random


class TCPSocket:
    """
    Implementação simples de socket TCP sobre UDP, com controle de conexão,
    envio, recepção e finalização usando segmentos com flags TCP.
    """

    def __init__(self, local_addr=("127.0.0.1", 0), recv_window=4096):
        """
        Inicializa socket UDP e variáveis do protocolo.

        Args:
            local_addr (tuple): Endereço local para bind.
            recv_window (int): Tamanho da janela de recepção.
        """
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(local_addr)
        self.remote_addr = None
        self.seq = random.randint(0, 65535)
        self.ack = 0
        self.recv_window = recv_window
        self.send_buffer = {}
        self.recv_buffer = bytearray()
        self.estimated_rtt = 1.0
        self.dev_rtt = 0.5
        self.timeout_interval = 1.5
        self.running = False
        self.connected = False
        self.fin_sent = False
        self.fin_acked = False
        self.fin_received = False
        self.thread = None
        self.lock = threading.Lock()

    def connect(self, remote_addr):
        """
        Estabelece conexão TCP com o servidor usando handshake de 3 vias.

        Args:
            remote_addr (tuple): Endereço do servidor.
        """
        print("DEBUG: CLIENT connect() INICIADO")
        self.remote_addr = remote_addr
        syn_segment = self._pack_segment("SYN", self.seq, self.ack, self.recv_window, b"")
        self.udp.sendto(syn_segment, remote_addr)
        print("DEBUG: CLIENT connect() SYN enviado para", remote_addr)
        while True:
            data, _ = self.udp.recvfrom(1024)
            header = self._unpack_segment(data)
            print("DEBUG: CLIENT connect() recebeu header:", header)
            if header["flags"] == "SYN-ACK":
                self.ack = header["seq"] + 1
                break
        ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
        self.udp.sendto(ack_segment, remote_addr)
        self.connected = True

        # ===== ALTERAÇÃO CRUCIAL aqui! =====
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        # ===================================

        print("DEBUG: CLIENT connect() finalizou. connected =", self.connected)

    def accept(self):
        """
        Aceita conexão TCP do cliente com handshake 3 vias.
        """
        print("DEBUG: SERVER accept() INICIADO")
        while True:
            data, addr = self.udp.recvfrom(1024)
            header = self._unpack_segment(data)
            print("DEBUG: SERVER accept() recebeu pacote, header:", header)
            if header["flags"] == "SYN":
                self.remote_addr = addr
                self.ack = header["seq"] + 1
                synack = self._pack_segment(
                    "SYN-ACK", self.seq, self.ack, self.recv_window, b""
                )
                self.udp.sendto(synack, addr)
                data, _ = self.udp.recvfrom(1024)
                header = self._unpack_segment(data)
                print("DEBUG: SERVER accept() aguardando ACK, recebeu header:", header)
                if header["flags"] == "ACK":
                    self.connected = True

                    # ===== ALTERAÇÃO CRUCIAL aqui! =====
                    self.running = True
                    self.thread = threading.Thread(target=self._receive_loop, daemon=True)
                    self.thread.start()
                    # ===================================

                    print("DEBUG: SERVER accept() finalizou. connected =", self.connected)
                    break

    def send(self, data: bytes):
        """
        Envia dados usando segmentos TCP com flag PSH.

        Args:
            data (bytes): Dados a enviar.
        """
        print("DEBUG SEND: self.connected =", self.connected)
        if not self.connected:
            raise ConnectionError("Socket não está conectado.")
        with self.lock:
            chunk = data[: self.recv_window]
            segment = self._pack_segment(
                "PSH", self.seq, self.ack, self.recv_window, chunk
            )
            self.udp.sendto(segment, self.remote_addr)
            self.send_buffer[self.seq] = {
                "segment": segment,
                "time": time.time(),
                "data": chunk,
            }
            self.seq += len(chunk)
        self._start_timer()

    def recv(self, bufsize=4096):
        """
        Recebe os dados da conexão TCP do cliente/servidor.

        Args:
            bufsize (int): Tamanho máximo do buffer para receber dados.

        Returns:
            bytes: Dados recebidos.
        """
        while not self.recv_buffer:
            time.sleep(0.01)
        with self.lock:
            data = bytes(self.recv_buffer[:bufsize])
            del self.recv_buffer[:bufsize]
            return data

    def close(self):
        """
        Encerra a conexão TCP enviando FIN, aguardando confirmação e encerrando o socket.
        """
        if not self.connected:
            self.udp.close()
            return
        if not self.fin_sent:
            fin_segment = self._pack_segment("FIN", self.seq, self.ack, self.recv_window, b"")
            self.udp.sendto(fin_segment, self.remote_addr)
            self.fin_sent = True
            print("🔚 FIN enviado.")
        start = time.time()
        while time.time() - start < 5:
            if self.fin_acked and self.fin_received:
                break
            time.sleep(0.05)
        if self.fin_received and not self.fin_acked:
            ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
            self.udp.sendto(ack_segment, self.remote_addr)
            print("🔚 ACK final enviado.")
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.connected = False
        self.udp.close()
        print("✅ Conexão encerrada.")

    def _receive_loop(self):
        """
        Loop de recepção que processa os segmentos TCP recebidos.
        """
        while self.running:
            try:
                data, _ = self.udp.recvfrom(65536)
            except OSError:
                return
            header = self._unpack_segment(data)
            flag = header["flags"]
            if flag == "ACK":
                self._handle_ack(header)
            elif flag == "PSH":
                with self.lock:
                    self.recv_buffer.extend(header["data"])
                self.ack = header["seq"] + len(header["data"])
                ack_segment = self._pack_segment(
                    "ACK", self.seq, self.ack, self.recv_window, b""
                )
                self.udp.sendto(ack_segment, self.remote_addr)
            elif flag == "FIN":
                self.fin_received = True
                ack_segment = self._pack_segment(
                    "ACK", self.seq, self.ack, self.recv_window, b""
                )
                self.udp.sendto(ack_segment, self.remote_addr)
                print("🔚 FIN recebido.")
                if not self.fin_sent:
                    fin_segment = self._pack_segment(
                        "FIN", self.seq, self.ack, self.recv_window, b""
                    )
                    self.udp.sendto(fin_segment, self.remote_addr)
                    self.fin_sent = True
                    print("🔚 FIN enviado (lado passivo).")
            elif flag == "SYN" or flag == "SYN-ACK":
                # Não processado no loop de recepção
                pass

    def _handle_ack(self, header):
        """
        Processa ACK recebido, atualiza buffer e calcula RTT.

        Args:
            header (dict): Cabeçalho do segmento ACK.
        """
        ack_num = header["ack"]
        with self.lock:
            to_remove = [seq for seq in self.send_buffer if seq < ack_num]
            for seq in to_remove:
                sample_rtt = time.time() - self.send_buffer[seq]["time"]
                self._update_rtt(sample_rtt)
                del self.send_buffer[seq]
        if header["flags"] == "ACK" and header.get("fin_ack"):
            self.fin_acked = True

    def _start_timer(self):
        """
        Inicia thread para checagem de timeout e retransmissão.
        """
        threading.Thread(target=self._check_timeout, daemon=True).start()

    def _check_timeout(self):
        """
        Verifica timeout dos pacotes em buffer e retransmite se necessário.
        """
        time.sleep(self.timeout_interval)
        now = time.time()
        with self.lock:
            for seq, info in list(self.send_buffer.items()):
                if now - info["time"] > self.timeout_interval:
                    print(f"⏳ Timeout: retransmitindo seq={seq}")
                    self.udp.sendto(info["segment"], self.remote_addr)
                    self.send_buffer[seq]["time"] = now

    def _update_rtt(self, sample_rtt):
        """
        Atualiza estimativas de RTT e intervalo de timeout.

        Args:
            sample_rtt (float): Amostra de RTT para atualização.
        """
        self.estimated_rtt = 0.875 * self.estimated_rtt + 0.125 * sample_rtt
        self.dev_rtt = 0.75 * self.dev_rtt + 0.25 * abs(sample_rtt - self.estimated_rtt)
        self.timeout_interval = self.estimated_rtt + 4 * self.dev_rtt

    def _pack_segment(self, flags, seq, ack, window, data=b""):
        """
        Monta um segmento TCP com campos de cabeçalho e dados.

        Args:
            flags (str): Flags TCP (ex: "SYN", "ACK", "FIN", "PSH").
            seq (int): Número de sequência.
            ack (int): Número de ACK esperado.
            window (int): Tamanho da janela de recepção.
            data (bytes): Dados do segmento.

        Returns:
            bytes: Segmento com cabeçalho e dados.
        """
        flag_bits = 0
        if "FIN" in flags:
            flag_bits |= 0x01
        if "SYN" in flags:
            flag_bits |= 0x02
        if "ACK" in flags:
            flag_bits |= 0x10
        offset_flags = (5 << 12) | flag_bits
        header = struct.pack(
            "!HHIIHHHH",
            self.udp.getsockname()[1],
            self.remote_addr[1] if self.remote_addr else 0,
            seq,
            ack,
            offset_flags,
            window,
            0,
            0,
        )
        return header + data

    def _unpack_segment(self, segment):
        """
        Desmonta segmento em campos do cabeçalho e dados.

        Args:
            segment (bytes): Segmento recebido.

        Returns:
            dict: Dicionário com campos de cabeçalho e dados.
        """
        header = segment[:20]
        data = segment[20:]
        (
            src_port,
            dst_port,
            seq,
            ack,
            offset_flags,
            window,
            checksum,
            urg_ptr,
        ) = struct.unpack("!HHIIHHHH", header)
        flags = ""
        if offset_flags & 0x01:
            flags = "FIN"
        elif offset_flags & 0x02:
            flags = "SYN"
        elif offset_flags & 0x10:
            flags = "ACK"
        elif offset_flags & 0x12:
            flags = "SYN-ACK"
        elif offset_flags & 0x08:
            flags = "PSH"
        return {
            "src_port": src_port,
            "dst_port": dst_port,
            "seq": seq,
            "ack": ack,
            "flags": flags,
            "window": window,
            "data": data,
        }
