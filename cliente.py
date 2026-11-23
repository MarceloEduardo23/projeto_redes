
import argparse
import math
import queue
import random
import socket
import sys
import threading
import time
import tkinter as tk

from protocolo import (PORTA_PADRAO, TAMANHO, LETRAS, FROTA, montar,
                       ler_mensagens, celulas_navio, cabe, codificar_frota,
                       decodificar_frota, frota_aleatoria, nome_celula)

# ----------------------------------------------------------------------
# Visual
# ----------------------------------------------------------------------
FONTE = "Helvetica"
FUNDO1, FUNDO2 = "#020b17", "#0a2c4d"
OCEANO = ["#0c4470", "#0e4a7a", "#0f4f82", "#0d4878", "#11558a", "#0b4069"]
GRADE = "#1e6aa3"
TEXTO, SUAVE = "#e8f4ff", "#8fb3d1"
ACENTO, PERIGO, ALERTA, OK = "#2ee6d6", "#ff4d3d", "#ffb020", "#3ddc84"
CARD, BORDA_CARD = "#071c33", "#1f6fae"

C = 38                       
OY = 172                     
OX_MEU, OX_INI = 70, 530     
CW, CH = 980, 720            
LARG_PAINEL = 300            


def misturar(c1, c2, t):
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t)
                                   for k in range(3))


def ret_arredondado(cv, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


def gradiente(cv, w, h, c1, c2, tag="bg"):
    for y in range(0, h, 4):
        cv.create_rectangle(0, y, w, y + 4, outline="",
                            fill=misturar(c1, c2, y / h), tags=tag)


class TelaEscalada(tk.Canvas):

    def __init__(self, master, escala=1.0, **kw):
        self.s = escala
        super().__init__(master, **kw)

    def _t(self, args):
        nums = []

        def plano(a):
            for x in a:
                if isinstance(x, (list, tuple)):
                    plano(x)
                else:
                    nums.append(x * self.s)
        plano(args)
        return nums

    def fonte(self, f):
        if isinstance(f, tuple) and len(f) >= 2 and f[1] > 0:
            return (f[0], -max(6, round(f[1] * 96 / 72 * self.s))) + f[2:]
        return f

    def _create(self, tipo, args, kw):
        kw = dict(kw)
        if "font" in kw:
            kw["font"] = self.fonte(kw["font"])
        if "width" in kw and tipo != "window":
            kw["width"] = max(1, kw["width"] * self.s)
        return super()._create(tipo, self._t(args), kw)

    def coords(self, item, *args):
        if args:
            return super().coords(item, *self._t(args))
        return super().coords(item)

    def move(self, item, dx, dy):
        return super().move(item, dx * self.s, dy * self.s)

    def logico(self, ev):
        return self.canvasx(ev.x) / self.s, self.canvasy(ev.y) / self.s


ESTILOS_NAVIO = {
    "normal":   ("#8796a5", "#c9d6e2", "#5f6e7c", "#2b3640"),
    "afundado": ("#3a2622", "#ff4d3d", "#2a1a17", "#120a08"),
    "revelado": ("#3f4d5a", "#ffb020", "#2f3a45", "#1d252d"),
    "ok":       ("#1c7f78", "#2ee6d6", "#156560", "#0b3b38"),
    "ruim":     ("#7a2a25", "#ff4d3d", "#5c1e1a", "#2e0f0d"),
    "naufragio": ("#082a47", "#ff4d3d", "#06223b", "#051a2e"),
}


# ----------------------------------------------------------------------
# Rede
# ----------------------------------------------------------------------
class Conexao:
    """Encapsula o socket TCP. A recepção roda numa thread separada."""

    def __init__(self, fila, ident):
        self.fila, self.ident = fila, ident
        self.sock = None
        self.lock = threading.Lock()

    def conectar(self, host, porta, nome):
        def tarefa():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect((host, porta))
                s.settimeout(None)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock = s
                self.enviar("HELLO", nome)
            except OSError as e:
                self.fila.put((self.ident, ["_ERRO_CONEXAO", str(e)]))
                return
            self.fila.put((self.ident, ["_CONECTADO"]))
            for partes in ler_mensagens(s):          
                self.fila.put((self.ident, partes))
            self.fila.put((self.ident, ["_DESCONECTADO"]))

        threading.Thread(target=tarefa, name="rede", daemon=True).start()

    def enviar(self, *partes):
        if self.sock is None:
            return
        try:
            with self.lock:
                self.sock.sendall(montar(*partes))
        except OSError:
            pass

    def fechar(self):
        if self.sock:
            self.enviar("QUIT")
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


# ----------------------------------------------------------------------
class Botao:
    _contador = 0

    def __init__(self, cv, x, y, w, h, texto, comando, cor=ACENTO,
                 tamanho=12, tag="ui"):
        Botao._contador += 1
        self.cv, self.cmd, self.cor = cv, comando, cor
        self.tag = f"botao{Botao._contador}"
        self.ativo = True
        tags = (tag, self.tag)
        ret_arredondado(cv, x - w / 2 + 3, y - h / 2 + 4, x + w / 2 + 3,
                        y + h / 2 + 4, 12, fill="#01060d", outline="",
                        tags=tags)
        self.fundo = ret_arredondado(cv, x - w / 2, y - h / 2, x + w / 2,
                                     y + h / 2, 12, width=2, tags=tags)
        self.txt = cv.create_text(x, y, text=texto, fill=TEXTO,
                                  font=(FONTE, tamanho, "bold"), tags=tags)
        cv.tag_bind(self.tag, "<Enter>", self._entrar)
        cv.tag_bind(self.tag, "<Leave>", self._sair)
        cv.tag_bind(self.tag, "<Button-1>", self._clicar)
        self._pintar(False)

    def _pintar(self, foco):
        if not self.ativo:
            self.cv.itemconfig(self.fundo, fill="#1a2533", outline="#3a4a5c")
            self.cv.itemconfig(self.txt, fill="#5d6f82")
            return
        fill = misturar(self.cor, "#000000", 0.25 if foco else 0.6)
        self.cv.itemconfig(self.fundo, fill=fill, outline=self.cor)
        self.cv.itemconfig(self.txt, fill=TEXTO)

    def _entrar(self, _):
        if self.ativo:
            self._pintar(True)
            self.cv.config(cursor="hand2")

    def _sair(self, _):
        self._pintar(False)
        self.cv.config(cursor="")

    def _clicar(self, _):
        if self.ativo:
            self.cv.config(cursor="")
            self.cmd()
        return "break"

    def habilitar(self, ativo, texto=None):
        self.ativo = ativo
        if texto:
            self.cv.itemconfig(self.txt, text=texto)
        self._pintar(False)


# ----------------------------------------------------------------------
class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        root.title("Batalha Naval - Redes de Computadores")
        root.configure(bg=FUNDO1)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.fechar)
        root.bind("<F11>", self.alternar_tela_cheia)
        root.bind("<Escape>", lambda _e: self.tela_cheia and
                  self.alternar_tela_cheia())
        self.tela_cheia = False
        self.historico = []          
        self.naufragios = []         
        dpi = max(1.0, root.winfo_fpixels("1i") / 96)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.escala_janela = max(0.6, min(dpi, sw * 0.96 / (CW + LARG_PAINEL),
                                          (sh - 90) / CH))

        self.fila = queue.Queue()
        self.con, self.con_id = None, 0
        self.meu_nome, self.nome_op = "", ""
        self.estado = "conexao"
        self.aviso = None
        self.tick = 0
        self.particulas, self.chamas = [], {}
        self.radar, self.banner = None, None
        self.txt_log = None
        self.shake = 0
        self.ids_celulas = []
        self.vista = (0, 0)
        self.novo_jogo()
        self.tela_conexao()
        root.after(30, self.processar_fila)
        root.after(40, self.animar)

    # ==================================================================
    # Estado de uma partida
    # ==================================================================
    def novo_jogo(self):
        self.posicionados = [None] * len(FROTA)    
        self.orient = "H"
        self.meus_navios = []       
        self.tiros_meus, self.tiros_op = {}, {}
        self.ini_afundados = []     
        self.ini_idx_afundados = set()
        self.frota_revelada = None
        self.minha_vez = False
        self.esperando_tiro = False
        self.op_pronto = False
        self.op_quer_revanche = False
        self.pedi_revanche = False
        self.vitoria = False
        self.fogos = 0
        self.chamas = {}

    # ==================================================================
    # Tela de conexão
    # ==================================================================
    def limpar_janela(self):
        for w in self.root.winfo_children():
            w.destroy()
        self.particulas, self.chamas, self.naufragios = [], {}, []
        self.radar = self.banner = self.txt_log = None

    def novo_container(self):
        self.limpar_janela()
        if self.tela_cheia:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.s = min(sw / (CW + LARG_PAINEL), sh / CH)
        else:
            self.s = self.escala_janela
        quadro = tk.Frame(self.root, bg=FUNDO1)
        if self.tela_cheia:
            quadro.place(relx=0.5, rely=0.5, anchor="center")
        else:
            quadro.pack()
        return quadro

    def fonte(self, tamanho, *estilo):
        return (FONTE, -max(6, round(tamanho * 96 / 72 * self.s))) + estilo

    def alternar_tela_cheia(self, _ev=None):
        self.tela_cheia = not self.tela_cheia
        self.root.resizable(self.tela_cheia, self.tela_cheia)
        self.root.attributes("-fullscreen", self.tela_cheia)
        if self.tela_cheia:    
            self.root.geometry(f"{self.root.winfo_screenwidth()}x"
                               f"{self.root.winfo_screenheight()}+0+0")
        else:
            self.root.geometry("")          
        self.root.update_idletasks()
        if self.estado == "conexao":
            self.args.nome = self.entradas["Seu nome"].get()
            self.args.host = self.entradas["Servidor (IP)"].get()
            self.args.porta = self.entradas["Porta"].get()
            erro = self.cv.itemcget(self.lbl_erro, "text")
            ativo = self.btn_conectar.ativo
            self.tela_conexao(erro)
            self.btn_conectar.habilitar(ativo)
        else:
            rascunho = self.ent_chat.get()
            self.tela_jogo()
            self.ent_chat.insert(0, rascunho)
            self.redesenhar()

    def botao_tela_cheia(self, x, y):
        Botao(self.cv, x, y, 150, 30,
              "SAIR DA TELA CHEIA" if self.tela_cheia else "TELA CHEIA (F11)",
              self.alternar_tela_cheia, cor=SUAVE, tamanho=9)

    def tela_conexao(self, erro=""):
        quadro = self.novo_container()
        self.estado = "conexao"
        W, H = CW + LARG_PAINEL, CH
        cv = self.cv = TelaEscalada(quadro, self.s, width=W * self.s,
                                    height=H * self.s, bg=FUNDO1,
                                    highlightthickness=0)
        cv.pack()
        gradiente(cv, W, H, "#01050d", "#0b3358")
        self.estrelas = []
        for _ in range(90):
            x, y = random.randint(0, W), random.randint(0, 420)
            r = random.choice((1, 1, 1, 2))
            self.estrelas.append(cv.create_oval(x, y, x + r, y + r,
                                                fill="#9fb8d0", outline=""))
        cv.create_oval(1080, 60, 1160, 140, fill="#dfe9f5", outline="")
        cv.create_oval(1100, 60, 1180, 140, fill="#06162a", outline="")

        for d, cor in ((4, "#05345a"), (2, "#0d6c8a")):
            cv.create_text(W / 2 + d, 88 + d, text="BATALHA NAVAL",
                           fill=cor, font=(FONTE, 54, "bold"))
        cv.create_text(W / 2, 88, text="BATALHA NAVAL", fill=TEXTO,
                       font=(FONTE, 54, "bold"))
        cv.create_text(W / 2, 142, fill=ACENTO, font=(FONTE, 13),
                       text="multijogador em rede  -  sockets TCP  -  threads")
        self.botao_tela_cheia(95, 30)

        self.ondas = []
        for base, cor in ((618, "#0a3a63"),):
            self.ondas.append((cv.create_polygon(0, 0, 0, 0, fill=cor,
                                                 outline=""), base))
        self.desenhar_navio_capa(860, 620)
        for base, cor in ((638, "#0c4a7c"), (668, "#0f5a94")):
            self.ondas.append((cv.create_polygon(0, 0, 0, 0, fill=cor,
                                                 outline=""), base))
        self.bob = 0.0

        x0, x1, y0 = W / 2 - 210, W / 2 + 210, 178
        fundo_card = ret_arredondado(cv, x0, y0, x1, y0 + 10, 22, fill=CARD,
                                     outline=BORDA_CARD, width=2)
        cv.create_text(W / 2, y0 + 32, text="ENTRAR NO MAR", fill=TEXTO,
                       font=(FONTE, 15, "bold"))
        self.entradas = {}
        campos = [("Seu nome", self.args.nome or
                   f"Capitão{random.randint(10, 99)}"),
                  ("Servidor (IP)", self.args.host),
                  ("Porta", str(self.args.porta))]
        y = y0 + 64
        for rotulo, valor in campos:
            cv.create_text(x0 + 40, y, text=rotulo, anchor="w",
                           fill=SUAVE, font=(FONTE, 10, "bold"))
            e = tk.Entry(cv, font=self.fonte(13), bg="#0b2a48", fg=TEXTO,
                         insertbackground=TEXTO, relief="flat",
                         highlightthickness=2, highlightbackground=BORDA_CARD,
                         highlightcolor=ACENTO)
            e.insert(0, valor)
            e.bind("<Return>", lambda _e: self.conectar())
            cv.create_window(x0 + 40, y + 12, window=e, anchor="nw",
                             width=(x1 - x0 - 80) * self.s)
            altura = e.winfo_reqheight() / self.s
            self.entradas[rotulo] = e
            y += 12 + altura + 24
        y_botao = y + 14
        self.btn_conectar = Botao(cv, W / 2, y_botao, 220, 46, "ZARPAR!",
                                  self.conectar, cor=OK, tamanho=15)
        y1 = y_botao + 23 + 26
        cv.coords(fundo_card, *self._pontos_card(x0, y0, x1, y1, 22))
        self.lbl_erro = cv.create_text(W / 2, y1 + 22, text=erro,
                                       fill=PERIGO, font=(FONTE, 11, "bold"))
        self.entradas["Seu nome"].focus_set()

    @staticmethod
    def _pontos_card(x0, y0, x1, y1, r):
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1,
                y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r,
                x0, y0]

    def desenhar_navio_capa(self, x, y):
        cv, t = self.cv, "capa_navio"
        casco = [x, y - 30, x + 380, y - 30, x + 345, y + 8, x + 30, y + 8]
        cv.create_polygon(casco, fill="#3b4652", outline="#7b8a99", width=2,
                          tags=t)
        cv.create_rectangle(x + 20, y - 34, x + 365, y - 30, fill="#ff4d3d",
                            outline="", tags=t)
        cv.create_rectangle(x + 120, y - 70, x + 250, y - 34, fill="#56626e",
                            outline="#8c9aa8", tags=t)
        cv.create_rectangle(x + 150, y - 98, x + 220, y - 70, fill="#66727e",
                            outline="#8c9aa8", tags=t)
        for i in range(5):
            cv.create_rectangle(x + 158 + i * 12, y - 90, x + 165 + i * 12,
                                y - 82, fill="#ffd84d", outline="", tags=t)
        cv.create_rectangle(x + 200, y - 130, x + 218, y - 98,
                            fill="#2b3640", outline="#8c9aa8", tags=t)
        cv.create_line(x + 175, y - 98, x + 175, y - 150, fill="#8c9aa8",
                       width=2, tags=t)
        for cx in (x + 60, x + 310):
            cv.create_oval(cx - 16, y - 46, cx + 16, y - 30, fill="#4a5662",
                           outline="#8c9aa8", tags=t)
            cv.create_line(cx, y - 40, cx + 45, y - 44, fill="#8c9aa8",
                           width=4, tags=t)
        self.chamine = (x + 209, y - 132)

    def animar_capa(self):
        cv = self.cv
        fase = self.tick * 0.08
        for k, (pid, base) in enumerate(self.ondas):
            pts = [0, CH]
            for xx in range(0, CW + LARG_PAINEL + 21, 20):
                yy = base + 7 * math.sin(xx * 0.018 + fase * (1 + k * 0.4)) \
                    + 4 * math.sin(xx * 0.043 - fase * 1.3)
                pts += [xx, yy]
            pts += [CW + LARG_PAINEL, CH]
            cv.coords(pid, *pts)
        novo = 5 * math.sin(self.tick * 0.06)
        cv.move("capa_navio", 0, novo - self.bob)
        self.chamine = (self.chamine[0], self.chamine[1] + novo - self.bob)
        self.bob = novo
        if self.tick % 5 == 0:
            self.fumaca(*self.chamine, grande=True)
        if self.tick % 3 == 0:
            s = random.choice(self.estrelas)
            cv.itemconfig(s, fill=random.choice(("#9fb8d0", "#ffffff",
                                                 "#4d6a86")))

    def conectar(self):
        nome = self.entradas["Seu nome"].get().strip()[:20]
        host = self.entradas["Servidor (IP)"].get().strip()
        try:
            porta = int(self.entradas["Porta"].get())
        except ValueError:
            return self.cv.itemconfig(self.lbl_erro, text="Porta inválida")
        if not nome or not host:
            return self.cv.itemconfig(self.lbl_erro,
                                      text="Preencha nome e servidor")
        self.meu_nome, self.host, self.porta = nome, host, porta
        self.historico = []
        self.args.nome, self.args.host, self.args.porta = nome, host, porta
        self.cv.itemconfig(self.lbl_erro, text="Conectando...", fill=ALERTA)
        self.btn_conectar.habilitar(False)
        if self.con:
            self.con.fechar()
        self.con_id += 1
        self.con = Conexao(self.fila, self.con_id)
        self.con.conectar(host, porta, nome)

    # ==================================================================
    # Recepção das mensagens (vindas da thread de rede via fila)
    # ==================================================================
    def processar_fila(self):
        try:
            while True:
                ident, partes = self.fila.get_nowait()
                if ident != self.con_id:
                    continue              
                try:
                    self.tratar(partes)
                except Exception as e:     
                    import traceback
                    traceback.print_exc()
                    self.registrar(f"Erro interno: {e}", "erro")
        except queue.Empty:
            pass
        self.root.after(30, self.processar_fila)

    def tratar(self, p):
        cmd = p[0]
        if cmd == "_ERRO_CONEXAO":
            if self.estado == "conexao":
                self.cv.itemconfig(self.lbl_erro, fill=PERIGO,
                                   text=f"Falha ao conectar: {p[1]}")
                self.btn_conectar.habilitar(True)
        elif cmd == "WELCOME":
            self.meu_nome = p[1]
            self.tela_jogo()
            self.estado = "aguardando"
            self.redesenhar()
            self.registrar(f"Conectado a {self.host}:{self.porta} "
                           f"como {self.meu_nome}.", "destaque")
        elif cmd == "WAIT":
            self.estado, self.aviso, self.nome_op = "aguardando", None, ""
            self.redesenhar()
            self.registrar("Aguardando outro jogador entrar...")
        elif cmd == "MATCHED":
            self.nome_op = p[1]
            self.novo_jogo()
            self.estado, self.aviso = "posicionando", None
            self.redesenhar()
            self.registrar(f"Oponente encontrado: {self.nome_op}!",
                           "destaque")
            self.registrar("Posicione seus navios e clique em PRONTO.")
        elif cmd == "PLACE_OK":
            self.estado = "pronto"
            self.redesenhar()
            self.registrar("Frota confirmada pelo servidor.")
        elif cmd == "OPP_READY":
            self.op_pronto = True
            self.registrar(f"{self.nome_op} já posicionou a frota.")
            if self.estado == "posicionando":
                self.redesenhar()
        elif cmd == "START":
            self.estado = "jogando"
            self.minha_vez = p[1] == "YOU"
            self.redesenhar()
            self.registrar("A batalha começou! " +
                           ("Você atira primeiro." if self.minha_vez else
                            f"{self.nome_op} atira primeiro."), "destaque")
        elif cmd == "TURN":
            self.minha_vez = p[1] == "YOU"
            self.esperando_tiro = False
            self.atualizar_banner()
        elif cmd == "SHOT":
            self.tratar_tiro(p)
        elif cmd == "GAMEOVER":
            self.estado = "fim"
            self.vitoria = p[1] == "WIN"
            self.minha_vez = False
            if not self.vitoria and len(p) > 2:
                self.frota_revelada = decodificar_frota(p[2])
            self.fogos = 14 if self.vitoria else 0
            self.redesenhar()
            self.registrar("VITÓRIA! Toda a frota inimiga foi afundada!"
                           if self.vitoria else
                           "DERROTA... sua frota foi afundada.",
                           "destaque" if self.vitoria else "acerto")
        elif cmd == "REMATCH_REQ":
            self.op_quer_revanche = True
            self.registrar(f"{p[1]} quer uma revanche!", "destaque")
            if self.estado == "fim":
                self.redesenhar()
        elif cmd == "REMATCH_START":
            self.novo_jogo()
            self.estado, self.aviso = "posicionando", None
            self.redesenhar()
            self.registrar("Revanche! Posicione a frota novamente.",
                           "destaque")
        elif cmd == "OPP_LEFT":
            self.aviso = "sem_oponente"
            self.minha_vez = False
            self.redesenhar()
            self.registrar(f"{self.nome_op or 'O oponente'} saiu da partida.",
                           "erro")
        elif cmd == "CHAT" and len(p) >= 4:
            quem, nome, texto = p[1], p[2], "|".join(p[3:])
            self.registrar(f"{nome}: {texto}",
                           "meu_chat" if quem == "YOU" else "op_chat")
        elif cmd == "ERROR":
            self.esperando_tiro = False
            self.registrar(f"Servidor: {p[1] if len(p) > 1 else ''}", "erro")
        elif cmd == "_DESCONECTADO":
            if self.estado == "conexao":
                self.cv.itemconfig(self.lbl_erro, fill=PERIGO,
                                   text="O servidor encerrou a conexão")
                self.btn_conectar.habilitar(True)
            else:
                self.aviso = "desconectado"
                self.redesenhar()
                self.registrar("Conexão com o servidor perdida.", "erro")

    def tratar_tiro(self, p):
        quem, l, c, res = p[1], int(p[2]), int(p[3]), p[4]
        info = None
        if res == "SUNK":
            info = (int(p[5]), int(p[6]), int(p[7]), p[8])
        alvo = nome_celula(l, c)

        if quem == "YOU":
            self.esperando_tiro = False
            self.tiros_meus[(l, c)] = res
            self.cv.delete("hover")
            self.marcar("ini", l, c, res, animar=True)
            if res == "MISS":
                self.registrar(f"Você atirou em {alvo}: água.", "agua")
            elif res == "HIT":
                self.registrar(f"Você atirou em {alvo}: FOGO! Acertou!",
                               "acerto")
            else:
                idx = self.indice_frota(info[0], self.ini_idx_afundados)
                self.ini_idx_afundados.add(idx)
                self.ini_afundados.append(info)
                self.registrar(f"Você atirou em {alvo}: AFUNDOU o "
                               f"{FROTA[idx][0]} inimigo!", "destaque")
                self.desenhar_navio(OX_INI, *info, "naufragio", "navio")
                self.afundar("ini", info, "afundado")
                self.desenhar_painel_frota("ini")
        else:
            self.tiros_op[(l, c)] = res
            self.marcar("meu", l, c, res, animar=True)
            nome = self.nome_op
            if res == "MISS":
                self.registrar(f"{nome} atirou em {alvo}: água.", "agua")
            else:
                for i, n in enumerate(self.meus_navios):
                    if (l, c) in n["cel"]:
                        n["hit"].add((l, c))
                        if res == "SUNK":
                            n["afundado"] = True
                            self.registrar(f"{nome} AFUNDOU o seu "
                                           f"{FROTA[i][0]}!", "acerto")
                            self.afundar("meu", (n["tam"], n["l"], n["c"],
                                                 n["o"]), "afundado")
                        else:
                            self.registrar(f"{nome} atirou em {alvo}: "
                                           f"seu navio foi atingido!",
                                           "acerto")
                self.desenhar_meus_navios()
                self.desenhar_painel_frota("meu")
        self.ordenar_camadas()

    @staticmethod
    def indice_frota(tam, usados):
        for i, (_, t) in enumerate(FROTA):
            if t == tam and i not in usados:
                return i
        return 0

    # ==================================================================
    # Tela do jogo
    # ==================================================================
    def tela_jogo(self):
        quadro = self.novo_container()
        s = self.s
        cv = self.cv = TelaEscalada(quadro, s, width=CW * s, height=CH * s,
                                    bg=FUNDO1, highlightthickness=0,
                                    confine=False, xscrollincrement=1,
                                    yscrollincrement=1)
        self.vista = (0, 0)
        cv.pack(side="left")
        cv.bind("<Motion>", self.ao_mover)
        cv.bind("<Leave>", lambda _e: cv.delete("hover"))
        cv.bind("<Button-1>", self.ao_clicar)
        cv.bind("<Button-3>", lambda _e: self.girar())
        cv.bind("<Button-2>", lambda _e: self.girar())
        cv.bind("<Key-r>", lambda _e: self.girar())
        cv.bind("<Key-R>", lambda _e: self.girar())

        painel = tk.Frame(quadro, bg="#061627", width=LARG_PAINEL * s,
                          height=CH * s)
        painel.pack(side="left", fill="y")
        painel.pack_propagate(False)
        tk.Label(painel, text="DIÁRIO DE BORDO", bg="#061627", fg=ACENTO,
                 font=self.fonte(13, "bold")).pack(pady=(18 * s, 2))
        tk.Label(painel, text="eventos da partida e chat", bg="#061627",
                 fg=SUAVE, font=self.fonte(9)).pack(pady=(0, 10 * s))

        rodape = tk.Frame(painel, bg="#061627")
        rodape.pack(side="bottom", fill="x", padx=12 * s, pady=12 * s)
        self.lbl_info = tk.Label(rodape, bg="#061627", fg=SUAVE,
                                 font=self.fonte(9), justify="left",
                                 text=f"Servidor: {self.host}:{self.porta}\n"
                                      f"Você: {self.meu_nome}")
        self.lbl_info.pack(side="bottom", anchor="w", pady=(10 * s, 0))
        linha = tk.Frame(rodape, bg="#061627")
        linha.pack(side="bottom", fill="x")
        self.ent_chat = tk.Entry(linha, font=self.fonte(11), bg="#0b2a48",
                                 fg=TEXTO, insertbackground=TEXTO,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=BORDA_CARD,
                                 highlightcolor=ACENTO)
        self.ent_chat.pack(side="left", fill="x", expand=True, ipady=6 * s)
        self.ent_chat.bind("<Return>", lambda _e: self.enviar_chat())
        tk.Button(linha, text="Enviar", command=self.enviar_chat,
                  bg=ACENTO, fg="#02131f", activebackground="#7ff5ea",
                  relief="flat", font=self.fonte(10, "bold"), padx=10 * s
                  ).pack(side="left", padx=(6 * s, 0), ipady=3 * s)

        self.txt_log = tk.Text(painel, bg="#04111f", fg=TEXTO, wrap="word",
                               font=self.fonte(10), relief="flat",
                               padx=10 * s, pady=8 * s, state="disabled",
                               highlightthickness=0, spacing1=2 * s,
                               spacing3=2 * s)
        self.txt_log.pack(fill="both", expand=True, padx=12 * s)
        for tag, cor in (("sistema", SUAVE), ("destaque", OK),
                         ("acerto", "#ff7a5c"), ("agua", "#7cc4f5"),
                         ("meu_chat", ACENTO), ("op_chat", ALERTA),
                         ("erro", PERIGO), ("hora", "#4d6a86")):
            self.txt_log.tag_configure(tag, foreground=cor)
        for hora, texto, tag in self.historico:
            self._escrever_log(hora, texto, tag)

    def registrar(self, texto, tag="sistema"):
        hora = time.strftime("%H:%M ")
        self.historico.append((hora, texto, tag))
        self._escrever_log(hora, texto, tag)

    def _escrever_log(self, hora, texto, tag):
        if self.txt_log is None:
            return
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", hora, "hora")
        self.txt_log.insert("end", texto + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def enviar_chat(self):
        texto = self.ent_chat.get().strip()
        if not texto:
            return
        if not self.nome_op or self.aviso:
            self.registrar("Ninguém para conversar ainda.", "erro")
            return
        self.con.enviar("CHAT", texto)
        self.ent_chat.delete(0, "end")

    # ------------------------------------------------------------------
    def redesenhar(self):
        cv = self.cv
        cv.delete("all")
        self.deslocar_vista((0, 0))
        self.shake = 0
        self.particulas, self.chamas, self.naufragios = [], {}, []
        self.radar = self.banner = None
        self.ids_celulas = []
        cv.config(cursor="")
        gradiente(cv, CW, CH, FUNDO1, FUNDO2)
        self.desenhar_cabecalho()

        if self.estado == "aguardando":
            self.desenhar_radar(CW / 2, 390, 160)
            cv.create_text(CW / 2, 590, text="Procurando oponente...",
                           fill=TEXTO, font=(FONTE, 18, "bold"))
            cv.create_text(CW / 2, 622, fill=SUAVE, font=(FONTE, 11),
                           text=f"Peça para outro jogador conectar em "
                                f"{self.host}:{self.porta}")
        else:
            self.desenhar_tabuleiro(OX_MEU, "meu", "SUA FROTA")
            self.desenhar_meus_navios()
            for (l, c), res in self.tiros_op.items():
                self.marcar("meu", l, c, res)
            self.desenhar_painel_frota("meu")

            if self.estado == "posicionando":
                self.desenhar_painel_posicionamento()
            elif self.estado == "pronto":
                cx, cy = OX_INI + 5 * C, OY + 5 * C - 20
                self.desenhar_radar(cx, cy, 140)
                cv.create_text(cx, OY + 360, text="FROTA PRONTA!", fill=OK,
                               font=(FONTE, 16, "bold"))
                cv.create_text(cx, OY + 388, fill=SUAVE, font=(FONTE, 11),
                               text=f"Aguardando {self.nome_op} posicionar...")
                self.desenhar_painel_frota("ini")
            else:
                self.desenhar_tabuleiro(OX_INI, "ini", "ÁGUAS INIMIGAS")
                if self.frota_revelada:
                    for n in self.frota_revelada:
                        if n not in self.ini_afundados:
                            self.desenhar_navio(OX_INI, *n, "revelado",
                                                "navio")
                for info in self.ini_afundados:
                    self.desenhar_navio(OX_INI, *info, "naufragio", "navio")
                for (l, c), res in self.tiros_meus.items():
                    self.marcar("ini", l, c, res)
                if self.estado == "fim":
                    self.desenhar_fim()
                else:
                    self.desenhar_painel_frota("ini")

        if self.aviso:
            self.desenhar_aviso()
        self.ordenar_camadas()

    def ordenar_camadas(self):
        for tag in ("navio", "marca", "chama", "destroco", "fx", "hover",
                    "ui",
                    "overlay"):
            self.cv.tag_raise(tag)

    def desenhar_cabecalho(self):
        cv = self.cv
        cv.create_text(CW / 2 + 2, 38, text="BATALHA NAVAL", fill="#0d6c8a",
                       font=(FONTE, 28, "bold"))
        cv.create_text(CW / 2, 36, text="BATALHA NAVAL", fill=TEXTO,
                       font=(FONTE, 28, "bold"))
        if self.nome_op:
            sub = f"{self.meu_nome}   vs   {self.nome_op}"
        else:
            sub = f"Capitão {self.meu_nome}"
        cv.create_text(CW / 2, 68, text=sub, fill=SUAVE,
                       font=(FONTE, 12, "bold"))
        fundo = ret_arredondado(cv, CW / 2 - 240, 84, CW / 2 + 240, 118, 16,
                                fill="#06182b", outline=ACENTO, width=2)
        texto = cv.create_text(CW / 2, 101, text="", fill=TEXTO,
                               font=(FONTE, 13, "bold"))
        self.banner = (fundo, texto)
        self.atualizar_banner()
        self.botao_tela_cheia(CW - 90, 30)

    def atualizar_banner(self):
        if not self.banner:
            return
        e = self.estado
        if self.aviso == "sem_oponente":
            t, cor = "O oponente saiu da partida", PERIGO
        elif self.aviso == "desconectado":
            t, cor = "Sem conexão com o servidor", PERIGO
        elif e == "aguardando":
            t, cor = "Procurando oponente na rede...", ALERTA
        elif e == "posicionando":
            t, cor = "Posicione sua frota", ACENTO
        elif e == "pronto":
            t, cor = "Aguardando o oponente...", ALERTA
        elif e == "jogando":
            if self.minha_vez:
                t, cor = "SUA VEZ  -  ESCOLHA UM ALVO!", OK
            else:
                t, cor = f"Vez de {self.nome_op}...", ALERTA
        else:
            t, cor = (("VITÓRIA!", OK) if self.vitoria
                      else ("DERROTA", PERIGO))
        self.cor_banner = cor
        self.cv.itemconfig(self.banner[1], text=t, fill=cor)
        self.cv.itemconfig(self.banner[0], outline=cor)

    # ------------------------------------------------------------------
    def desenhar_tabuleiro(self, ox, chave, titulo):
        cv = self.cv
        cv.create_text(ox + 5 * C, OY - 38, text=titulo, fill=TEXTO,
                       font=(FONTE, 13, "bold"))
        cv.create_rectangle(ox - 5, OY - 5, ox + 10 * C + 5, OY + 10 * C + 5,
                            outline="#0b3a66", width=6)
        cv.create_rectangle(ox - 2, OY - 2, ox + 10 * C + 2, OY + 10 * C + 2,
                            outline=BORDA_CARD, width=2)
        for i in range(TAMANHO):
            cv.create_text(ox + i * C + C / 2, OY - 13, text=str(i + 1),
                           fill=SUAVE, font=(FONTE, 10, "bold"))
            cv.create_text(ox - 15, OY + i * C + C / 2, text=LETRAS[i],
                           fill=SUAVE, font=(FONTE, 10, "bold"))
        for l in range(TAMANHO):
            for c in range(TAMANHO):
                x0, y0 = ox + c * C, OY + l * C
                self.ids_celulas.append(cv.create_rectangle(
                    x0, y0, x0 + C, y0 + C, fill=random.choice(OCEANO),
                    outline=GRADE, tags=("celula", chave)))

    def desenhar_navio(self, ox, tam, l, c, o, estilo="normal", tag="navio"):
        cv = self.cv
        casco, borda, conves, det = ESTILOS_NAVIO[estilo]
        m, comp, hw = self.mapa_navio(ox, tam, l, c, o)

        def poli(pontos, **kw):
            pts = [k for p in pontos for k in m(*p)]
            return cv.create_polygon(pts, tags=("navio", tag), **kw)

        extra = {"dash": (5, 3)} if estilo == "naufragio" else {}
        poli([(0, -hw * .75), (5, -hw), (comp - 18, -hw), (comp, 0),
              (comp - 18, hw), (5, hw), (0, hw * .75)],
             fill=casco, outline=borda, width=2, **extra)
        poli([(6, -hw * .45), (comp - 22, -hw * .45), (comp - 10, 0),
              (comp - 22, hw * .45), (6, hw * .45)], fill=conves, outline="")
        ponte = int(tam * 0.4)
        if tam == 5:      
            a, b = m(10, 0), m(comp - 24, 0)
            cv.create_line(*a, *b, fill="#d9e2ea", dash=(6, 4), width=1,
                           tags=("navio", tag))
            poli([(ponte * C, -hw + 1), (ponte * C + 26, -hw + 1),
                  (ponte * C + 26, -hw * .3), (ponte * C, -hw * .3)],
                 fill=det, outline=borda)
            return
        poli([(ponte * C + 4, -hw * .55), (ponte * C + C - 10, -hw * .55),
              (ponte * C + C - 10, hw * .55), (ponte * C + 4, hw * .55)],
             fill=det, outline=borda)
        for i in range(tam):
            if i == ponte:
                continue
            u = i * C + C / 2 - 4
            x, y = m(u, 0)
            cv.create_oval(x - 4.5, y - 4.5, x + 4.5, y + 4.5, fill=det,
                           outline=borda, tags=("navio", tag))
            x2, y2 = m(u + (9 if i > ponte else -9), 0)
            cv.create_line(x, y, x2, y2, fill=borda, width=2,
                           tags=("navio", tag))

    @staticmethod
    def mapa_navio(ox, tam, l, c, o):
        comp, hw = tam * C - 8, (C - 14) / 2
        if o == "H":
            bx, by = ox + c * C + 4, OY + l * C + C / 2
            return (lambda u, v: (bx + u, by + v)), comp, hw
        bx, by = ox + c * C + C / 2, OY + l * C + 4
        return (lambda u, v: (bx + v, by + u)), comp, hw

    def desenhar_meus_navios(self):
        self.cv.delete("navio_meu")
        if self.estado == "posicionando":
            for i, pos in enumerate(self.posicionados):
                if pos:
                    self.desenhar_navio(OX_MEU, FROTA[i][1], *pos,
                                        "normal", "navio_meu")
        else:
            for n in self.meus_navios:
                self.desenhar_navio(OX_MEU, n["tam"], n["l"], n["c"], n["o"],
                                    "naufragio" if n["afundado"] else "normal",
                                    "navio_meu")

    def celulas_afundadas(self, tab):
        cel = set()
        if tab == "meu":
            for n in self.meus_navios:
                if n["afundado"]:
                    cel |= n["cel"]
        else:
            for info in self.ini_afundados:
                cel.update(celulas_navio(*info))
        return cel

    def afundar(self, tab, info, estilo_inicial):

        ox = OX_MEU if tab == "meu" else OX_INI
        tam, l, c, o = info
        m, comp, hw = self.mapa_navio(ox, tam, l, c, o)
        casco, borda, conves, _ = ESTILOS_NAVIO[estilo_inicial]
        meio = comp / 2
        formas = {
            "popa": ([(0, -hw * .75), (5, -hw), (meio + 3, -hw),
                      (meio - 3, -hw * .3), (meio + 4, hw * .2),
                      (meio - 1, hw), (5, hw), (0, hw * .75)],
                     [(6, -hw * .45), (meio - 4, -hw * .45),
                      (meio - 1, hw * .1), (meio - 4, hw * .45),
                      (6, hw * .45)], -1),
            "proa": ([(meio + 3, -hw), (comp - 18, -hw), (comp, 0),
                      (comp - 18, hw), (meio - 1, hw), (meio + 4, hw * .2),
                      (meio - 3, -hw * .3)],
                     [(meio + 5, -hw * .45), (comp - 22, -hw * .45),
                      (comp - 10, 0), (comp - 22, hw * .45),
                      (meio + 5, hw * .45), (meio + 7, 0)], 1),
        }
        eixo = (1, 0) if o == "H" else (0, 1)
        pecas = []
        for nome, (cas, dec, sentido) in formas.items():
            pts_c = [m(*p) for p in cas]
            pts_d = [m(*p) for p in dec]
            cx = sum(p[0] for p in pts_c) / len(pts_c)
            cy = sum(p[1] for p in pts_c) / len(pts_c)
            ids = []
            for pts, fill, out in ((pts_c, casco, borda),
                                   (pts_d, conves, "")):
                pid = self.cv.create_polygon(
                    [k for p in pts for k in p], fill=fill,
                    outline=out, width=2, tags="destroco")
                ids.append(dict(id=pid, pts=pts, fill=fill, out=out))
            pecas.append(dict(ids=ids, cx=cx, cy=cy, sentido=sentido))

        celulas = celulas_navio(tam, l, c, o)
        for i, (a, b) in enumerate(celulas):   
            cx, cy = ox + b * C + C / 2, OY + a * C + C / 2
            self.explosao(cx, cy, grande=False, atraso=i * 3, destrocos=True)
        self.naufragios.append(dict(
            tab=tab, pecas=pecas, celulas=celulas, eixo=eixo, t=0,
            atraso=len(celulas) * 3 + 4, dur=55, quebra=m(meio, 0)))
        self.ordenar_camadas()

    def animar_naufragios(self):
        cv, vivos = self.cv, []
        for nf in self.naufragios:
            nf["t"] += 1
            t = nf["t"] - nf["atraso"]
            if t < 0:                     
                quente = (nf["t"] // 2) % 2 == 0
                for pc in nf["pecas"]:
                    for it in pc["ids"]:
                        cv.itemconfig(it["id"], fill="#ff7a1a" if quente
                                      and it["out"] else it["fill"])
                vivos.append(nf)
                continue
            if t == 0:                  
                self.explosao(*nf["quebra"], grande=True, destrocos=True)
                if nf["tab"] == "meu":
                    self.shake = 18
                ox = OX_MEU if nf["tab"] == "meu" else OX_INI
                for (a, b) in nf["celulas"]:
                    cx, cy = ox + b * C + C / 2, OY + a * C + C / 2
                    self.apagar_chama(nf["tab"], a, b)
                    for _ in range(2):
                        self.fumaca(cx, cy, vapor=True)
            k = t / nf["dur"]
            if k >= 1:                  
                for pc in nf["pecas"]:
                    for it in pc["ids"]:
                        cv.delete(it["id"])
                continue
            ease = 1 - (1 - k) ** 2
            for pc in nf["pecas"]:
                ang = pc["sentido"] * 0.75 * ease
                esc = 1 - 0.6 * ease
                dx = nf["eixo"][0] * pc["sentido"] * 16 * ease
                dy = nf["eixo"][1] * pc["sentido"] * 16 * ease
                co, si = math.cos(ang), math.sin(ang)
                for it in pc["ids"]:
                    novos = []
                    for (x, y) in it["pts"]:
                        rx, ry = (x - pc["cx"]) * esc, (y - pc["cy"]) * esc
                        novos += [pc["cx"] + rx * co - ry * si + dx,
                                  pc["cy"] + rx * si + ry * co + dy]
                    cv.coords(it["id"], *novos)
                    cv.itemconfig(it["id"],
                                  fill=misturar(it["fill"], OCEANO[2], k))
                    if it["out"]:
                        cv.itemconfig(it["id"], outline=misturar(
                            it["out"], OCEANO[2], k))
                if random.random() < 0.6:
                    self.nova_particula(
                        "anel", pc["cx"] + random.uniform(-14, 14) + dx,
                        pc["cy"] + random.uniform(-14, 14) + dy, vida=14,
                        r=1, r1=random.uniform(4, 8), c0="#cdeeff",
                        c1=OCEANO[2], largura=1)
            vivos.append(nf)
        self.naufragios = vivos

    def marcar(self, tab, l, c, res, animar=False):
        cv = self.cv
        ox = OX_MEU if tab == "meu" else OX_INI
        cx, cy = ox + c * C + C / 2, OY + l * C + C / 2
        if res == "MISS":
            cv.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline="#9fd3f7",
                           width=2, tags="marca")
            cv.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#e6f6ff",
                           outline="", tags="marca")
            if animar:
                self.respingo(cx, cy)
        else:
            if tab == "ini":
                cv.create_rectangle(cx - C / 2 + 3, cy - C / 2 + 3,
                                    cx + C / 2 - 3, cy + C / 2 - 3,
                                    outline="#ff6a3d", width=2,
                                    tags="marca")
            cv.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#1d0d08",
                           outline=PERIGO, width=2, tags="marca")
            if animar or (l, c) not in self.celulas_afundadas(tab):
                self.criar_chama(tab, l, c, cx, cy)
            if animar:
                self.explosao(cx, cy, grande=res == "SUNK", destrocos=True)
                if tab == "meu":
                    self.shake = 12

    # ------------------------------------------------------------------
    def desenhar_painel_frota(self, tab):
        cv = self.cv
        t = f"painel_{tab}"
        cv.delete(t)
        ox = OX_MEU if tab == "meu" else OX_INI
        y0 = OY + 10 * C + 22
        ret_arredondado(cv, ox - 6, y0, ox + 10 * C + 6, y0 + 112, 14,
                        fill="#051525", outline="#123e66", width=1, tags=t)
        if tab == "meu":
            if self.estado == "posicionando":
                vivos = sum(1 for p in self.posicionados if p)
                titulo = f"NAVIOS POSICIONADOS: {vivos}/{len(FROTA)}"
                afundado = [False] * len(FROTA)
            else:
                afundado = [n["afundado"] for n in self.meus_navios]
                titulo = (f"SEUS NAVIOS: {afundado.count(False)}/"
                          f"{len(FROTA)} à tona")
        else:
            if self.estado in ("posicionando", "pronto"):
                st = ("pronto para a batalha" if self.op_pronto or
                      self.estado == "jogando" else "posicionando a frota...")
                titulo = f"{self.nome_op.upper()}: {st}"
                afundado = [False] * len(FROTA)
            else:
                afundado = [i in self.ini_idx_afundados
                            for i in range(len(FROTA))]
                titulo = (f"FROTA INIMIGA: {afundado.count(False)}/"
                          f"{len(FROTA)} à tona")
        cv.create_text(ox + 6, y0 + 16, text=titulo, anchor="w", fill=SUAVE,
                       font=(FONTE, 10, "bold"), tags=t)
        for i, (nome, tam) in enumerate(FROTA):
            col, lin = (0, i) if i < 3 else (1, i - 3)
            x, y = ox + 8 + col * 200, y0 + 42 + lin * 26
            self.mini_navio(x, y, tam, afundado[i], t)
            cv.create_text(x + 84, y, text=nome, anchor="w",
                           fill="#7a4a44" if afundado[i] else TEXTO,
                           font=(FONTE, 10, "overstrike" if afundado[i]
                                 else "normal"), tags=t)

    def mini_navio(self, x, y, tam, afundado, tag):
        cv = self.cv
        L, h = tam * 15, 10
        pts = [x, y - h / 2 + 1, x + 3, y - h / 2, x + L - 7, y - h / 2,
               x + L, y, x + L - 7, y + h / 2, x + 3, y + h / 2, x,
               y + h / 2 - 1]
        cv.create_polygon(pts, fill="#3a2622" if afundado else "#8796a5",
                          outline=PERIGO if afundado else "#c9d6e2",
                          tags=tag)
        if afundado:
            cv.create_line(x - 2, y - 6, x + L + 2, y + 6, fill=PERIGO,
                           width=2, tags=tag)

    # ------------------------------------------------------------------
    def desenhar_painel_posicionamento(self):
        cv, t = self.cv, "ui"
        x0, y0, x1, y1 = OX_INI - 6, OY - 50, OX_INI + 10 * C + 6, OY + 392
        ret_arredondado(cv, x0, y0, x1, y1, 18, fill=CARD,
                        outline=BORDA_CARD, width=2, tags=t)
        cx = (x0 + x1) / 2
        cv.create_text(cx, y0 + 26, text="POSICIONE SUA FROTA", fill=TEXTO,
                       font=(FONTE, 14, "bold"), tags=t)
        atual = self.proximo_navio()
        for i, (nome, tam) in enumerate(FROTA):
            y = y0 + 66 + i * 38
            if i == atual:
                ret_arredondado(cv, x0 + 14, y - 16, x1 - 14, y + 16, 10,
                                fill="#0b3550", outline=ACENTO, tags=t)
            feito = self.posicionados[i] is not None
            L = tam * 18
            pts = [x0 + 30, y - 6, x0 + 30 + L - 9, y - 6, x0 + 30 + L, y,
                   x0 + 30 + L - 9, y + 6, x0 + 30, y + 6]
            cv.create_polygon(pts, fill="#1c7f78" if i == atual else
                              ("#8796a5" if feito else "#34475a"),
                              outline=ACENTO if i == atual else "#9fb0c0",
                              tags=t)
            cv.create_text(x0 + 130, y, anchor="w", tags=t,
                           text=f"{nome}  ({tam})",
                           fill=TEXTO if not feito else SUAVE,
                           font=(FONTE, 11, "bold" if i == atual else
                                 "normal"))
            estado = ("pronto" if feito else ("◄ agora" if i == atual else ""))
            cv.create_text(x1 - 28, y, anchor="e", text=estado, tags=t,
                           fill=OK if feito else ACENTO,
                           font=(FONTE, 11, "bold"))
        yi = y0 + 268
        cv.create_text(cx, yi, fill=SUAVE, font=(FONTE, 10), justify="center",
                       tags=t,
                       text="Clique na sua grade para posicionar o navio.\n"
                            "Botão direito ou tecla R: girar.\n"
                            "Clique num navio posicionado para movê-lo.")
        cv.create_text(cx, yi + 44, tags=t, fill=ACENTO,
                       font=(FONTE, 10, "bold"),
                       text="Orientação: " + ("HORIZONTAL ↔" if
                                             self.orient == "H" else
                                             "VERTICAL ↕"))
        yb = y1 - 70
        Botao(cv, cx - 120, yb, 108, 32, "GIRAR", self.girar, tamanho=10)
        Botao(cv, cx, yb, 108, 32, "ALEATÓRIO", self.aleatorio, tamanho=10)
        Botao(cv, cx + 120, yb, 108, 32, "LIMPAR", self.limpar,
              cor=ALERTA, tamanho=10)
        b = Botao(cv, cx, yb + 44, 348, 38, "PRONTO PARA A BATALHA!",
                  self.confirmar_frota, cor=OK, tamanho=12)
        b.habilitar(atual is None)
        self.desenhar_painel_frota("ini")

    def proximo_navio(self):
        for i, p in enumerate(self.posicionados):
            if p is None:
                return i
        return None

    def ocupadas(self, exceto=None):
        s = set()
        for i, p in enumerate(self.posicionados):
            if p and i != exceto:
                s.update(celulas_navio(FROTA[i][1], *p))
        return s

    def girar(self):
        if self.estado != "posicionando":
            return
        self.orient = "V" if self.orient == "H" else "H"
        self.redesenhar()

    def aleatorio(self):
        navios = frota_aleatoria()      
        self.posicionados = [(l, c, o) for (_, l, c, o) in navios]
        self.redesenhar()

    def limpar(self):
        self.posicionados = [None] * len(FROTA)
        self.redesenhar()

    def confirmar_frota(self):
        if self.proximo_navio() is not None:
            return
        navios = [(FROTA[i][1], *p) for i, p in enumerate(self.posicionados)]
        self.meus_navios = [dict(tam=t, l=l, c=c, o=o, hit=set(),
                                 afundado=False,
                                 cel=set(celulas_navio(t, l, c, o)))
                            for (t, l, c, o) in navios]
        self.con.enviar("PLACE", codificar_frota(navios))

    # ------------------------------------------------------------------
    def celula_em(self, ev):
        x, y = self.cv.logico(ev)
        for tab, ox in (("meu", OX_MEU), ("ini", OX_INI)):
            if ox <= x < ox + TAMANHO * C and OY <= y < OY + TAMANHO * C:
                return tab, int((y - OY) // C), int((x - ox) // C)
        return None

    def ao_mover(self, ev):
        cv = self.cv
        cv.delete("hover")
        alvo = self.celula_em(ev)
        if self.aviso or not alvo:
            return
        tab, l, c = alvo
        if self.estado == "posicionando" and tab == "meu":
            i = self.proximo_navio()
            if i is None:
                return
            tam = FROTA[i][1]
            ok = cabe(tam, l, c, self.orient, self.ocupadas())
            if ok:
                self.desenhar_navio(OX_MEU, tam, l, c, self.orient, "ok",
                                    "hover")
            else:
                for (a, b) in celulas_navio(tam, l, c, self.orient):
                    if 0 <= a < TAMANHO and 0 <= b < TAMANHO:
                        x0, y0 = OX_MEU + b * C, OY + a * C
                        cv.create_rectangle(x0 + 2, y0 + 2, x0 + C - 2,
                                            y0 + C - 2, outline=PERIGO,
                                            width=2, tags="hover")
            cv.tag_raise("hover")
        elif (self.estado == "jogando" and tab == "ini" and self.minha_vez
              and not self.esperando_tiro and (l, c) not in self.tiros_meus):
            x0, y0 = OX_INI + c * C, OY + l * C
            cx, cy = x0 + C / 2, y0 + C / 2
            cv.create_rectangle(x0 + 1, y0 + 1, x0 + C - 1, y0 + C - 1,
                                outline=PERIGO, width=2, tags="hover")
            cv.create_oval(cx - 12, cy - 12, cx + 12, cy + 12,
                           outline="#ff8a7a", width=2, tags="hover")
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                cv.create_line(cx + dx * 6, cy + dy * 6, cx + dx * 17,
                               cy + dy * 17, fill="#ff8a7a", width=2,
                               tags="hover")
            cv.create_line(OX_INI, cy, OX_INI + 10 * C, cy, fill=PERIGO,
                           dash=(2, 4), tags="hover")
            cv.create_line(cx, OY, cx, OY + 10 * C, fill=PERIGO, dash=(2, 4),
                           tags="hover")
            cv.create_text(x0 + C + 4, y0 - 4, anchor="sw", tags="hover",
                           text=nome_celula(l, c), fill="#ffd2cc",
                           font=(FONTE, 11, "bold"))
            cv.tag_raise("hover")

    def ao_clicar(self, ev):
        self.cv.focus_set()
        alvo = self.celula_em(ev)
        if self.aviso or not alvo:
            return
        tab, l, c = alvo
        if self.estado == "posicionando" and tab == "meu":
            for i, p in enumerate(self.posicionados):    
                if p and (l, c) in celulas_navio(FROTA[i][1], *p):
                    self.posicionados[i] = None
                    self.orient = p[2]
                    self.redesenhar()
                    return
            i = self.proximo_navio()
            if i is not None and cabe(FROTA[i][1], l, c, self.orient,
                                      self.ocupadas()):
                self.posicionados[i] = (l, c, self.orient)
                self.redesenhar()
        elif self.estado == "jogando" and tab == "ini":
            if (self.minha_vez and not self.esperando_tiro
                    and (l, c) not in self.tiros_meus):
                self.esperando_tiro = True
                self.cv.delete("hover")
                self.con.enviar("FIRE", l, c)

    # ------------------------------------------------------------------
    def desenhar_fim(self):
        cv, t = self.cv, "ui"
        y0, y1 = OY + 10 * C + 22, OY + 10 * C + 134
        x0, x1 = OX_MEU - 6, OX_INI + 10 * C + 6
        cor = OK if self.vitoria else PERIGO
        ret_arredondado(cv, x0, y0, x1, y1, 16, fill=CARD, outline=cor,
                        width=3, tags=t)
        cv.create_text(x0 + 30, y0 + 40, anchor="w", tags=t, fill=cor,
                       font=(FONTE, 30, "bold"),
                       text="VITÓRIA!" if self.vitoria else "DERROTA")
        tiros = len(self.tiros_meus)
        acertos = sum(1 for r in self.tiros_meus.values() if r != "MISS")
        prec = 100 * acertos / tiros if tiros else 0
        cv.create_text(x0 + 30, y0 + 80, anchor="w", tags=t, fill=SUAVE,
                       font=(FONTE, 11),
                       text=f"Tiros: {tiros}    Acertos: {acertos}    "
                            f"Precisão: {prec:.0f}%")
        if self.op_quer_revanche and not self.pedi_revanche:
            cv.create_text(x0 + 30, y0 + 100, anchor="w", tags=t,
                           fill=ALERTA, font=(FONTE, 10, "bold"),
                           text=f"{self.nome_op} quer revanche!")
        b = Botao(cv, x1 - 290, (y0 + y1) / 2, 180, 44,
                  "AGUARDANDO..." if self.pedi_revanche else "REVANCHE",
                  self.revanche, cor=OK)
        if self.pedi_revanche:
            b.habilitar(False)
        Botao(cv, x1 - 100, (y0 + y1) / 2, 170, 44, "NOVO OPONENTE",
              self.novo_oponente, cor=ALERTA, tamanho=11)

    def revanche(self):
        self.pedi_revanche = True
        self.con.enviar("REMATCH")
        self.registrar("Pedido de revanche enviado.")
        self.redesenhar()

    def novo_oponente(self):
        self.nome_op = ""
        self.aviso = None
        self.novo_jogo()
        self.con.enviar("FIND")

    def desenhar_aviso(self):
        cv, t = self.cv, "overlay"
        if self.root.tk.call("tk", "windowingsystem") != "aqua":
            cv.create_rectangle(0, 0, CW, CH, fill="#000000",
                                stipple="gray50", outline="", tags=t)
        x0, y0, x1, y1 = CW / 2 - 230, 250, CW / 2 + 230, 470
        ret_arredondado(cv, x0, y0, x1, y1, 20, fill=CARD, outline=PERIGO,
                        width=3, tags=t)
        if self.aviso == "sem_oponente":
            titulo = "O OPONENTE SAIU"
            texto = f"{self.nome_op or 'O oponente'} deixou a partida."
            botoes = [("PROCURAR OUTRO", self.novo_oponente, OK),
                      ("MENU", self.voltar_menu, ALERTA)]
        else:
            titulo = "CONEXÃO PERDIDA"
            texto = "O servidor não está respondendo."
            botoes = [("VOLTAR AO MENU", self.voltar_menu, ALERTA)]
        cv.create_text(CW / 2, y0 + 48, text=titulo, fill=PERIGO,
                       font=(FONTE, 22, "bold"), tags=t)
        cv.create_text(CW / 2, y0 + 92, text=texto, fill=TEXTO,
                       font=(FONTE, 12), tags=t)
        n = len(botoes)
        for k, (txt, cmd, cor) in enumerate(botoes):
            x = CW / 2 + (k - (n - 1) / 2) * 200
            Botao(cv, x, y1 - 52, 180, 44, txt, cmd, cor=cor, tag=t)

    def voltar_menu(self):
        if self.con:
            self.con.fechar()
        self.con_id += 1
        self.nome_op, self.aviso = "", None
        self.novo_jogo()
        self.tela_conexao()

    # ==================================================================
    # Efeitos visuais
    # ==================================================================
    def desenhar_radar(self, cx, cy, r):
        cv, t = self.cv, "ui"
        cv.create_oval(cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8,
                       fill="#04201f", outline="#0f5a55", width=3, tags=t)
        for k in (1, 2, 3):
            rr = r * k / 3
            cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                           outline="#127068", tags=t)
        cv.create_line(cx - r, cy, cx + r, cy, fill="#127068", tags=t)
        cv.create_line(cx, cy - r, cx, cy + r, fill="#127068", tags=t)
        linhas = []
        for k in range(22):
            cor = misturar("#7ffff0", "#04201f", k / 22)
            linhas.append(cv.create_line(cx, cy, cx, cy, fill=cor,
                                         width=3 if k == 0 else 2, tags=t))
        self.radar = dict(cx=cx, cy=cy, r=r, ang=0.0, linhas=linhas)

    def animar_radar(self):
        rd = self.radar
        rd["ang"] += 0.07
        for k, lid in enumerate(rd["linhas"]):
            a = rd["ang"] - k * 0.03
            self.cv.coords(lid, rd["cx"], rd["cy"],
                           rd["cx"] + rd["r"] * math.cos(a),
                           rd["cy"] + rd["r"] * math.sin(a))
        if random.random() < 0.06:
            a = rd["ang"] - 0.1
            d = random.uniform(0.25, 0.9) * rd["r"]
            x, y = rd["cx"] + d * math.cos(a), rd["cy"] + d * math.sin(a)
            self.nova_particula("blip", x, y, vida=40, r=4, c0="#9ffff4",
                                c1="#04201f")

    def nova_particula(self, tipo, x, y, vx=0, vy=0, g=0, vida=20, r=3,
                       r1=None, c0="#ffffff", c1="#000000", atraso=0,
                       largura=2):
        cv = self.cv
        if tipo == "anel":
            pid = cv.create_oval(x, y, x, y, outline=c0, width=largura,
                                 tags="fx", state="hidden" if atraso else
                                 "normal")
        else:
            pid = cv.create_oval(x - r, y - r, x + r, y + r, fill=c0,
                                 outline="", tags="fx",
                                 state="hidden" if atraso else "normal")
        self.particulas.append(dict(id=pid, tipo=tipo, x=x, y=y, vx=vx,
                                    vy=vy, g=g, vida=vida, t=0, r=r,
                                    r1=r1 if r1 is not None else r, c0=c0,
                                    c1=c1, atraso=atraso))

    def explosao(self, cx, cy, grande=False, atraso=0,
                 cores=("#fff3b0", "#ff8c00"), destrocos=False):
        self.nova_particula("anel", cx, cy, vida=12, r=4,
                            r1=38 if grande else 24, c0="#fff6c0",
                            c1=FUNDO2, atraso=atraso, largura=3)
        self.nova_particula("nucleo", cx, cy, vida=7, r=16 if grande else 12,
                            r1=2, c0=cores[0], c1=cores[1], atraso=atraso)
        for _ in range(28 if grande else 16):
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(1.5, 6.5 if grande else 5)
            self.nova_particula("faisca", cx, cy, vx=v * math.cos(a),
                                vy=v * math.sin(a) - 1.5, g=0.25,
                                vida=random.randint(12, 24),
                                r=random.uniform(1.5, 3), c0=cores[0],
                                c1="#5a0d05", atraso=atraso)
        if destrocos:                       
            for _ in range(10 if grande else 6):
                a = random.uniform(0, 2 * math.pi)
                v = random.uniform(1, 3.5)
                self.nova_particula("faisca", cx, cy, vx=v * math.cos(a),
                                    vy=v * math.sin(a) - 2, g=0.2,
                                    vida=random.randint(18, 28),
                                    r=random.uniform(2.5, 4), r1=1.5,
                                    c0="#9aa8b5", c1="#1a2633",
                                    atraso=atraso)

    def respingo(self, cx, cy):
        for k in range(3):
            self.nova_particula("anel", cx, cy, vida=16, r=3, r1=20,
                                c0="#e6f6ff", c1=OCEANO[2], atraso=k * 4)
        for _ in range(9):
            a = random.uniform(-math.pi, 0)
            v = random.uniform(1.5, 3.5)
            self.nova_particula("faisca", cx, cy, vx=v * math.cos(a),
                                vy=v * math.sin(a) - 1.5, g=0.3,
                                vida=random.randint(10, 16), r=2,
                                c0="#ffffff", c1=OCEANO[2])

    def fumaca(self, x, y, grande=False, vapor=False):
        if vapor:                          
            self.nova_particula("fumaca", x + random.uniform(-6, 6), y,
                                vx=random.uniform(-0.4, 0.4),
                                vy=-random.uniform(0.8, 1.6), vida=28, r=4,
                                r1=12, c0="#e8f2fa", c1=OCEANO[2])
            return
        self.nova_particula("fumaca", x + random.uniform(-3, 3), y,
                            vx=random.uniform(0.2, 0.9) if grande else
                            random.uniform(-0.2, 0.2),
                            vy=-random.uniform(0.6, 1.2), vida=50 if grande
                            else 30, r=4 if grande else 3,
                            r1=16 if grande else 9, c0="#6b6f75",
                            c1="#10263d" if grande else FUNDO2)

    def criar_chama(self, tab, l, c, cx, cy):
        ids = [self.cv.create_oval(cx, cy, cx, cy, fill=cor, outline="",
                                   tags="chama")
               for cor in ("#ff3b1f", "#ff8c00", "#ffe066")]
        self.chamas[(tab, l, c)] = dict(ids=ids, cx=cx, cy=cy, fraca=False)

    def apagar_chama(self, tab, l, c):
        ch = self.chamas.pop((tab, l, c), None)
        if ch:
            for i in ch["ids"]:
                self.cv.delete(i)

    def enfraquecer_chama(self, tab, l, c):
        if (tab, l, c) in self.chamas:
            self.chamas[(tab, l, c)]["fraca"] = True

    def animar_chamas(self):
        for ch in self.chamas.values():
            f = 0.5 if ch["fraca"] else 1.0
            cx, cy = ch["cx"], ch["cy"]
            for k, i in enumerate(ch["ids"]):
                r = (10 - k * 3) * f * random.uniform(0.8, 1.15)
                dx = random.uniform(-1.2, 1.2)
                up = (k * 2.5 + 2) * f
                self.cv.coords(i, cx - r + dx, cy - r * 1.5 - up,
                               cx + r + dx, cy + r * 0.7 - up)

    def animar_particulas(self):
        cv, vivas = self.cv, []
        for p in self.particulas:
            if p["atraso"] > 0:
                p["atraso"] -= 1
                if p["atraso"] == 0:
                    cv.itemconfig(p["id"], state="normal")
                vivas.append(p)
                continue
            p["t"] += 1
            t = p["t"] / p["vida"]
            if t >= 1:
                cv.delete(p["id"])
                continue
            cor = misturar(p["c0"], p["c1"], t)
            r = p["r"] + (p["r1"] - p["r"]) * t
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += p["g"]
            x, y = p["x"], p["y"]
            cv.coords(p["id"], x - r, y - r, x + r, y + r)
            if p["tipo"] == "anel":
                cv.itemconfig(p["id"], outline=cor)
            else:
                cv.itemconfig(p["id"], fill=cor)
            vivas.append(p)
        self.particulas = vivas

    def animar(self):
        self.tick += 1
        try:
            if self.estado == "conexao":
                self.animar_capa()
            else:
                if self.tick % 2 == 0 and self.ids_celulas:
                    for _ in range(12):
                        self.cv.itemconfig(random.choice(self.ids_celulas),
                                           fill=random.choice(OCEANO))
                if self.tick % 2 == 0:
                    self.animar_chamas()
                if self.chamas and self.tick % 4 == 0 and \
                        len(self.particulas) < 250:
                    ch = random.choice(list(self.chamas.values()))
                    self.fumaca(ch["cx"], ch["cy"] - 10)
                if self.naufragios:
                    self.animar_naufragios()
                if self.radar:
                    self.animar_radar()
                if self.banner and self.estado == "jogando" and \
                        self.minha_vez:
                    t = (math.sin(self.tick * 0.15) + 1) / 2
                    self.cv.itemconfig(self.banner[0],
                                       fill=misturar("#06182b", "#0d3b2a", t))
                if self.fogos and self.tick % 9 == 0:
                    self.fogos -= 1
                    cor = random.choice(("#ffe066", "#2ee6d6", "#3ddc84",
                                         "#ff6ad5", "#ffffff"))
                    self.explosao(random.uniform(80, CW - 80),
                                  random.uniform(150, 520), grande=True,
                                  cores=(cor, cor))
            if self.shake > 0:
                self.shake -= 1
                s = self.shake // 2
                novo = ((random.randint(-s, s), random.randint(-s, s))
                        if s else (0, 0))
                self.deslocar_vista(novo)
            self.animar_particulas()
        except tk.TclError:
            pass
        self.root.after(40, self.animar)

    def deslocar_vista(self, novo):
        dx, dy = novo[0] - self.vista[0], novo[1] - self.vista[1]
        if dx:
            self.cv.xview_scroll(dx, "units")
        if dy:
            self.cv.yview_scroll(dy, "units")
        self.vista = novo

    # ------------------------------------------------------------------
    def fechar(self):
        if self.con:
            self.con.fechar()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Cliente da Batalha Naval")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--nome", default="")
    args = ap.parse_args()
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
