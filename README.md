Como executar os respectivos arquivos utilizando comandos:

1) Para executar o arquivo "rdt20.py" utiliza-se dois comandos:
    - python rdt20.py receiver --port 10000
    - python rdt20.py sender --dest-host 127.0.0.1 --dest-port 10000 --bind-port 10001
OBS: Rode em terminais diferentes (Git bash).

2) Para executar o arquivo "rdt21.py" utiliza-se dois comandos:
    - python -c "from fase1.rdt21 import RDT21Receiver; import time; r=RDT21Receiver(local_addr=('localhost',10000), verbose=True); print('Receiver rodando na porta 10000'); time.sleep(600)"
    - python -c "from fase1.rdt21 import RDT21Sender; s=RDT21Sender(local_addr=('localhost',0), dest_addr=('localhost',10000), verbose=True); s.send(b'Teste rdt2.1'); s.close()"
OBS: Rode em terminais diferentes (Git bash).

3) Para executar o arquivo "rdt30.py" utiliza-se dois comandos:
    - python -m fase1.rdt30 receiver --local-port 10000 --verbose
    - python -m fase1.rdt30 sender --local-port 0 --dest-port 10000 --verbose
OBS: Rode em terminais diferentes (Git bash)

4) Para executar o arquivo "test_fase1.py" utiliza-se o comando:
    - python -m testes.test_fase1 (Git bash)

5) Para executar o arquivo "test_fase2.py" utiliza-se o comando:
    - python testes/test_fase2.py (Git bash)

6) Para executar o arquivo "test_fase3.py" utiliza-se o comando:
    - python testes/test_fase3.py (Git bash)