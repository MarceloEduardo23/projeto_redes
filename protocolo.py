import random

PORTA_PADRAO = 5000
TAMANHO = 10                     
LETRAS = "ABCDEFGHIJ"
MAX_BUFFER = 64 * 1024            

FROTA = [
    ("Porta-aviões", 5),
    ("Encouraçado", 4),
    ("Cruzador", 3),
    ("Submarino", 3),
    ("Destróier", 2),
]


# ----------------------------------------------------------------------
# Envio / recepção de mensagens
# ----------------------------------------------------------------------
def montar(*partes):
    limpos = [str(p).replace("|", "/").replace("\n", " ").replace("\r", " ")
              for p in partes]
    return ("|".join(limpos) + "\n").encode("utf-8")


def ler_mensagens(sock):
    buffer = b""
    while True:
        try:
            dados = sock.recv(4096)
        except OSError:
            return
        if not dados:                 
            return
        buffer += dados
        if len(buffer) > MAX_BUFFER and b"\n" not in buffer:
            return                    
        while b"\n" in buffer:
            linha, buffer = buffer.split(b"\n", 1)
            texto = linha.decode("utf-8", errors="replace").strip("\r")
            if texto:
                yield texto.split("|")


# ----------------------------------------------------------------------
# Regras do tabuleiro
# ----------------------------------------------------------------------
def celulas_navio(tam, l, c, o):
    if o == "H":
        return [(l, c + i) for i in range(tam)]
    return [(l + i, c) for i in range(tam)]


def cabe(tam, l, c, o, ocupadas):
    for (a, b) in celulas_navio(tam, l, c, o):
        if not (0 <= a < TAMANHO and 0 <= b < TAMANHO):
            return False
        if (a, b) in ocupadas:
            return False
    return True


def codificar_frota(navios):
    return ";".join(f"{t},{l},{c},{o}" for (t, l, c, o) in navios)


def decodificar_frota(texto):
    navios = []
    for parte in texto.split(";"):
        t, l, c, o = parte.split(",")
        navios.append((int(t), int(l), int(c), o.strip().upper()))
    return navios


def validar_frota(navios):
    esperados = sorted(t for _, t in FROTA)
    if sorted(t for (t, _, _, _) in navios) != esperados:
        raise ValueError("Frota com navios incorretos")
    ocupadas = set()
    for (t, l, c, o) in navios:
        if o not in ("H", "V"):
            raise ValueError("Orientação inválida")
        if not cabe(t, l, c, o, ocupadas):
            raise ValueError("Navio fora do tabuleiro ou sobreposto")
        ocupadas.update(celulas_navio(t, l, c, o))


def frota_aleatoria():
    while True:
        ocupadas, navios = set(), []
        ok = True
        for _, tam in FROTA:
            for _tentativa in range(200):
                o = random.choice("HV")
                l = random.randrange(TAMANHO)
                c = random.randrange(TAMANHO)
                if cabe(tam, l, c, o, ocupadas):
                    navios.append((tam, l, c, o))
                    ocupadas.update(celulas_navio(tam, l, c, o))
                    break
            else:
                ok = False
                break
        if ok:
            return navios


def nome_celula(l, c):
    return f"{LETRAS[l]}{c + 1}"
