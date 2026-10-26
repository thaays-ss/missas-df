# Onde tem missa? · DF

Horários de **missa, confissão e adoração** no Distrito Federal, num site só: o que está começando agora, onde ainda dá tempo hoje e onde se confessar depois do trabalho.

**→ [Abrir o site](https://missas-df.thaysoaresilva0.workers.dev)**

## Como funciona

```
Planilha dos fiéis (Google Sheets)  ─┐
Cadastro da Arquidiocese de Brasília ─┼─► robô (GitHub Actions, de hora em hora) ─► public/index.html ─► Cloudflare
Tabela de missas da Arquidiocese 2023 ┘        limpa · junta · confere
```

1. **Fiéis atualizam a planilha.** Um horário que muda ou uma igreja nova entra por lá.
2. **O robô roda de hora em hora** (`.github/workflows/atualiza.yml`):
   - baixa a planilha;
   - transforma textos como `6h30 18h` ou `06:30. 19:30` em horários padronizados;
   - casa cada igreja com o cadastro oficial e, quando as fontes discordam, **fica com a informação mais recente**;
   - procura no OpenStreetMap as igrejas que ainda não têm pino no mapa.
3. **Se algo mudou**, o robô grava `dados/` e `public/index.html` num commit. O Cloudflare publica a nova versão sozinho.

### Travas de segurança
- **Quedas bruscas:** se o total de horários cair mais de 15% de uma vez (uma coluna apagada, por exemplo), o robô **não publica**. A execução fica vermelha na aba *Actions*.
- **Texto incompreensível:** o que o robô não entende (como "1ª sexta do mês") fica de fora e vai para `dados/conferir.csv`, em vez de entrar errado no site.
- **Privacidade:** a coluna "Quem atualizou?" da planilha nunca é lida, e a planilha baixada nunca é salva no repositório.

## Estrutura

| Pasta | O que tem |
|---|---|
| `pipeline/` | o robô em Python: `atualiza.py` comanda, `fontes.py` lê as fontes, `parser_horarios.py` entende texto livre, `build_base.py` junta tudo |
| `dados/` | base limpa (`horarios.csv`, `paroquias.csv`), o que conferir (`conferir.csv`) e os dados fixos da Arquidiocese |
| `site/` | modelo do site (`template.html`), ícone e Leaflet |
| `public/` | o site pronto: a única pasta que vai para o ar |

Para rodar na sua máquina:

```bash
pip install -r pipeline/requirements.txt
python pipeline/atualiza.py            # baixa a planilha e gera public/index.html
```

## Números (outubro de 2026)

- **2.619 horários semanais** em **175 igrejas**, em 30 regiões
- Domingo concentra 25% da semana; nos dias úteis, a missa é às 19h
- Fontes:
  - página da paróquia no site da Arquidiocese (95%)
  - planilha dos fiéis (4%)
  - tabela de 2023 (1%)

---

Projeto de [Thays Soares](https://thaays-ss.github.io/), portfólio de Dados & Analytics. **Horários mudam: confirme com a paróquia.**
