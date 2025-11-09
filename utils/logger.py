"""
Sistema simples de logging para eventos com timestamp relativo.
Permite salvar logs em CSV e imprimir no console.
"""

import csv
import time


class Logger:
    """
    Classe para registrar eventos com timestamps relativos e salvar em CSV.

    Funcionalidades:
    - Armazenar logs com timestamp relativo (tempo desde a criação do logger).
    - Salvar logs em arquivo CSV.
    - Imprimir logs no console.
    """

    def __init__(self, filename="logs.csv"):
        """
        Inicializa o logger, cria arquivo CSV e marca o tempo inicial.

        Args:
            filename (str): Nome do arquivo CSV para armazenar os logs.
        """
        self.filename = filename
        self.start_time = time.time()

        # Cria arquivo CSV com cabeçalho
        with open(self.filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'event', 'info'])

    def log(self, event, info=""):
        """
        Registra um evento com timestamp relativo, salva no CSV e imprime no console.

        Args:
            event (str): Nome ou tipo do evento.
            info (str, optional): Informação adicional sobre o evento.
        """
        timestamp = round(time.time() - self.start_time, 3)

        # Escreve no arquivo CSV
        with open(self.filename, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, event, info])

        # Imprime no console
        print(f"[LOG {timestamp}s] {event}: {info}")
