import socket
import threading
import time
import struct
import random


class TCPSocket:
    """
    Implementação simplificada de TCP sobre UDP.
    Suporta: three-way handshake, envio/recepção confiável,
    controle de fluxo e encerramento (four-way handshake).
    """

    def __init__(self, local_addr=("127.0.0.1", 0), recv_window=4096):
        """
        Inicializa socket UDP e variáveis do protocolo.
        """
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # ✅ permite reuso da porta
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

    # ============================================================
    # 🔹 ESTABELECIMENTO DE CONEXÃO (THREE-WAY HANDSHAKE)
    # ============================================================

    def connect(self, remote_addr):
        """
        Cliente: inicia conexão com o servidor (three-way handshake).
        """
        print("DEBUG: CLIENT connect() INICIADO")
        self.remote_addr = remote_addr
        syn_segment = self._pack_segment("SYN", self.seq, self.ack, self.recv_window, b"")

        timeout = 1.0
        start = time.time()
        max_wait = 10.0  # tempo máximo para tentar conectar
        attempts = 0

        while True:
            if time.time() - start > timeout:
                attempts += 1
                print(f"⏳ Timeout SYN, retransmitindo (tentativa {attempts})...")
                self.udp.sendto(syn_segment, remote_addr)
                start = time.time()
                if attempts > 5:
                    raise TimeoutError("❌ Falha ao conectar: servidor não respondeu ao SYN-ACK.")

            self.udp.settimeout(0.5)
            try:
                data, _ = self.udp.recvfrom(1024)
                header = self._unpack_segment(data)
                print("DEBUG: CLIENT connect() recebeu header:", header)
                if header["flags"] == "SYN-ACK":
                    self.ack = header["seq"] + 1
                    break
            except socket.timeout:
                continue

        # Envia ACK final
        ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
        self.udp.sendto(ack_segment, remote_addr)
        self.connected = True

        # Inicia thread de recepção
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()

        print("✅ CLIENTE conectado com sucesso!")

    def accept(self):
        """
        Servidor: aceita conexão (three-way handshake).
        """
        print("DEBUG: SERVER accept() INICIADO")
        while True:
            data, addr = self.udp.recvfrom(1024)
            header = self._unpack_segment(data)
            print("DEBUG: SERVER accept() recebeu pacote:", header)

            if header["flags"] == "SYN":
                self.remote_addr = addr
                self.ack = header["seq"] + 1
                # Envia SYN-ACK
                synack = self._pack_segment("SYN-ACK", self.seq, self.ack, self.recv_window, b"")
                self.udp.sendto(synack, addr)
                print("DEBUG: SERVER SYN-ACK enviado para", addr)

                # Espera ACK do cliente
                data, _ = self.udp.recvfrom(1024)
                header = self._unpack_segment(data)
                print("DEBUG: SERVER aguardando ACK, recebeu:", header)
                if header["flags"] == "ACK":
                    self.connected = True

                    self.running = True
                    self.thread = threading.Thread(target=self._receive_loop, daemon=True)
                    self.thread.start()
                    print("✅ SERVIDOR conectado com sucesso!")
                    break

    # ============================================================
    # 🔹 ENVIO E RECEPÇÃO DE DADOS
    # ============================================================

    def send(self, data: bytes):
        """Envia dados em segmentos PSH."""
        if not self.connected:
            raise ConnectionError("Socket não está conectado.")
        with self.lock:
            chunk = data[: self.recv_window]
            segment = self._pack_segment("PSH", self.seq, self.ack, self.recv_window, chunk)
            self.udp.sendto(segment, self.remote_addr)
            self.send_buffer[self.seq] = {
                "segment": segment,
                "time": time.time(),
                "data": chunk,
            }
            self.seq += len(chunk)
        self._start_timer()

    def recv(self, bufsize=4096):
        """Recebe dados do buffer de recepção."""
        while not self.recv_buffer:
            time.sleep(0.01)
        with self.lock:
            data = bytes(self.recv_buffer[:bufsize])
            del self.recv_buffer[:bufsize]
            return data

    # ============================================================
    # 🔹 ENCERRAMENTO DE CONEXÃO (FOUR-WAY HANDSHAKE)
    # ============================================================

    def close(self):
        """Fecha conexão com handshake de 4 vias."""
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

    # ============================================================
    # 🔹 LOOP DE RECEPÇÃO E PROCESSAMENTO
    # ============================================================

    def _receive_loop(self):
        """Thread que processa segmentos recebidos."""
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
                ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
                self.udp.sendto(ack_segment, self.remote_addr)
            elif flag == "FIN":
                self.fin_received = True
                ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
                self.udp.sendto(ack_segment, self.remote_addr)
                print("🔚 FIN recebido.")
                if not self.fin_sent:
                    fin_segment = self._pack_segment("FIN", self.seq, self.ack, self.recv_window, b"")
                    self.udp.sendto(fin_segment, self.remote_addr)
                    self.fin_sent = True
                    print("🔚 FIN enviado (lado passivo).")

    # ============================================================
    # 🔹 GERENCIAMENTO DE TIMEOUT / RTT
    # ============================================================

    def _handle_ack(self, header):
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
        threading.Thread(target=self._check_timeout, daemon=True).start()

    def _check_timeout(self):
        time.sleep(self.timeout_interval)
        now = time.time()
        with self.lock:
            for seq, info in list(self.send_buffer.items()):
                if now - info["time"] > self.timeout_interval:
                    print(f"⏳ Timeout: retransmitindo seq={seq}")
                    self.udp.sendto(info["segment"], self.remote_addr)
                    self.send_buffer[seq]["time"] = now

    def _update_rtt(self, sample_rtt):
        self.estimated_rtt = 0.875 * self.estimated_rtt + 0.125 * sample_rtt
        self.dev_rtt = 0.75 * self.dev_rtt + 0.25 * abs(sample_rtt - self.estimated_rtt)
        self.timeout_interval = self.estimated_rtt + 4 * self.dev_rtt

    # ============================================================
    # 🔹 EMPACOTAMENTO / DESEMPACOTAMENTO DE SEGMENTOS
    # ============================================================

    def _pack_segment(self, flags, seq, ack, window, data=b""):
        flag_bits = 0
        if "FIN" in flags:
            flag_bits |= 0x01
        if "SYN" in flags:
            flag_bits |= 0x02
        if "ACK" in flags:
            flag_bits |= 0x10
        if "SYN-ACK" in flags:
            flag_bits |= 0x12  # ✅ SYN + ACK

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

        if offset_flags & 0x12 == 0x12:
            flags = "SYN-ACK"
        elif offset_flags & 0x02:
            flags = "SYN"
        elif offset_flags & 0x10:
            flags = "ACK"
        elif offset_flags & 0x01:
            flags = "FIN"
        elif offset_flags & 0x08:
            flags = "PSH"
        else:
            flags = ""

        return {
            "src_port": src_port,
            "dst_port": dst_port,
            "seq": seq,
            "ack": ack,
            "flags": flags,
            "window": window,
            "data": data,
        }
