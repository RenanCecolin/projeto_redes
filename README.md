# EFC 02: Implementação de Transferência Confiável de Dados e TCP sobre UDP

Este projeto tem como objetivo implementar protocolos de comunicação confiável em três fases, evoluindo desde protocolos básicos de transferência confiável até uma versão simplificada de TCP sobre UDP.

**Alunos:**

- Leonardo Ferraro Gianfagna - 18174490
- Mateus Colferai Mistro - 23002896
- Rafael Gonçalves Michielin - 23012113
- Renan Negri Cecolin – 23012651
- Samuel Arantes dos Santos Prado – 23013858

---

## Estrutura do Projeto

```
projeto_redes/
├── fase1/                 # Protocolos RDT (Reliable Data Transfer)
│   ├── rdt20.py           # Implementação rdt2.0
│   ├── rdt21.py           # Implementação rdt2.1
│   └── rdt30.py           # Implementação rdt3.0
├── fase2/                 # Protocolo Go-Back-N e Selective Repeat
│   └── gbn.py             # Implementação Go-Back-N
|   └── sr.py              # Implementação Selective Repeat
├── fase3/                 # TCP Simplificado sobre UDP
|   ├── tcp_socket.py      # Classe SimpleTCPSocket
|   ├── tcp_server.py      # Aplicação servidor de exemplo
|   └── tcp_client.py      # Aplicação cliente de exemplo
├── testes/                # Suíte de testes completa
│   ├── test_fase1.py      # Testes RDT
│   ├── test_fase2.py      # Testes Go-Back-N e Selective Repeat
│   └── test_fase3.py      # Testes TCP
├── utils/                 # Utilitários compartilhados
│   ├── packet.py          # Classes de pacotes
│   ├── simulator.py       # Simulador de canal
│   └── logger.py          # Sistema de logging de protocolos
├── relatorio/
│ └── relatorio.pdf        # Relatório final
└── README.MD              # Este arquivo
```

## Requisitos

- Python 3.8 ou superior
- matplotlib (para gerar os gráficos)

### Instalação das Dependências

```bash
python -m pip install matplotlib
```

## Execução dos Testes

```bash
# Executa todos os testes da fase 1
python -m testes.test_fase1

# Executa todos os testes da fase 2
python -m testes.test_fase2

# Executa todos os testes da fase 3
python -m testes.test_fase3

# OBS:
O Relatório contêm todas as capturas de tela dos logs de teste.
```
