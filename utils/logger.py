"""
Sistema simples de logging para eventos com timestamp relativo,
armazena logs em CSV e imprime no console.
"""

import csv
import time


class Logger:
    """
    Classe para registrar eventos com timestamps relativos e salvar em CSV.
    """

    def __init__(self, filename="logs.csv"):
        """
        Inicializa o logger, prepara arquivo de log CSV e marca tempo inicial.

        Args:
            filename (str): Nome do arquivo para salvar logs.
        """
        self.filename = filename
        self.start_time = time.time()
        with open(self.filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'event', 'info'])

    def log(self, event, info=""):
        """
        Registra um evento no arquivo CSV e imprime no console.

        Args:
            event (str): Nome ou tipo do evento.
            info (str, opcional): Informação adicional do evento.
        """
        t = round(time.time() - self.start_time, 3)
        with open(self.filename, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([t, event, info])
        print(f"[LOG {t}s] {event}: {info}")
