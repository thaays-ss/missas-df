"""
Parser de horários em texto livre (português) -> linhas estruturadas.

Exemplo:
  "Terça a Sexta: 17h às 19h Sábado: 9h30 às 11h"
  -> [(Ter,17:00,19:00), (Qua,...), (Qui,...), (Sex,...), (Sab,09:30,11:00)]

Ideia: varrer o texto como uma sequência de "tokens" (dia, horário, local,
marcador mensal) e usar uma pequena máquina de estados:
  - dias consecutivos formam um grupo ("terça a sexta", "terça, quinta e sexta")
  - horários depois do grupo valem para todos os dias do grupo
  - um novo dia depois de horários abre um grupo novo
  - "Capela X" / "Matriz" mudam o local corrente
  - trechos com "do mês" / "de cada mês" são eventos mensais -> ignorados
"""
import re
from unidecode import unidecode

DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"]

# padrões de dia (texto já sem acento e minúsculo)
DIA_PAT = [
    (r"\bsegunda(?:s)?(?:[\s-]*feiras?)?\b|\bseg\b|\b2[ªa]\b", "Seg"),
    (r"\bterca(?:s)?(?:[\s-]*feiras?)?\b|\bter\b|\b3[ªa]\b", "Ter"),
    (r"\bquarta(?:s)?(?:[\s-]*feiras?)?\b|\bqua\b|\b4[ªa]\b", "Qua"),
    (r"\bquinta(?:s)?(?:[\s-]*feiras?)?\b|\bqui\b|\b5[ªa]\b", "Qui"),
    (r"\bsexta(?:s)?(?:[\s-]*feiras?)?\b|\bsex\b|\b6[ªa]\b", "Sex"),
    (r"\bsabados?\b|\bsab\b", "Sab"),
    (r"\bdomingos?\b|\bdom\b|\bdominicais\b", "Dom"),
]
TODOS = r"\btodos os dias\b|\bdiariamente\b"
FDS = r"\bfinais? de semana\b|\bfim de semana\b"

# horário: 7h, 7h30, 07:00, 19h:30, 19:00h, 18h30min
HORA = r"(?<![\d/.,])(?<!\d\d\d-)([01]?\d|2[0-3])\s*(?:h\s*:?\s*([0-5]\d)?|:\s*([0-5]\d))\s*(?:h|min)?(?![\d])"
# hora "nua" usada só como início de intervalo: "das 16 às 18h", "18-18h50"
HORA_NUA = r"(?<![\d/.,])(?<!\d\d\d-)([01]?\d|2[0-3])(?=\s*(?:-|–|as|a|ate)\s*[01]?\d\s*[h:])"
RANGE_SEP = r"^\s*(?:-|–|as|a|ate|ao|aos)\s*$"

MENSAL = r"\b[1-5][ºoªa]\s*(?:e|,)\s*[1-5][ºoªa]\b|(?:primeir[oa]|1[ºoªa]|ultim[oa]|segund[oa]|terceir[oa]|quart[oa]|4[ªa]|\d)\s*\w*[\s-]*(?:feira\s*)?(?:d[oe]\s+(?:cada\s+)?mes)|\bdia\s+\d{1,2}\s+(?:de\s+cada|do)\s+mes|todo\s+(?:o\s+)?dia\s+\d{1,2}|do mes\b|de cada mes\b"
LOCAL = r"\b(capela|igrejinha|matriz|comunidade|santuario:|paroquia:)\b"
RELATIVO = r"\b(apos|antes|depois|durante|na missa|nas missas)\b"


def _norm(t):
    t = (t or "").replace("&nbsp;", " ").replace("\xa0", " ")
    t = re.sub(r"[·●•*|;]", " , ", t)
    t = t.replace("0O", "00")
    t = unidecode(t).lower()
    return re.sub(r"\s+", " ", t).strip()


def _tokens(t):
    toks = []
    spans = []

    def add(kind, m, val):
        s, e = m.span()
        if any(not (e <= a or s >= b) for a, b in spans):
            return
        spans.append((s, e))
        toks.append((s, e, kind, val))

    for m in re.finditer(MENSAL, t):
        add("MENSAL", m, None)
    for m in re.finditer(TODOS, t):
        add("DIA", m, "ALL")
    for m in re.finditer(FDS, t):
        add("DIA", m, "FDS")
    for pat, d in DIA_PAT:
        for m in re.finditer(pat, t):
            add("DIA", m, d)
    for m in re.finditer(HORA, t):
        h = int(m.group(1)); mi = int(m.group(2) or m.group(3) or 0)
        add("HORA", m, f"{h:02d}:{mi:02d}")
    for m in re.finditer(HORA_NUA, t):
        add("HORA", m, f"{int(m.group(1)):02d}:00")
    for m in re.finditer(r"(?<![\d/.,:])\b([01]?\d|2[0-3])\b(?=\s+e\s+(?:as\s+)?[01]?\d\s*h)", t):
        add("HORA", m, f"{int(m.group(1)):02d}:00")
    for m in re.finditer(LOCAL, t):
        # nome do local: até 6 palavras ou até ":" / "-" / dia / hora
        rest = t[m.end():m.end() + 70]
        nome = re.split(r"[:(\-–,.;]|\b(?:segunda|terca|quarta|quinta|sexta|sabado|domingo|ter\b|qua\b|qui\b|sex\b|sab\b|dom\b|final|meio|missa|horario|as\b|na\b|todo|toda)|\d", rest)[0]
        nome = " ".join(nome.split()[:6]).strip(" ,.")
        add("LOCAL", m, (m.group(1).rstrip(":") + " " + nome).strip())
    for m in re.finditer(r"\badorac\w*|\bhora santa\b|\bsantissimo\b", t):
        add("ITEM", m, "Adoração")
    for m in re.finditer(r"\bmissas?\b|\bcelebrac\w*\b|\bconfiss\w*\b", t):
        add("ITEM", m, None)
    for m in re.finditer(RELATIVO, t):
        add("REL", m, m.group(1))
    toks.sort()
    return toks


def _expande(a, b):
    i, j = DIAS.index(a), DIAS.index(b)
    # semana começando na segunda: Seg..Dom
    ordem = DIAS[1:] + DIAS[:1]
    i, j = ordem.index(a), ordem.index(b)
    if j < i:
        return [a, b]
    return ordem[i:j + 1]


def parse(texto, modo="confissao"):
    """Retorna lista de dicts: dia, inicio, fim, local, aproximado, mensal_ignorado."""
    t = _norm(texto)
    if not t:
        return []
    toks = _tokens(t)
    out = []
    dias_grupo, ult_dia, pend_range = [], None, False
    teve_hora_no_grupo = False
    local = None
    mensal_ate = -1
    ini_grupo = 0
    item, item_s, last_hora_s = None, -1, -1
    i = 0
    while i < len(toks):
        s, e, k, v = toks[i]
        gap_prev = t[toks[i - 1][1]:s] if i else ""
        if k == "MENSAL":
            # ignora horários até o próximo dia/local (evento mensal)
            j = i + 1
            while j < len(toks) and toks[j][2] == "HORA":
                j += 1
            mensal_ate = j
            i += 1
            continue
        if k == "ITEM":
            item, item_s = v, s
            i += 1
            continue
        if k == "LOCAL":
            item = None
            # novo local herda os dias do grupo atual ("Domingo: Matriz 8h, Capela X 10h")
            if re.search(r"\b(na|no|ma)\s*$", t[max(0, s - 4):s]) and teve_hora_no_grupo:
                # local "à direita": "Quartas às 19h30 na capela" -> vale para as últimas horas
                for r in out[ini_grupo:]:
                    r["local"] = v.title()
                local = None
            else:
                local = v.title()
        elif k == "DIA":
            if not (i + 1 < len(toks) and toks[i + 1][2] == "ITEM"):
                pass
            if teve_hora_no_grupo and item_s < last_hora_s:
                item = None
            vals = DIAS[1:] + DIAS[:1] if v == "ALL" else (["Sab", "Dom"] if v == "FDS" else [v])
            conecta_range = re.fullmatch(r"\s*(?:a|as|ate|-|–)\s*", gap_prev or "") is not None
            conecta_lista = re.fullmatch(r"\s*(?:,|e|,\s*e)\s*", gap_prev or "") is not None
            if teve_hora_no_grupo or not (ult_dia and (conecta_range or conecta_lista)):
                if teve_hora_no_grupo or not ult_dia or not re.fullmatch(r"[\s,:.e]*", gap_prev or ""):
                    dias_grupo = []
                teve_hora_no_grupo = False
            if ult_dia and conecta_range and len(vals) == 1 and not teve_hora_no_grupo and dias_grupo:
                dias_grupo = dias_grupo[:-1] + _expande(ult_dia, vals[0])
            else:
                dias_grupo = dias_grupo + vals
            ult_dia = vals[-1]
            if not teve_hora_no_grupo:
                ini_grupo = len(out)
        elif k == "HORA":
            if i < mensal_ate:
                i += 1
                continue
            fim = None
            last_hora_s = s
            if (modo != "missa" or item == "Adoração") and i + 1 < len(toks) and toks[i + 1][2] == "HORA" and re.fullmatch(RANGE_SEP, t[e:toks[i + 1][0]].replace("das", "")):
                fim = toks[i + 1][3]
            # aproximado: "após a missa das 19h", "antes das missas"
            ctx = t[max(0, s - 30):s]
            aprox = modo != "missa" and bool(re.search(r"\b(apos|antes|depois|durante|na missa|nas missas)\b[^,]{0,25}$", ctx))
            for d in dias_grupo:
                out.append(dict(dia=d, inicio=v, fim=fim, local=local, aproximado=aprox, item=item))
            teve_hora_no_grupo = True
            if fim:
                i += 1
        i += 1
    # remove duplicatas mantendo ordem
    seen, res = set(), []
    for r in out:
        key = (r["dia"], r["inicio"], r["fim"], r["local"], r["item"])
        if key not in seen:
            seen.add(key); res.append(r)
    return res


if __name__ == "__main__":
    testes = [
        "Terça a Sexta: 17h às 19h Sábado: 9h30 às 11h",
        "Terça, quinta e sexta-feira das 14h30 às 16h30",
        "3ª a 6ª das 14:30h às 17h . Sábado na Missa das 19h e nas Missas dominicais.",
        "Segunda a sexta: 7h, às 12h15 e às 19h; Sábado : 7h, às 12h15 e às 18h. Domingo: 7h, às 8h, às 9h30",
        "Terça a Sexta 18-18h50",
        "Segunda a Sexta-feira: 19h Sábado: 18h Domingo: 8h / 19h Primeira sexta-feira do mês, às 19h — Missa do Sagrado Coração",
        "Matriz Terça a sábado: 19h Domingo: 7h30, 10h e 19h Capela Nossa Senhora Rainha dos Anjos Quarta-feira: 19h Domingo: 17h",
        "Quarta - após a Missa das 19h Sexta - das 16h às 18h",
        "DOMINGO: 07h30-10h-19h TERÇA-FEIRA: 19h30",
        "Terça-Feira à Sexta-Feira 19:30 Quinta-Feira 07:00 Sábado 18:00 Domingo 07:30 – 19:30",
    ]
    for x in testes:
        print(x)
        for r in parse(x):
            print("   ", r)
