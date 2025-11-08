import socket
import threading
import time
import struct
import random


class TCPSocket:
    """
    Implementação simplificada de TCP sobre UDP.
    Suporta:
        - Three-way handshake
        - Envio e recepção confiável
        - Controle de fluxo
        - Four-way handshake
    """

    def __init__(self, local_addr=("127.0.0.1", 0), recv_window=4096):
        """
        Inicializa o socket TCP simplificado.
        
        Args:
            local_addr (tuple): Endereço local (host, port) para bind.
            recv_window (int): Tamanho da janela de recepção.
        """
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp.bind(local_addr)

        self.remote_addr = None
        self.seq = random.randint(0, 65535)  # Número de sequência inicial aleatório
        self.ack = 0
        self.recv_window = recv_window

        # Buffers de envio e recepção
        self.send_buffer = {}  # seq_base -> {segment, time, data}
        self.recv_buffer = bytearray()

        # RTT adaptativo
        self.estimated_rtt = 0.3
        self.dev_rtt = 0.15
        self.timeout_interval = 1.0

        # Estado da conexão
        self.running = False
        self.connected = False
        self.fin_sent = False
        self.fin_acked = False
        self.fin_received = False

        # Concorrência
        self.lock = threading.Lock()
        self.thread = None

        # Timer único para retransmissão
        self._timer_running = False
        self._timer_lock = threading.Lock()
        self._timer_thread = None

    # ============================================================
    # ESTABELECIMENTO DE CONEXÃO
    # ============================================================

    def connect(self, remote_addr):
        """
        Cliente inicia conexão (three-way handshake).
        
        Args:
            remote_addr (tuple): Endereço remoto (host, port) para conectar.
        """
        self.remote_addr = remote_addr
        syn = self._pack_segment("SYN", self.seq, 0, self.recv_window, b"")
        attempts = 0
        start = time.time()

        while True:
            # Envia SYN
            try:
                self.udp.sendto(syn, remote_addr)
            except Exception:
                pass

            # Recebe SYN-ACK
            try:
                self.udp.settimeout(1.0)
                data, addr = self.udp.recvfrom(65536)
                header = self._unpack_segment(data)
                if header["flags"] == "SYN-ACK":
                    self.ack = header["seq"] + 1
                    break
            except socket.timeout:
                attempts += 1
                if attempts >= 8 or time.time() - start > 12.0:
                    raise TimeoutError("❌ Falha ao conectar (sem resposta SYN-ACK).")

        # Envia ACK final
        ack = self._pack_segment("ACK", self.seq + 1, self.ack, self.recv_window, b"")
        try:
            self.udp.sendto(ack, remote_addr)
        except Exception:
            pass

        self.seq += 1
        self.connected = True
        self.running = True

        # Inicia thread de recepção
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        time.sleep(0.01)  # Pequena pausa para sincronização

        print("✅ CLIENTE conectado com sucesso!")

    def accept(self):
        """
        Servidor aceita conexão (three-way handshake).
        Bloqueante até receber conexão.
        """
        while True:
            data, addr = self.udp.recvfrom(65536)
            header = self._unpack_segment(data)

            if header["flags"] == "SYN":
                self.remote_addr = addr
                self.ack = header["seq"] + 1
                synack = self._pack_segment("SYN-ACK", self.seq, self.ack, self.recv_window, b"")
                self.udp.sendto(synack, addr)

                # Espera ACK final
                try:
                    self.udp.settimeout(3.0)
                    data2, addr2 = self.udp.recvfrom(65536)
                    hdr = self._unpack_segment(data2)
                    if hdr["flags"] == "ACK" and hdr["ack"] == self.seq + 1:
                        self.seq += 1
                        self.connected = True
                        self.running = True
                        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
                        self.thread.start()
                        print("✅ SERVIDOR conectado com sucesso!")
                        return
                except socket.timeout:
                    continue

    # ============================================================
    # ENVIO E RECEPÇÃO DE DADOS
    # ============================================================

    def send(self, data: bytes):
        """
        Envia dados em múltiplos segmentos com controle de fluxo simplificado.

        Args:
            data (bytes): Dados a serem enviados.
        """
        if not self.connected:
            raise ConnectionError("Socket não está conectado.")

        send_window_max = self.recv_window * 8
        offset = 0

        while offset < len(data):
            # Aguarda se a janela de envio estiver cheia
            while len(self.send_buffer) * self.recv_window >= send_window_max:
                time.sleep(0.005)

            chunk = data[offset:offset + self.recv_window]
            with self.lock:
                seq_base = self.seq
                segment = self._pack_segment("PSH", seq_base, self.ack, self.recv_window, chunk)

                try:
                    self.udp.sendto(segment, self.remote_addr)
                except Exception:
                    pass

                # Registra pacote no buffer
                self.send_buffer[seq_base] = {"segment": segment, "time": time.time(), "data": chunk}
                self.seq += len(chunk)

            # Inicia timer único
            self._start_timer()
            offset += len(chunk)
            time.sleep(0.001)

    def recv(self, bufsize=4096):
        """
        Recebe dados do buffer. Bloqueante até haver dados disponíveis.

        Args:
            bufsize (int): Quantidade máxima de bytes a receber.

        Returns:
            bytes: Dados recebidos.
        """
        while True:
            with self.lock:
                if len(self.recv_buffer) > 0:
                    data = bytes(self.recv_buffer[:bufsize])
                    del self.recv_buffer[:bufsize]
                    return data
            if not self.running and not self.connected:
                return b""
            time.sleep(0.01)

    # ============================================================
    # ENCERRAMENTO DE CONEXÃO
    # ============================================================

    def close(self):
        """
        Fecha a conexão (four-way handshake).
        """
        if not self.connected:
            try:
                self.udp.close()
            except Exception:
                pass
            return

        # Aguarda envio completo antes do FIN
        wait_start = time.time()
        while self.send_buffer and (time.time() - wait_start) < 15.0:
            time.sleep(0.02)

        if not self.fin_sent:
            fin = self._pack_segment("FIN", self.seq, self.ack, self.recv_window, b"")
            if self.remote_addr:
                try:
                    self.udp.sendto(fin, self.remote_addr)
                except Exception:
                    pass
            self.fin_sent = True
            print("🔚 FIN enviado.")

        # Aguarda ACK do FIN
        start = time.time()
        while time.time() - start < 2.0:
            if self.fin_received and self.fin_acked:
                break
            time.sleep(0.05)

        # Envia ACK final se necessário
        if self.fin_received and not self.fin_acked:
            ack = self._pack_segment("ACK", self.seq + 1, self.ack, self.recv_window, b"")
            if self.remote_addr:
                try:
                    self.udp.sendto(ack, self.remote_addr)
                except Exception:
                    pass
            self.fin_acked = True
            print("🔚 ACK final enviado.")

        # Encerra threads e socket
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.1)
        self.connected = False
        try:
            self.udp.close()
        except Exception:
            pass
        print("✅ Conexão encerrada.")

    # ============================================================
    # LOOP DE RECEPÇÃO
    # ============================================================

    def _receive_loop(self):
        """
        Thread que processa pacotes recebidos, envia ACKs e trata FIN.
        """
        while self.running:
            try:
                data, addr = self.udp.recvfrom(65536)
            except OSError:
                return
            except Exception:
                return

            header = self._unpack_segment(data)
            flag = header["flags"]

            if self.remote_addr is None:
                self.remote_addr = addr

            if flag == "ACK":
                self._handle_ack(header)

            elif flag == "PSH":
                # Processa pacote esperado
                with self.lock:
                    if header["seq"] == self.ack:
                        self.recv_buffer.extend(header["data"])
                        self.ack += len(header["data"])

                # Envia ACK imediato
                ack_segment = self._pack_segment("ACK", self.seq, self.ack, self.recv_window, b"")
                try:
                    self.udp.sendto(ack_segment, addr)
                except Exception:
                    pass

            elif flag == "FIN":
                self.fin_received = True
                # Envia ACK do FIN
                ack_segment = self._pack_segment("ACK", self.seq, self.ack + 1, self.recv_window, b"")
                try:
                    self.udp.sendto(ack_segment, addr)
                except Exception:
                    pass
                print("🔚 FIN recebido.")

                # Envia FIN de volta se lado passivo
                if not self.fin_sent:
                    fin_segment = self._pack_segment("FIN", self.seq, self.ack + 1, self.recv_window, b"")
                    try:
                        self.udp.sendto(fin_segment, addr)
                    except Exception:
                        pass
                    self.fin_sent = True
                    print("🔚 FIN enviado (lado passivo).")

    # ============================================================
    # ACKS, TIMEOUT E RTT
    # ============================================================

    def _handle_ack(self, header):
        """
        Processa ACK recebido e remove pacotes confirmados do buffer.

        Args:
            header (dict): Segmento recebido.
        """
        ack_num = header["ack"]
        with self.lock:
            oldest_seq_before = min(self.send_buffer.keys()) if self.send_buffer else None
            confirmed = [seq for seq, info in self.send_buffer.items()
                         if seq + len(info["data"]) <= ack_num]

            for seq in confirmed:
                if seq == oldest_seq_before:
                    sample_rtt = time.time() - self.send_buffer[seq]["time"]
                    self._update_rtt(sample_rtt)
                del self.send_buffer[seq]
                print(f"DEBUG ACK: Pacote {seq} confirmado e removido.")

            # Reinicia timer se necessário
            if not self.send_buffer:
                with self._timer_lock:
                    self._timer_running = False
                    print("DEBUG ACK: Buffer vazio. Timer parado.")

        if self.send_buffer:
            self.timeout_interval = max(0.1, min(self.estimated_rtt + 4 * self.dev_rtt, 3.0))
            self._start_timer()

    def _start_timer(self):
        """Inicia a thread de timer de retransmissão se não estiver ativa."""
        with self._timer_lock:
            if self._timer_running:
                return
            self._timer_running = True

        def timer_loop():
            while self.running and self.connected and self._timer_running:
                time.sleep(0.05)
                now = time.time()
                resend_list = []

                with self.lock:
                    if self.send_buffer:
                        oldest_seq = min(self.send_buffer.keys())
                        info = self.send_buffer[oldest_seq]
                        current_timeout = self.timeout_interval
                        if now - info["time"] > current_timeout:
                            resend_list.append((oldest_seq, info))

                for seq, info in resend_list:
                    try:
                        print(f"⏳ Timeout: retransmitindo seq={seq} (Timeout: {current_timeout:.3f}s)")
                        self.udp.sendto(info["segment"], self.remote_addr)
                        with self.lock:
                            if seq in self.send_buffer:
                                self.send_buffer[seq]["time"] = time.time()
                        time.sleep(0.01)
                    except OSError:
                        continue

                with self.lock:
                    if not self.send_buffer:
                        break

            with self._timer_lock:
                self._timer_running = False

        self._timer_thread = threading.Thread(target=timer_loop, daemon=True)
        self._timer_thread.start()

    def _update_rtt(self, sample_rtt):
        """
        Atualiza o RTT estimado e o desvio.

        Args:
            sample_rtt (float): RTT medido para o pacote.
        """
        if sample_rtt <= 0:
            return

        alpha = 0.125
        beta = 0.25

        if self.estimated_rtt == 0.3:
            self.estimated_rtt = sample_rtt
            self.dev_rtt = sample_rtt / 2
        else:
            self.estimated_rtt = (1 - alpha) * self.estimated_rtt + alpha * sample_rtt
            self.dev_rtt = (1 - beta) * self.dev_rtt + beta * abs(sample_rtt - self.estimated_rtt)

        self.timeout_interval = max(0.1, min(self.estimated_rtt + 4 * self.dev_rtt, 3.0))

    # ============================================================
    # EMPACOTAMENTO / DESEMPACOTAMENTO
    # ============================================================

    def _pack_segment(self, flags, seq, ack, window, data=b""):
        """
        Cria um segmento TCP simplificado.

        Args:
            flags (str): Bandeira do segmento ('SYN', 'ACK', 'PSH', 'FIN', etc.)
            seq (int): Número de sequência.
            ack (int): Número de confirmação.
            window (int): Tamanho da janela.
            data (bytes): Dados do segmento.

        Returns:
            bytes: Segmento empacotado.
        """
        flag_bits = 0
        if "FIN" in flags:
            flag_bits |= 0x01
        if "SYN" in flags:
            flag_bits |= 0x02
        if "ACK" in flags:
            flag_bits |= 0x10
        if "SYN-ACK" in flags:
            flag_bits |= 0x12
        if "PSH" in flags:
            flag_bits |= 0x08

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
        Desempacota um segmento recebido.

        Args:
            segment (bytes): Segmento recebido.

        Returns:
            dict: Informações do segmento.
        """
        header = segment[:20]
        data = segment[20:]
        src_port, dst_port, seq, ack, offset_flags, window, _, _ = struct.unpack("!HHIIHHHH", header)
        flags = ""
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
        return {
            "src_port": src_port,
            "dst_port": dst_port,
            "seq": seq,
            "ack": ack,
            "flags": flags,
            "window": window,
            "data": data,
        }
