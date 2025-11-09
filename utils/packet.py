"""
Módulo de utilitários de pacotes para protocolos confiáveis.

Fornece funções para criar, parsear e validar pacotes com checksum de 32 bits.
Inclui tipos de pacote DATA, ACK e NAK.
"""

import struct
import hashlib

# Tipos de pacote
TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NAK = 2


def checksum32(data: bytes) -> int:
    """
    Calcula um checksum de 32 bits usando MD5 truncado.

    O checksum é usado para detectar corrupção de pacotes.

    Args:
        data (bytes): Dados sobre os quais calcular o checksum.

    Returns:
        int: Valor do checksum de 32 bits.
    """
    h = hashlib.md5(data).digest()
    return struct.unpack('!I', h[:4])[0]


def make_packet(pkt_type: int, seqnum: int, payload: bytes) -> bytes:
    """
    Monta um pacote no formato [type|seq|checksum|payload].

    Args:
        pkt_type (int): Tipo do pacote (TYPE_DATA, TYPE_ACK, TYPE_NAK).
        seqnum (int): Número de sequência do pacote.
        payload (bytes): Dados a enviar. Se None, usa bytes vazios.

    Returns:
        bytes: Pacote completo pronto para envio.
    """
    if payload is None:
        payload = b''

    # Cabeçalho temporário com checksum zero
    header = struct.pack('!BBI', pkt_type, seqnum, 0)

    # Calcula checksum sobre cabeçalho + payload
    chksum = checksum32(header + payload)

    # Cabeçalho final com checksum correto
    header = struct.pack('!BBI', pkt_type, seqnum, chksum)

    # Retorna pacote completo
    return header + payload


def parse_packet(packet: bytes):
    """
    Desmonta um pacote recebido e verifica sua integridade via checksum.

    Args:
        packet (bytes): Pacote recebido.

    Returns:
        dict ou None: Dicionário com informações do pacote:
            - 'type': tipo do pacote
            - 'seq': número de sequência
            - 'checksum': checksum recebido
            - 'payload': dados do pacote
            - 'corrupt': True se o pacote estiver corrompido
        Retorna None se o pacote for muito curto.
    """
    if len(packet) < 6:
        return None

    pkt_type, seqnum, chksum = struct.unpack('!BBI', packet[:6])
    payload = packet[6:]

    # Recalcula checksum para detectar corrupção
    calc = checksum32(struct.pack('!BBI', pkt_type, seqnum, 0) + payload)
    corrupt = (calc != chksum)

    return {
        'type': pkt_type,
        'seq': seqnum,
        'checksum': chksum,
        'payload': payload,
        'corrupt': corrupt
    }


def extract(pkt_bytes):
    """
    Compatibilidade com formato antigo.

    Args:
        pkt_bytes (bytes): Pacote em bytes.

    Returns:
        dict: Resultado de parse_packet.
    """
    return parse_packet(pkt_bytes)


def is_corrupt(pkt):
    """
    Verifica se um pacote está corrompido.

    Args:
        pkt (dict): Dicionário do pacote parseado.

    Returns:
        bool: True se o pacote estiver corrompido ou inválido.
    """
    return pkt.get('corrupt', True)
