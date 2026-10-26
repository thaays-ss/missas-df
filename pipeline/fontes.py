"""Carrega e normaliza as 3 fontes + casamento de nomes entre elas."""
import json, re
from pathlib import Path
import pandas as pd
from unidecode import unidecode
from rapidfuzz import fuzz

RAW = Path(__file__).resolve().parent.parent / "dados"
DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"]

PREFIXOS = r"^(quase paroquia|paroquia|santuario basilica|santuario arquidiocesano|santuario|basilica|catedral|igrejinha|capela|comunidade catolica|comunidade|sant\.)\s+"
ABREV = [(r"\bn\.?\s*sra\.?", "nossa senhora"), (r"\bsra\.?", "senhora"), (r"\bsto\.?\b", "santo"),
         (r"\bsoc\.?$", "socorro"), (r"\bs\.\s", "sao "), (r"lelis", "lellis"), (r"santa cura", "santo cura"),
         (r"teresinha", "terezinha"), (r"^(paroquia )?santuario dom bosco", "sao joao bosco"), (r"francisco francisco", "francisco de assis"), (r"^sao paulo$", "sao paulo apostolo"), (r"^catedral$", "catedral nossa senhora aparecida")]


def norm_nome(s):
    s = unidecode(str(s or "")).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[-–]{2,}|[^a-z0-9.\s]", " ", s)
    for a, b in ABREV:
        s = re.sub(a, b, s)
    s = re.sub(r"\s+", " ", s).strip()
    for _ in range(2):
        s = re.sub(PREFIXOS, "", s)
    s = s.replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


BAIRRO_ALIAS = {"l2 sul": "asa sul", "esplanada dos ministerios": "asa sul", "cruzeiro novo": "cruzeiro",
                "cruzeiro velho": "cruzeiro", "cruzeiro octogonal": "cruzeiro", "octogonal": "cruzeiro",
                "taguatinga norte": "taguatinga", "taguatinga sul": "taguatinga", "setor sudoeste": "sudoeste",
                "parkway": "park way", "sobradinho ii": "sobradinho", "jardins mangueiral": "jardim botanico",
                "jardim botanico mangueiral": "jardim botanico", "guara i": "guara", "guara ii": "guara",
                "ceilandia sul": "ceilandia", "samambaia norte": "samambaia", "samambaia sul": "samambaia",
                "riacho fundo 1": "riacho fundo i", "estrutural": "cidade estrutural", "areal": "aguas claras",
                "sol nascente": "ceilandia", "lucio costa": "guara", "noroeste": "asa norte"}


def norm_bairro(s):
    s = unidecode(str(s or "")).lower().replace("/", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return BAIRRO_ALIAS.get(s, s)


# ---------- fonte 1: cadastro de paróquias (API GeoDirectory do site) ----------
def carrega_cadastro():
    p = pd.DataFrame(json.load(open(RAW / "arq_paroquias.json")))
    p["lat"] = pd.to_numeric(p["lat"], errors="coerce").replace(0, pd.NA)
    p["lng"] = pd.to_numeric(p["lng"], errors="coerce").replace(0, pd.NA)
    p["bairro"] = p["bairro"].str.replace("Enjenho", "Engenho").replace({"ParkWay": "Park Way", "Jardins mangueiral": "Jardins Mangueiral"})
    # correções pontuais do cadastro (endereço diz outro bairro)
    p.loc[p.id == 541, "bairro"] = "Lago Sul"   # São Pedro de Alcântara: SHIS QI 07, Lago Sul
    p["k_nome"] = p["nome"].map(norm_nome)
    p["k_bairro"] = p["bairro"].map(norm_bairro)
    return p


# ---------- fonte 2: tabela de missas renderizada em /horarios-de-missas ----------
def carrega_tabela_missas():
    s = (RAW / "arq_missas_tabela.txt").read_text()
    P, R = s.split("\nR\n")
    par = [x.split("|") for x in P.split("\n")[1:]]
    rows = []
    for r in R.split(";"):
        d, i, h = r.split(",")
        nome, end, bairro = par[int(i)]
        hh, mm = h.split("h")
        rows.append(dict(t_id=int(i), nome=nome, endereco=end, bairro=bairro, dia=d, inicio=f"{int(hh):02d}:{mm or '00'}"))
    t = pd.DataFrame(rows).drop_duplicates(["t_id", "dia", "inicio"])
    t["k_nome"] = t["nome"].map(norm_nome)
    t["k_bairro"] = t["bairro"].map(norm_bairro)
    return t


# ---------- fonte 3: planilha do grupo de WhatsApp ----------
def _hora(v):
    """Uma célula de horário -> lista "HH:MM". Aceita 19:00, 19h, 19h30, '6h30 18h', '06:30. 19:30', '6:30 | 19:00', 19."""
    if pd.isna(v):
        return []
    if hasattr(v, "hour"):
        return [f"{v.hour:02d}:{v.minute:02d}"]
    s = unidecode(str(v)).lower()
    if re.search(r"do mes|de cada mes", s):
        return []
    out = []
    for m in re.finditer(r"(?<![\d/])([01]?\d|2[0-3])\s*(?:(?::|h)\s*([0-5]\d)?|(?=\s*$))(?![\d/])", s.strip()):
        out.append(f"{int(m.group(1)):02d}:{m.group(2) or '00'}")
    return out


def _k(s):
    return re.sub(r"\s+", " ", unidecode(str(s or "")).lower()).strip()


DIA_HEAD = {"domingo": "Dom", "segunda": "Seg", "terca": "Ter", "quarta": "Qua", "quinta": "Qui", "sexta": "Sex", "sabado": "Sab",
            "dom": "Dom", "seg": "Seg", "ter": "Ter", "qua": "Qua", "qui": "Qui", "sex": "Sex", "sab": "Sab"}


def _acha(head, *prefixos):
    for c, h in head.items():
        if any(_k(h).startswith(p) for p in prefixos):
            return c
    return None


def carrega_planilha(caminho):
    """Lê a planilha do grupo (baixada do Google Sheets) pelos NOMES das colunas,
    para não quebrar se alguém inserir/mover uma coluna.
    A coluna "Quem atualizou?" (nomes de pessoas) nunca é lida."""
    xl = pd.ExcelFile(caminho)
    abas = {_k(s): s for s in xl.sheet_names}
    if "missa base" not in abas:
        raise SystemExit(f"Planilha sem a aba 'Missa base' (abas: {xl.sheet_names})")
    # ---- aba "Missa base": paróquia | bairro | atualização | quem | Domingo (várias col.) ... Sábado | Observações
    df = xl.parse(abas["missa base"], header=None)
    head = df.iloc[0]
    c_nome, c_bairro = _acha(head, "paroquia"), _acha(head, "bairro")
    c_upd, c_obs = _acha(head, "ultima atualiza"), _acha(head, "observa")
    if c_nome is None or c_bairro is None:
        raise SystemExit("Aba 'Missa base': não achei as colunas Paróquia/Bairro")
    dia_col = {}
    atual = None
    for c in df.columns:
        if c in (c_nome, c_bairro, c_upd, c_obs) or "atualiz" in _k(head[c]):
            atual = None if not pd.isna(head[c]) else atual
            continue
        if not pd.isna(head[c]):
            atual = DIA_HEAD.get(_k(head[c]).split("-")[0].split(" ")[0])
        if atual:
            dia_col[c] = atual
    if len(set(dia_col.values())) < 7:
        raise SystemExit(f"Aba 'Missa base': esperava colunas dos 7 dias, achei {sorted(set(dia_col.values()))}")
    body = df.iloc[1:].copy()
    body[c_bairro] = body[c_bairro].ffill()
    missas, info = [], []
    for _, r in body.iterrows():
        if pd.isna(r[c_nome]) or not str(r[c_nome]).strip():
            continue
        nome = str(r[c_nome]).strip().rstrip("-").strip()
        upd = pd.to_datetime(r[c_upd], errors="coerce", dayfirst=True) if c_upd is not None else pd.NaT
        if pd.notna(upd) and (upd.year < 2019 or upd > pd.Timestamp.now() + pd.Timedelta(days=2)):
            upd = pd.NaT  # data digitada errada
        obs = r[c_obs] if c_obs is not None and not pd.isna(r[c_obs]) else ""
        info.append(dict(nome=nome, bairro=str(r[c_bairro]).strip(), atualizado=upd, obs=obs))
        for c, d in dia_col.items():
            for h in _hora(r[c]):
                missas.append(dict(nome=nome, bairro=str(r[c_bairro]).strip(), dia=d, inicio=h))
    info = pd.DataFrame(info)
    missas = pd.DataFrame(missas, columns=["nome", "bairro", "dia", "inicio"]).drop_duplicates()

    # ---- aba "Confissão": paróquia | local | Seg ... Dom (uma linha por faixa, paróquia na 1ª linha do bloco)
    conf = []
    if "confissao" in abas:
        cf = xl.parse(abas["confissao"], header=None)
        hc = cf.iloc[0]
        cn, cb = _acha(hc, "paroquia"), _acha(hc, "local", "bairro")
        cols = {c: DIA_HEAD[_k(h)[:3]] for c, h in hc.items() if not pd.isna(h) and _k(h)[:3] in DIA_HEAD and c not in (cn, cb)}
        cf = cf.iloc[1:].copy()
        cf[cb] = cf[cb].ffill()
        cf["nome"] = cf[cn].ffill()
        for _, r in cf.iterrows():
            if pd.isna(r["nome"]):
                continue
            for c, d in cols.items():
                v = r[c]
                if pd.isna(v) or str(v).strip() in (".", "-", ""):
                    continue
                if hasattr(v, "hour"):
                    v = f"{v.hour:02d}:{v.minute:02d}"
                conf.append(dict(nome=str(r["nome"]).strip(), bairro=str(r[cb]).strip(), dia=d, texto=str(v).strip()))
    conf = pd.DataFrame(conf, columns=["nome", "bairro", "dia", "texto"])
    for d in (info, missas, conf):
        d["k_nome"] = d["nome"].map(norm_nome)
        d["k_bairro"] = d["bairro"].map(norm_bairro)
    return info, missas, conf


def _end(s):
    return re.sub(r"[^a-z0-9 ]", " ", unidecode(str(s or "")).lower())


def casa(df, cad, limiar=82):
    """Casa cada paróquia de uma fonte com o cadastro oficial.
    score = 60% nome + 40% localização (bairro igual, ou endereço parecido).
    O nome completo (com 'Santuário', 'Igrejinha'...) desempata homônimos."""
    res = {}
    cols = [c for c in ["k_nome", "k_bairro", "nome", "endereco"] if c in df]
    for row in df[cols].drop_duplicates(["k_nome", "k_bairro"]).itertuples(index=False):
        r = row._asdict()
        kn, kb = r["k_nome"], r["k_bairro"]
        best, best_sc = None, 0
        for c in cad.itertuples():
            sn = max(fuzz.token_sort_ratio(kn, c.k_nome), 0.95 * fuzz.token_set_ratio(kn, c.k_nome))
            if sn < 75:
                continue
            sl = 50
            if kb and c.k_bairro:
                sl = 100 if kb == c.k_bairro else 0.6 * fuzz.partial_ratio(kb, c.k_bairro)
            if r.get("endereco") and c.end:
                sl = max(sl, fuzz.token_set_ratio(_end(r["endereco"]), _end(c.end)))
            sc = 0.6 * sn + 0.4 * sl + 0.02 * fuzz.ratio(norm_nome(r["nome"]) + unidecode(r["nome"]).lower(), c.k_nome + unidecode(c.nome).lower())
            if sc > best_sc:
                best, best_sc = c.id, sc
        res[(kn, kb)] = (best if best_sc >= limiar else None, round(best_sc, 1))
    return res
