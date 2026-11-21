import argparse
import os
import random
import socket
import threading
import time

from protocolo import (PORTA_PADRAO, TAMANHO, montar, ler_mensagens,
                       decodificar_frota, validar_frota, codificar_frota,
                       celulas_navio, nome_celula)

_lock_print = threading.Lock()


def log(msg):
    with _lock_print:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Jogador:

    def __init__(self, sock, endereco):
        self.sock = sock
        self.endereco = endereco
        self.nome = f"{endereco[0]}:{endereco[1]}"
        self.partida = None
        self.conectado = True
        self._lock_envio = threading.Lock()

    def enviar(self, *partes):
        if not self.conectado:
            return
        try:
            with self._lock_envio:
                self.sock.sendall(montar(*partes))
        except OSError:
            self.conectado = False

    def __repr__(self):
        return self.nome


# ----------------------------------------------------------------------
class Navio:
    def __init__(self, tam, l, c, o):
        self.tam, self.l, self.c, self.o = tam, l, c, o
        self.celulas = set(celulas_navio(tam, l, c, o))
        self.atingidas = set()

    @property
    def afundado(self):
        return self.atingidas == self.celulas


class Partida:

    def __init__(self, a, b):
        self.jogadores = [a, b]
        self.lock = threading.RLock()
        a.partida = self
        b.partida = self
        self.reiniciar()

    def reiniciar(self):
        self.estado = "posicionando"  
        self.frotas = {j: None for j in self.jogadores}
        self.tiros = {j: set() for j in self.jogadores}
        self.vez = None
        self.revanche = set()

    def oponente(self, j):
        a, b = self.jogadores
        return b if j is a else a

    # ---------------------------------------------------------------
    def posicionar(self, j, texto):
        with self.lock:
            if self.estado != "posicionando":
                return j.enviar("ERROR", "Não é hora de posicionar")
            if self.frotas[j] is not None:
                return j.enviar("ERROR", "Frota já enviada")
            try:
                navios = decodificar_frota(texto)
                validar_frota(navios)
            except (ValueError, IndexError):
                return j.enviar("ERROR", "Posicionamento inválido")
            self.frotas[j] = [Navio(*n) for n in navios]
            j.enviar("PLACE_OK")
            op = self.oponente(j)
            log(f"{j} posicionou a frota")

            if self.frotas[op] is None:
                op.enviar("OPP_READY")
                return
            self.estado = "jogando"
            self.vez = random.choice(self.jogadores)
            outro = self.oponente(self.vez)
            self.vez.enviar("START", "YOU")
            outro.enviar("START", "OPP")
            log(f"Partida {self.jogadores[0]} x {self.jogadores[1]} "
                f"começou - {self.vez} atira primeiro")

    # ---------------------------------------------------------------
    def atirar(self, j, l, c):
        with self.lock:
            if self.estado != "jogando":
                return j.enviar("ERROR", "A partida não está em andamento")
            if self.vez is not j:
                return j.enviar("ERROR", "Não é a sua vez")
            if not (0 <= l < TAMANHO and 0 <= c < TAMANHO):
                return j.enviar("ERROR", "Coordenada inválida")
            if (l, c) in self.tiros[j]:
                return j.enviar("ERROR", "Você já atirou aí")

            self.tiros[j].add((l, c))
            op = self.oponente(j)
            resultado, extra = "MISS", []
            for navio in self.frotas[op]:
                if (l, c) in navio.celulas:
                    navio.atingidas.add((l, c))
                    resultado = "HIT"
                    if navio.afundado:
                        resultado = "SUNK"
                        extra = [navio.tam, navio.l, navio.c, navio.o]
                    break

            j.enviar("SHOT", "YOU", l, c, resultado, *extra)
            op.enviar("SHOT", "OPP", l, c, resultado, *extra)
            log(f"{j} -> {nome_celula(l, c)}: {resultado}")

            if all(n.afundado for n in self.frotas[op]):
                self.estado = "fim"
                frota_vencedor = codificar_frota(
                    [(n.tam, n.l, n.c, n.o) for n in self.frotas[j]])
                j.enviar("GAMEOVER", "WIN")
                op.enviar("GAMEOVER", "LOSE", frota_vencedor)
                log(f"*** {j} venceu {op} ***")
                return

            self.vez = op
            op.enviar("TURN", "YOU")
            j.enviar("TURN", "OPP")

    # ---------------------------------------------------------------
    def pedir_revanche(self, j):
        with self.lock:
            if self.estado != "fim":
                return j.enviar("ERROR", "Revanche só ao fim da partida")
            self.revanche.add(j)
            op = self.oponente(j)
            if len(self.revanche) < 2:
                op.enviar("REMATCH_REQ", j.nome)
                return
            self.reiniciar()
            for x in self.jogadores:
                x.enviar("REMATCH_START")
            log(f"Revanche: {self.jogadores[0]} x {self.jogadores[1]}")

    def chat(self, j, texto):
        texto = texto[:300]
        op = self.oponente(j)
        j.enviar("CHAT", "YOU", j.nome, texto)
        op.enviar("CHAT", "OPP", j.nome, texto)

    def sair(self, j):
        with self.lock:
            if self.estado == "encerrada":
                return
            self.estado = "encerrada"
            op = self.oponente(j)
            j.partida = None
            op.partida = None
            op.enviar("OPP_LEFT")
            log(f"Partida {self.jogadores[0]} x {self.jogadores[1]} encerrada")


# ----------------------------------------------------------------------
class Servidor:
    def __init__(self, host, porta):
        self.host, self.porta = host, porta
        self.lock = threading.Lock()
        self.em_espera = None       
        self.clientes = []
        self.partidas = []
        self.total_partidas = 0
        self.sock = None

    # ---- matchmaking ---------------------------------------------
    def procurar_partida(self, j):
        with self.lock:
            esp = self.em_espera
            if esp is not None and esp is not j and esp.conectado \
                    and esp.partida is None:
                self.em_espera = None
                partida = Partida(esp, j)
                self.partidas.append(partida)
                self.total_partidas += 1
            else:
                self.em_espera = j
                partida = None
        if partida:
            esp.enviar("MATCHED", j.nome)
            j.enviar("MATCHED", esp.nome)
            log(f"Nova partida: {esp} x {j}")
        else:
            j.enviar("WAIT")
            log(f"{j} entrou na fila de espera")

    # ---- thread de cada cliente ----------------------------------
    def atender_cliente(self, sock, endereco):
        j = Jogador(sock, endereco)
        with self.lock:
            self.clientes.append(j)
        log(f"Conexão de {endereco[0]}:{endereco[1]} "
            f"(thread {threading.current_thread().name})")
        identificado = False
        try:
            for partes in ler_mensagens(sock):
                cmd, args = partes[0].upper(), partes[1:]

                if cmd == "HELLO" and not identificado:
                    nome = (args[0] if args else "").strip()[:20]
                    j.nome = nome or j.nome
                    identificado = True
                    j.enviar("WELCOME", j.nome)
                    self.procurar_partida(j)
                elif not identificado:
                    j.enviar("ERROR", "Envie HELLO|<nome> primeiro")
                elif cmd == "PLACE" and j.partida and args:
                    j.partida.posicionar(j, args[0])
                elif cmd == "FIRE" and j.partida and len(args) >= 2:
                    try:
                        l, c = int(args[0]), int(args[1])
                    except ValueError:
                        j.enviar("ERROR", "Coordenada inválida")
                        continue
                    j.partida.atirar(j, l, c)
                elif cmd == "CHAT" and j.partida and args:
                    j.partida.chat(j, "|".join(args))
                elif cmd == "REMATCH" and j.partida:
                    j.partida.pedir_revanche(j)
                elif cmd == "FIND":
                    if j.partida is not None:      # abandona a atual
                        j.partida.sair(j)
                    self.procurar_partida(j)
                elif cmd == "QUIT":
                    break
                else:
                    j.enviar("ERROR", f"Comando inválido: {cmd}")
        finally:
            self.desconectar(j)

    def desconectar(self, j):
        j.conectado = False
        if j.partida:
            j.partida.sair(j)
        with self.lock:
            if self.em_espera is j:
                self.em_espera = None
            if j in self.clientes:
                self.clientes.remove(j)
            self.partidas = [p for p in self.partidas
                             if p.estado != "encerrada"]
        try:
            j.sock.close()
        except OSError:
            pass
        log(f"{j} desconectou")

    # ---- console do operador (usa input) --------------------------
    def console(self):
        log("Console: digite 'status', 'partidas' ou 'sair'")
        while True:
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return          # sem terminal (ex.: rodando em background)
            if cmd == "status":
                with self.lock:
                    print(f"  Clientes conectados : {len(self.clientes)}")
                    print(f"  Partidas ativas     : {len(self.partidas)}")
                    print(f"  Na fila de espera   : {self.em_espera}")
                    print(f"  Partidas (total)    : {self.total_partidas}")
                    print(f"  Threads ativas      : {threading.active_count()}")
            elif cmd == "partidas":
                with self.lock:
                    if not self.partidas:
                        print("  (nenhuma)")
                    for p in self.partidas:
                        a, b = p.jogadores
                        print(f"  {a} x {b}  [{p.estado}]")
            elif cmd == "sair":
                log("Encerrando servidor...")
                os._exit(0)
            elif cmd:
                print("  Comandos: status | partidas | sair")

    # ---- laço principal --------------------------------------------
    def iniciar(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.porta))
        self.sock.listen(16)
        log(f"Servidor da Batalha Naval ouvindo na porta {self.porta}")
        log(f"Jogadores na mesma rede devem usar o IP: {ip_local()}")

        threading.Thread(target=self.console, name="console",
                         daemon=True).start()
        try:
            while True:
                conn, endereco = self.sock.accept()
                # desliga o algoritmo de Nagle: mensagens curtas saem já
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                t = threading.Thread(target=self.atender_cliente,
                                     args=(conn, endereco), daemon=True)
                t.start()
        except KeyboardInterrupt:
            log("Encerrando servidor (Ctrl+C)")
        finally:
            self.sock.close()


def ip_local():

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Servidor da Batalha Naval")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    a = ap.parse_args()
    Servidor(a.host, a.porta).iniciar()
