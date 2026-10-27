"""
Planilha de curadoria (a planilha da Thays no Google Sheets).

Abas lidas:
  Horários       horários semanais; quando uma igreja aparece aqui com um tipo,
                 os horários daquele tipo passam a vir SÓ desta planilha
  Especiais      celebrações não semanais (todo dia 1, 1ª sexta, Finados, Páscoa...)
  Igrejas novas  igrejas que não estão na base, ou correções (endereço, nome, link do Maps)
"""
import re, urllib.request, zlib
from datetime import date, timedelta
import pandas as pd
from unidecode import unidecode

FONTE = "Curadoria do projeto"
DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"]
DIA_NOME = {"domingo": "Dom", "segunda": "Seg", "terca": "Ter", "quarta": "Qua", "quinta": "Qui", "sexta": "Sex", "sabado": "Sab"}
FAIXAS = {"seg a sex": ["Seg", "Ter", "Qua", "Qui", "Sex"], "ter a sex": ["Ter", "Qua", "Qui", "Sex"],
          "seg a sab": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab"], "todos os dias": DIAS}
TIPOS_ESP = ["Missa", "Confissão", "Adoração", "Celebração"]


def k(s):
    return re.sub(r"\s+", " ", unidecode(str(s or "")).lower()).strip()


def vazio(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "NaT")


def hora(v):
    if vazio(v):
        return None
    if hasattr(v, "hour"):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, float) and 0 <= v < 1:  # fração do dia (Excel)
        m = round(v * 1440)
        return f"{m // 60:02d}:{m % 60:02d}"
    m = re.search(r"(2[0-3]|[01]?\d)\s*(?:[:h]\s*([0-5]\d))?", str(v))
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}" if m else None


def data_br(v):
    if vazio(v):
        return None
    if hasattr(v, "year"):
        return pd.Timestamp(v).date()
    d = pd.to_datetime(str(v).strip(), dayfirst=True, errors="coerce")
    return None if pd.isna(d) else d.date()


def dias(v):
    s = k(v)
    if s in FAIXAS:
        return FAIXAS[s]
    s = s.split("-")[0].split(" ")[0]
    return [DIA_NOME[s]] if s in DIA_NOME else []


# ---------- datas litúrgicas móveis ----------
def pascoa(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, kk = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - kk) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(y, mes, dia)


def advento1(y):
    n25 = date(y, 12, 25)
    return n25 - timedelta(days=(n25.weekday() + 1) % 7 or 7) - timedelta(days=21)


def festa_movel(nome, y):
    P = pascoa(y)
    off = {"quarta-feira de cinzas": -46, "domingo de ramos": -7, "quinta-feira santa": -3, "sexta-feira santa": -2,
           "vigilia pascal": -1, "domingo de pascoa": 0, "ascensao do senhor": 42, "pentecostes": 49,
           "santissima trindade": 56, "corpus christi": 60, "sagrado coracao de jesus": 68}
    n = k(nome)
    if n in off:
        return P + timedelta(days=off[n])
    if n.startswith("1o domingo do advento") or n.startswith("1º domingo do advento") or "advento" in n:
        return advento1(y)
    if n == "cristo rei":
        return advento1(y) - timedelta(days=7)
    return None


def ocorrencias(r, ini, fim):
    """Datas (date) em que a regra do especial acontece entre ini e fim."""
    rep = k(r.get("Repete"))
    out = []
    if rep.startswith("so uma"):
        d = data_br(r.get("Data"))
        out = [d] if d else []
    elif rep.startswith("toda semana"):
        ds = dias(r.get("Dia da semana"))
        wd = [DIAS.index(x) for x in ds]
        d = ini
        while d <= fim:
            if (d.weekday() + 1) % 7 in wd:
                out.append(d)
            d += timedelta(days=1)
    elif rep.startswith("todo ano"):
        s = str(r.get("Data") or "")
        if hasattr(r.get("Data"), "month"):
            dd, mm = r["Data"].day, r["Data"].month
        else:
            m = re.match(r"\s*(\d{1,2})\s*/\s*(\d{1,2})", s)
            dd, mm = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        if dd:
            for y in range(ini.year, fim.year + 1):
                try:
                    out.append(date(y, mm, dd))
                except ValueError:
                    pass
    elif rep.startswith("todo mes (dia fixo)"):
        try:
            n = int(float(r.get("Dia do mês")))
        except (TypeError, ValueError):
            n = None
        if n:
            y, m = ini.year, ini.month
            while date(y, m, 1) <= fim:
                try:
                    out.append(date(y, m, n))
                except ValueError:
                    pass
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    elif rep.startswith("todo mes (dia da semana)"):
        ds = dias(r.get("Dia da semana"))
        q = k(r.get("Qual semana"))
        if ds and q:
            wd = DIAS.index(ds[0])
            y, m = ini.year, ini.month
            while date(y, m, 1) <= fim:
                lst = [date(y, m, d) for d in range(1, 32) if _ok(y, m, d) and (date(y, m, d).weekday() + 1) % 7 == wd]
                if q.startswith("ult"):
                    out.append(lst[-1])
                elif q[0].isdigit() and int(q[0]) <= len(lst):
                    out.append(lst[int(q[0]) - 1])
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    elif rep.startswith("festa movel"):
        for y in range(ini.year, fim.year + 1):
            d = festa_movel(r.get("Festa móvel"), y)
            if d:
                out.append(d)
    return sorted(d for d in out if ini <= d <= fim)


def _ok(y, m, d):
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


# ---------- links do Google Maps ----------
def coords_do_link(link):
    """Extrai lat,lng de um link do Google Maps (abre links curtos maps.app.goo.gl)."""
    if vazio(link):
        return None
    url = str(link).strip()
    if re.search(r"goo\.gl|maps\.app", url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 missas-df-bot"})
            url = urllib.request.urlopen(req, timeout=20).geturl()
        except Exception as e:
            print("  link do Maps não abriu:", e)
    for pat in (r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", r"@(-?\d+\.\d+),(-?\d+\.\d+)", r"[?&](?:q|query|destination|ll)=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
                r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$"):
        m = re.search(pat, url)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -16.2 < lat < -15.3 and -48.4 < lng < -47.2:
                return round(lat, 6), round(lng, 6)
    return None


# ---------- leitura ----------
def carrega(caminho):
    xl = pd.ExcelFile(caminho)
    abas = {k(s): s for s in xl.sheet_names}
    ler = lambda nome: xl.parse(abas[nome], dtype=object) if nome in abas else pd.DataFrame()
    return ler("horarios"), ler("especiais"), ler("igrejas novas")


def aplica(caminho, h, p, avisos):
    """Aplica a curadoria sobre a base (h = horários, p = paróquias). Devolve h, p, especiais."""
    hor, esp, nov = carrega(caminho)
    p = p.copy()
    chave = lambda r: (f"{r.paroquia} — {r.bairro}" if isinstance(r.bairro, str) and r.bairro else r.paroquia)
    idx = {k(chave(r)): r.paroquia_id for r in p.itertuples()}
    idx.update({k(r.paroquia): r.paroquia_id for r in p.itertuples() if k(r.paroquia) not in idx})

    # --- igrejas novas e correções
    for _, r in nov.iterrows():
        nome = str(r.get("Nome") or "").strip()
        if not nome or nome == "nan":
            continue
        pid = idx.get(k(nome))
        novo_nome = r.get("Corrigir nome para (opcional)")
        if pid is None:  # igreja nova: id fixo a partir do nome
            pid = 1_000_000 + zlib.crc32(k(nome).encode()) % 900_000
            limpo = nome.split(" — ")[0].strip()
            p = pd.concat([p, pd.DataFrame([dict(paroquia_id=pid, paroquia=limpo, regiao="Não informado", bairro="", endereco="",
                                                 lat=pd.NA, lng=pd.NA, contato="", pagina_arquidiocese="")])], ignore_index=True)
            idx[k(nome)] = pid
            idx[k(limpo)] = pid
        i = p.index[p.paroquia_id == pid][0]
        for col, campo in (("bairro", "Bairro"), ("regiao", "Região"), ("endereco", "Endereço"), ("contato", "Contato (telefone/Instagram da igreja)")):
            if not vazio(r.get(campo)):
                p.loc[i, col] = str(r.get(campo)).strip()
        if not vazio(novo_nome):
            p.loc[i, "paroquia"] = str(novo_nome).strip()
            if vazio(link):
                p.loc[i, "como_chegar"] = ""
        # a igreja pode ser chamada por "Nome", "Nome — Bairro" ou pelo nome corrigido
        nm, br = p.loc[i, "paroquia"], p.loc[i, "bairro"]
        for x in (nm, f"{nm} — {br}" if isinstance(br, str) and br else nm, f"{nome.split(' — ')[0]} — {br}" if isinstance(br, str) else nome):
            idx.setdefault(k(x), pid)
        link = r.get("Link do Google Maps")
        c = coords_do_link(link)
        if c:
            p.loc[i, ["lat", "lng"]] = c
        if not vazio(link):
            p.loc[i, "como_chegar"] = str(link).strip()
        elif not vazio(r.get("Endereço")) and not c:
            p.loc[i, ["lat", "lng"]] = [pd.NA, pd.NA]  # endereço corrigido: o robô procura de novo no mapa
            p.loc[i, "como_chegar"] = ""
    # rota para quem não tem: busca pelo nome + endereço no Google Maps
    sem = p.como_chegar.isna() | (p.como_chegar.astype(str).str.len() < 10)
    p.loc[sem, "como_chegar"] = p[sem].apply(lambda r: "https://www.google.com/maps/search/?api=1&query=" +
                                             urllib.request.quote(f"{r.paroquia} {r.endereco if isinstance(r.endereco, str) else ''} Brasília DF"), axis=1)

    # --- horários semanais
    novas, trocar = [], set()
    for n, r in hor.iterrows():
        ig = str(r.get("Igreja") or "").strip()
        if not ig or ig == "nan":
            continue
        pid = idx.get(k(ig))
        tipo = str(r.get("Tipo") or "").strip()
        if pid is None:
            avisos.append(f"Horários linha {n + 2}: igreja '{ig}' não encontrada (cadastre em Igrejas novas)")
            continue
        if tipo not in ("Missa", "Confissão", "Adoração"):
            avisos.append(f"Horários linha {n + 2}: tipo '{tipo}' inválido")
            continue
        subst = k(r.get("Substituir a base?"))
        if not subst.startswith("nao"):
            trocar.add((pid, tipo))
        obs = "" if vazio(r.get("Observação")) else str(r.get("Observação")).strip()
        ini, fim = hora(r.get("Início")), hora(r.get("Fim (opcional)"))
        if ini is None:
            if "remover" not in obs.lower():
                avisos.append(f"Horários linha {n + 2}: sem horário de início")
            continue
        ds = dias(r.get("Dia"))
        if not ds:
            avisos.append(f"Horários linha {n + 2}: dia '{r.get('Dia')}' não reconhecido")
            continue
        upd = data_br(r.get("Atualizado em")) or date.today()
        local = "Matriz / igreja principal" if vazio(r.get("Local (opcional)")) else str(r.get("Local (opcional)")).strip()
        for d in ds:
            novas.append(dict(paroquia_id=pid, tipo=tipo, dia=d, inicio=ini, fim=fim, local=local,
                              aproximado=bool(re.search(r"\(aprox|aproximad|(antes|apos|após|depois) d[ao]s? missa", obs.lower())),
                              obs=obs, fonte=FONTE, atualizado_em=upd))
    if trocar:
        fora = h.apply(lambda r: (r.paroquia_id, r.tipo) in trocar, axis=1)
        h = h[~fora]
    h = pd.concat([h, pd.DataFrame(novas)], ignore_index=True) if novas else h

    # --- especiais: ocorrências de ontem até ~13 meses
    hoje = date.today()
    ini, fim = hoje - timedelta(days=1), hoje + timedelta(days=400)
    occ = []
    for n, r in esp.iterrows():
        ig = str(r.get("Igreja") or "").strip()
        if not ig or ig == "nan":
            continue
        pid = idx.get(k(ig))
        if pid is None:
            avisos.append(f"Especiais linha {n + 2}: igreja '{ig}' não encontrada")
            continue
        tipo = str(r.get("Tipo") or "Missa").strip()
        tipo = tipo if tipo in TIPOS_ESP else "Missa"
        hi, hf = hora(r.get("Início")), hora(r.get("Fim (opcional)"))
        tit = "" if vazio(r.get("Celebração")) else str(r.get("Celebração")).strip()
        obs = "" if vazio(r.get("Observação")) else str(r.get("Observação")).strip()
        ds = ocorrencias(r, ini, fim)
        exc = [DIAS.index(x) for x in re.findall(r"dom|seg|ter|qua|qui|sex|sab", k(r.get("Exceto (dias da semana)")))
               for x in [dict(dom="Dom", seg="Seg", ter="Ter", qua="Qua", qui="Qui", sex="Sex", sab="Sab")[x]]]
        ds = [d for d in ds if (d.weekday() + 1) % 7 not in exc]
        cat = k(r.get("Categoria"))
        cat = "Votiva" if cat.startswith("votiv") else "Solenidades e festas" if cat.startswith(("solen", "festa")) else ""
        if not ds:
            avisos.append(f"Especiais linha {n + 2}: não consegui calcular a data (confira Repete e as colunas da regra)")
        for d in ds:
            occ.append(dict(data=d.isoformat(), inicio=hi or "", fim=hf or "", paroquia_id=pid, celebracao=tit or tipo,
                            tipo=tipo, obs=obs, categoria=cat))
    especiais = pd.DataFrame(occ, columns=["data", "inicio", "fim", "paroquia_id", "celebracao", "tipo", "obs", "categoria"]).sort_values(["data", "inicio"])
    return h, p, especiais
