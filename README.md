# Batalha Naval em Rede

Jogo de Batalha Naval multijogador para dois jogadores, feito em Python com
**sockets TCP** e **threads**. Um computador roda o servidor; cada jogador
abre o cliente gráfico e se conecta a ele.

## Arquivos

| Arquivo        | O que é                                                      |
|----------------|--------------------------------------------------------------|
| `servidor.py`  | Servidor TCP multithread (uma thread por jogador)             |
| `cliente.py`   | Cliente com interface gráfica (Tkinter) e thread de rede      |
| `protocolo.py` | Funções e regras compartilhadas (mensagens, frota, validação) |

Os três arquivos precisam ficar **na mesma pasta**.

## Requisitos

* **Python 3.8 ou superior** (testado no 3.12). Nenhuma biblioteca externa:
  só a biblioteca padrão (`socket`, `threading`, `tkinter`, `queue`).
* **Tkinter**
  * Windows e macOS (instalador do python.org): já vem instalado.
  * Linux (Ubuntu/Debian): `sudo apt install python3-tk`

Para conferir se está tudo certo:

```
python --version
python -c "import tkinter; print('tkinter ok')"
```

> No Linux/macOS o comando pode ser `python3` em vez de `python`.

## Como rodar (tudo no mesmo computador)

Abra **três** terminais dentro da pasta do projeto.

**Terminal 1 - servidor**

```
python servidor.py
```

Ele mostra algo como:

```
[18:22:27] Servidor da Batalha Naval ouvindo na porta 5000
[18:22:27] Jogadores na mesma rede devem usar o IP: 192.168.0.15
```

**Terminal 2 - jogador 1**

```
python cliente.py
```

**Terminal 3 - jogador 2**

```
python cliente.py
```

Em cada janela, digite um nome, deixe o servidor como `127.0.0.1`, a porta
como `5000` e clique em **ZARPAR!**. Quando o segundo jogador conectar, a
partida começa automaticamente.

## Como rodar em computadores diferentes (mesma rede / Wi-Fi)

1. No computador do servidor, rode `python servidor.py` e anote o IP que ele
   mostra (ex.: `192.168.0.15`).
2. Em cada computador de jogador, rode `python cliente.py` e, no campo
   **Servidor (IP)**, digite esse IP.
3. Se não conectar, libere a porta 5000 no firewall do computador do servidor
   (no Windows, aceite o aviso "Permitir acesso" que aparece na primeira vez).

Opções de linha de comando (todas opcionais):

```
python servidor.py --porta 6000
python cliente.py --host 192.168.0.15 --porta 6000 --nome Maria
```

## Como jogar

1. **Posicionamento**: clique na sua grade para colocar cada navio.
   * Botão direito do mouse ou tecla **R** gira o navio.
   * Clique num navio já colocado para pegá-lo de volta.
   * **ALEATÓRIO** posiciona tudo sozinho; **LIMPAR** recomeça.
   * Com os 5 navios no lugar, clique em **PRONTO PARA A BATALHA!**
2. **Batalha**: quando aparecer "SUA VEZ", clique numa casa das
   *Águas Inimigas*. A vez alterna a cada tiro.
   * Círculo branco = água. Fogo = acerto.
   * Ao afundar um navio, ele explode em cadeia, se parte ao meio e afunda;
     no lugar fica o naufrágio (contorno tracejado).
3. Vence quem afundar os 5 navios do oponente primeiro: Porta-aviões (5),
   Encouraçado (4), Cruzador (3), Submarino (3) e Destróier (2).
4. No fim, escolha **REVANCHE** (os dois precisam aceitar) ou
   **NOVO OPONENTE**.
5. O painel da direita mostra o histórico da partida e tem um **chat**.
6. **Tela cheia**: aperte **F11** ou clique em **TELA CHEIA** no canto da
   tela (Esc ou F11 para voltar). A interface se ajusta a qualquer resolução.

## Comandos do console do servidor

Com o servidor rodando, digite no terminal dele:

* `status`: clientes conectados, partidas ativas, threads ativas
* `partidas`: lista as partidas em andamento
* `sair`: encerra o servidor

## Testando o protocolo sem interface (opcional)

O protocolo é texto puro, então dá para "jogar" pelo terminal com o `nc`
(netcat) ou `telnet`:

```
nc 127.0.0.1 5000
HELLO|Teste
```

O servidor responde `WELCOME|Teste` e `WAIT`. A lista completa de mensagens
está no início do arquivo `protocolo.py`.

## Problemas comuns

| Problema | Solução |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Linux: `sudo apt install python3-tk` |
| `ModuleNotFoundError: No module named 'protocolo'` | Rode os comandos de dentro da pasta do projeto |
| "Falha ao conectar: Connection refused" | O servidor não está rodando, ou o IP/porta estão errados |
| Conecta no mesmo PC mas não em outro | Firewall bloqueando a porta 5000, ou as máquinas não estão na mesma rede |
| `OSError: Address already in use` | Já existe um servidor na porta; feche-o ou use `--porta 5001` |
