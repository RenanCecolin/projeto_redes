import struct
import hashlib

# Tipos de pacote usados no protocolo
TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NAK = 2

def checksum32(data: bytes) -> int:
    """
    Calcula um checksum de 32 bits a partir do hash MD5 truncado.

    Args:
        data (bytes): Dados para calcular checksum.

    Returns:
        int: Valor do checksum de 32 bits.
    """
    h = hashlib.md5(data).digest()
    return struct.unpack('!I', h[:4])[0]

def make_packet(pkt_type: int, seqnum: int, payload: bytes) -> bytes:
    """
    Cria um pacote no formato [type|seq|checksum|payload].

    Args:
        pkt_type (int): Tipo do pacote (DATA, ACK, NAK).
        seqnum (int): Número de sequência do pacote.
        payload (bytes): Dados a serem enviados no pacote.

    Returns:
        bytes: Pacote montado pronto para envio.
    """
    if payload is None:
        payload = b''

    # Monta cabeçalho temporário com checksum zero para calcular o checksum real
    header = struct.pack('!BBI', pkt_type, seqnum, 0)

    # Calcula checksum sobre o cabeçalho e payload
    chksum = checksum32(header + payload)

    # Novo cabeçalho com checksum correto
    header = struct.pack('!BBI', pkt_type, seqnum, chksum)

    # Retorna pacote completo (cabeçalho + payload)
    return header + payload

def parse_packet(packet: bytes):
    """
    Desmonta um pacote recebido e verifica sua integridade.

    Args:
        packet (bytes): Pacote recebido.

    Returns:
        dict ou None: Dicionário com informações do pacote ou None se inválido.
    """
    if len(packet) < 6:
        return None

    pkt_type, seqnum, chksum = struct.unpack('!BBI', packet[:6])
    payload = packet[6:]

    # Recalcula checksum para verificar corrupção
    calc = checksum32(struct.pack('!BBI', pkt_type, seqnum, 0) + payload)
    corrupt = (calc != chksum)

    return {
        'type': pkt_type,
        'seq': seqnum,
        'checksum': chksum,
        'payload': payload,
        'corrupt': corrupt
    }
