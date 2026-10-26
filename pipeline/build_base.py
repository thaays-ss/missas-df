"""
Gera a base do painel "Onde tem missa? · DF".

Retorna (quem grava é o atualiza.py):
  horarios.csv   uma linha por celebração (missa ou confissão)  -> fonte do Looker Studio
  paroquias.csv  uma linha por paróquia (contatos, mapa, textos originais)
  qualidade.csv  comparação entre fontes, paróquia a paróquia
  base_looker.xlsx  as três abas juntas, para subir no Google Sheets

Regra de escolha da fonte (por paróquia e por tipo):
  usa a fonte com dado MAIS RECENTE entre:
    1. cadastro da paróquia no site da Arquidiocese (texto livre, editado em 2025-26)
    2. planilha do grupo de WhatsApp (data de "última atualização" por linha)
    3. tabela "Horários de Missas" do site (estruturada, mas congelada desde 2023)
"""
from pathlib import Path
import re
import pandas as pd
from fontes import carrega_cadastro, carrega_tabela_missas, carrega_planilha, casa, DIAS
from parser_horarios import parse

DATA_TABELA = pd.Timestamp("2023-05-28")      # última edição dos 155 registros da tabela oficial
DIA_NOME = dict(Dom="Domingo", Seg="Segunda", Ter="Terça", Qua="Quarta", Qui="Quinta", Sex="Sexta", Sab="Sábado")
DIA_ORDEM = dict(Seg=1, Ter=2, Qua=3, Qui=4, Sex=5, Sab=6, Dom=7)
DIA_TXT = dict(Dom="domingo", Seg="segunda", Ter="terça", Qua="quarta", Qui="quinta", Sex="sexta", Sab="sábado")

# "bairro" do site -> região usada no filtro (agrupa nomes que são a mesma RA)
REGIAO = {"Asa Sul": "Plano Piloto", "Asa Norte": "Plano Piloto", "Vila Planalto": "Plano Piloto",
          "Granja do Torto": "Plano Piloto", "Guará I": "Guará", "Guará II": "Guará",
          "Octogonal": "Sudoeste/Octogonal", "Setor Sudoeste": "Sudoeste/Octogonal",
          "Cidade Estrutural": "SCIA/Estrutural", "Jardins Mangueiral": "Jardim Botânico",
          "Grande Colorado": "Sobradinho II", "Engenho das Lajes": "Gama", "Areal": "Arniqueira",
          "Sol Nascente": "Sol Nascente/Pôr do Sol", "Núcleo Rural Nova Betânia": "São Sebastião", "Noroeste": "Plano Piloto",
          "Riacho fundo 1": "Riacho Fundo I", "Ceilandia Sul": "Ceilândia", "Samambaia Norte": "Samambaia", "Samambaia Sul": "Samambaia"}


def faixa(h):
    if h < 6: return "Madrugada (antes das 6h)"
    if h < 12: return "Manhã (6h–12h)"
    if h < 18: return "Tarde (12h–18h)"
    return "Noite (depois das 18h)"


def main(planilha):
    cad = carrega_cadastro()
    tab = carrega_tabela_missas()
    pinfo, pmissa, pconf = carrega_planilha(planilha)

    # ---------- 1. casar as fontes com o cadastro oficial ----------
    m = casa(tab, cad)
    tab["cad_id"] = [m[(a, b)][0] for a, b in zip(tab.k_nome, tab.k_bairro)]
    tab.loc[tab.cad_id.isna() & (tab.k_nome == "santa rita de cassia"), "cad_id"] = 670  # sem bairro; horários = Planaltina
    m = casa(pinfo, cad)
    for d in (pinfo, pmissa, pconf):
        d["cad_id"] = [m.get((a, b), (None,))[0] for a, b in zip(d.k_nome, d.k_bairro)]
    # paróquias da planilha que não estão no cadastro do site
    sem_cad = pinfo[pinfo.cad_id.isna()]

    # ---------- 2. candidatos por paróquia ----------
    def cand_cadastro(row, tipo):
        txt = row.missa if tipo == "Missa" else row.conf
        rows = parse(txt, "missa" if tipo == "Missa" else "confissao")
        if tipo == "Confissão":
            rows = [r for r in rows if r.get("item") != "Adoração"]
        if tipo == "Missa" and not any(r["dia"] == "Dom" for r in rows):
            return []  # paróquia sempre tem missa dominical: sem domingo = texto não interpretado
        return rows

    linhas, qual = [], []
    for c in cad.itertuples():
        mod = pd.Timestamp(c.mod)
        info = pinfo[pinfo.cad_id == c.id]
        dt_plan = info.atualizado.max() if len(info) else pd.NaT
        dt_plan = dt_plan if pd.notna(dt_plan) else pd.Timestamp("2021-01-01")
        for tipo in ("Missa", "Confissão"):
            cands = []
            r_cad = cand_cadastro(c, tipo)
            if r_cad:
                cands.append(("Site da Arquidiocese (página da paróquia)", mod, r_cad))
            if tipo == "Missa":
                g = pmissa[pmissa.cad_id == c.id]
                if len(g):
                    cands.append(("Planilha do grupo de WhatsApp", dt_plan, [dict(dia=d, inicio=h, fim=None, local=None, aproximado=False) for d, h in zip(g.dia, g.inicio)]))
                g = tab[tab.cad_id == c.id]
                if len(g):
                    cands.append(("Site da Arquidiocese (tabela Horários de Missas, 2023)", DATA_TABELA, [dict(dia=d, inicio=h, fim=None, local=None, aproximado=False) for d, h in zip(g.dia, g.inicio)]))
            else:
                g = pconf[pconf.cad_id == c.id]
                rows = []
                for d, txt in zip(g.dia, g.texto):
                    for r in parse(f"{DIA_TXT[d]} {txt}"):
                        rows.append(r)
                    if re.search(r"antes|apos|após", txt.lower()) and not re.search(r"\d", txt):
                        rows.append(dict(dia=d, inicio=None, fim=None, local=None, aproximado=True, obs=txt))
                if rows:
                    cands.append(("Planilha do grupo de WhatsApp", pd.Timestamp("2021-01-01"), rows))
            if not cands:
                qual.append(dict(paroquia_id=c.id, tipo=tipo, fonte_escolhida="sem horário estruturado", n_fontes=0))
                continue
            cands.sort(key=lambda x: x[1], reverse=True)
            fonte, data, rows = cands[0]
            # concordância entre as duas fontes mais recentes (só horário de início)
            conc = None
            if len(cands) > 1:
                a = {(r["dia"], r["inicio"]) for r in cands[0][2]}
                b = {(r["dia"], r["inicio"]) for r in cands[1][2]}
                conc = round(len(a & b) / len(a | b), 2) if a | b else None
            qual.append(dict(paroquia_id=c.id, tipo=tipo, fonte_escolhida=fonte, data_fonte=data.date(),
                             n_fontes=len(cands), fontes=" | ".join(x[0] for x in cands),
                             concordancia_2_fontes=conc, n_horarios=len(rows)))
            for r in rows:
                linhas.append(dict(paroquia_id=c.id, tipo=r.get("item") or tipo, dia=r["dia"], inicio=r["inicio"], fim=r.get("fim"),
                                   local=r.get("local") or "Matriz / igreja principal", aproximado=r.get("aproximado", False),
                                   obs=r.get("obs", ""), fonte=fonte, atualizado_em=data.date()))

    # ---------- 2b. igrejas que só existem na planilha (mosteiros, comunidades, capelas) ----------
    extras = []
    for i, r in enumerate(sem_cad.itertuples()):
        pid = 90001 + i
        extras.append(dict(id=pid, nome=r.nome, bairro=re.sub(r"\s+", " ", r.bairro).strip() if r.bairro != "nan" else "",
                           vic="", setor="", end="", lat=pd.NA, lng=pd.NA, tel="", wpp="", insta="", site="",
                           missa="", conf="", mod=r.atualizado if pd.notna(r.atualizado) else pd.Timestamp("2021-01-01"), link=""))
        data = r.atualizado if pd.notna(r.atualizado) else pd.Timestamp("2021-01-01")
        g = pmissa[(pmissa.k_nome == r.k_nome) & (pmissa.k_bairro == r.k_bairro)]
        for d, hh in zip(g.dia, g.inicio):
            linhas.append(dict(paroquia_id=pid, tipo="Missa", dia=d, inicio=hh, fim=None, local="Matriz / igreja principal",
                               aproximado=False, obs="", fonte="Planilha do grupo de WhatsApp", atualizado_em=data.date()))
        g = pconf[(pconf.k_nome == r.k_nome)]
        for d, txt in zip(g.dia, g.texto):
            for x in parse(f"{DIA_TXT[d]} {txt}"):
                linhas.append(dict(paroquia_id=pid, tipo="Confissão", dia=x["dia"], inicio=x["inicio"], fim=x["fim"],
                                   local="Matriz / igreja principal", aproximado=x["aproximado"], obs="",
                                   fonte="Planilha do grupo de WhatsApp", atualizado_em=data.date()))
        qual.append(dict(paroquia_id=pid, tipo="Missa", fonte_escolhida="Planilha do grupo de WhatsApp" if len(g) or True else "", data_fonte=data.date(), n_fontes=1))
    if extras:
        ex = pd.DataFrame(extras)
        ex["k_nome"], ex["k_bairro"] = "", ""
        cad = pd.concat([cad, ex], ignore_index=True)
        cad.loc[cad.id >= 90001, "bairro"] = cad.loc[cad.id >= 90001, "bairro"].replace({"Riacho Fundo 1": "Riacho Fundo I", "Ceilandia Sul": "Ceilândia", "Samambaia  Norte": "Samambaia", "Samambaia Norte": "Samambaia", "Lago Sul": "Lago Sul"})

    h = pd.DataFrame(linhas).drop_duplicates(["paroquia_id", "tipo", "dia", "inicio", "local"])
    qual = pd.DataFrame(qual)

    # ---------- 3. tabela de paróquias ----------
    p = cad.copy()
    p["regiao"] = p.bairro.fillna("").map(lambda b: REGIAO.get(b, b) or "Não informado")
    p["lat"] = pd.to_numeric(p.lat, errors="coerce"); p["lng"] = pd.to_numeric(p.lng, errors="coerce")
    p["lat"] = p.lat.where(p.lat.between(-16.1, -15.4) & p.lng.between(-48.3, -47.2))
    p["lng"] = p.lng.where(p.lat.notna())
    p["latlng"] = p.apply(lambda r: f"{r.lat:.6f},{r.lng:.6f}" if pd.notna(r.lat) else "", axis=1)
    p["como_chegar"] = p.apply(lambda r: "https://www.google.com/maps/dir/?api=1&destination=" + (r.latlng if r.latlng else
                                re.sub(r"\s+", "+", f"{r.nome} {r.end or ''} Brasília DF")), axis=1)
    contato = lambda r: " · ".join(x for x in [r.tel and f"Tel {r.tel}", r.wpp and f"WhatsApp {r.wpp}", r.insta and f"Instagram {r.insta}"] if x)
    p[["tel", "wpp", "insta", "end", "site"]] = p[["tel", "wpp", "insta", "end", "site"]].fillna("")
    p["contato"] = p.apply(contato, axis=1)
    p = p.rename(columns=dict(id="paroquia_id", nome="paroquia", end="endereco", vic="vicariato", tel="telefone",
                              wpp="whatsapp", insta="instagram", link="pagina_arquidiocese", missa="texto_missa_site",
                              conf="texto_confissao_site", mod="atualizado_site"))
    p["atualizado_site"] = pd.to_datetime(p.atualizado_site).dt.date
    for tipo, col in (("Missa", "fonte_missa"), ("Confissão", "fonte_confissao")):
        p[col] = p.paroquia_id.map(qual[qual.tipo == tipo].set_index("paroquia_id").fonte_escolhida)
    # observações da planilha (missas especiais, mudanças) entram como nota
    p["obs_grupo"] = p.paroquia_id.map(pinfo.dropna(subset=["cad_id"]).groupby("cad_id").obs.apply(lambda s: " ".join(str(x) for x in s if x)))
    cols_p = ["paroquia_id", "paroquia", "regiao", "bairro", "vicariato", "setor", "endereco", "lat", "lng", "latlng",
              "como_chegar", "contato", "telefone", "whatsapp", "instagram", "site", "pagina_arquidiocese",
              "texto_missa_site", "texto_confissao_site", "obs_grupo", "fonte_missa", "fonte_confissao", "atualizado_site"]
    p = p[cols_p]

    # ---------- 4. tabela de horários (flat, pronta pro Looker) ----------
    h = h.merge(p[["paroquia_id", "paroquia", "regiao", "bairro", "endereco", "latlng", "como_chegar", "contato", "pagina_arquidiocese"]], on="paroquia_id")
    h["dia_semana"] = h.dia.map(DIA_NOME)
    h["dia_ordem"] = h.dia.map(DIA_ORDEM)
    h["weekday_looker"] = h.dia.map(dict(Dom=0, Seg=1, Ter=2, Qua=3, Qui=4, Sex=5, Sab=6))  # = WEEKDAY() do Looker
    h["hora_num"] = h.inicio.map(lambda x: int(x[:2]) + int(x[3:]) / 60 if isinstance(x, str) else None)
    h["faixa_horario"] = h.hora_num.map(lambda x: faixa(x) if pd.notna(x) else "Horário a confirmar")
    h["horario"] = h.apply(lambda r: (r.inicio or "") + (f"–{r.fim}" if isinstance(r.fim, str) else "") + (" (aprox.)" if r.aproximado else "") if r.inicio else (r.obs or "a confirmar"), axis=1)
    h = h.sort_values(["dia_ordem", "hora_num", "paroquia"])
    cols_h = ["paroquia_id", "paroquia", "tipo", "dia_semana", "dia_ordem", "weekday_looker", "horario", "inicio", "fim", "hora_num",
              "faixa_horario", "local", "aproximado", "regiao", "bairro", "endereco", "latlng", "como_chegar",
              "contato", "fonte", "atualizado_em", "pagina_arquidiocese"]
    h = h[cols_h]

    qual = qual.merge(p[["paroquia_id", "paroquia", "regiao"]], on="paroquia_id")
    return h, p, qual, sem_cad


if __name__ == "__main__":
    import sys
    h, p, q, s = main(sys.argv[1])
    print("horários:", len(h), h.groupby("tipo").paroquia_id.nunique().to_dict(), h.tipo.value_counts().to_dict())
    print("paróquias:", len(p), "com coordenada:", p.latlng.ne("").sum())
    print(q.groupby(["tipo", "fonte_escolhida"]).size())
    print("planilha sem par no cadastro:", s.nome.tolist())
