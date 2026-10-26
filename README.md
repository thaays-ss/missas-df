# Onde tem missa? · DF

Horários de **missa, confissão e adoração** no Distrito Federal, num site só: o que está começando agora, onde ainda dá tempo hoje e onde se confessar depois do trabalho.

**→ [Abrir o site](https://missas-df.thaysoaresilva0.workers.dev)**

## Os dados

- **2.618 horários semanais** em **175 igrejas**, agrupadas em 30 regiões
- Fontes:
  - página de cada paróquia no site da Arquidiocese de Brasília (95%)
  - planilha colaborativa de um grupo de fiéis (4%)
  - tabela "Horários de Missas" de 2023 (1%)
- Retrato de outubro de 2026. Os nomes de quem atualizou a planilha foram removidos.

## O site

- **Agora:** o que começa na próxima hora, mapa, o último horário do dia, dedicação do dia e tempo litúrgico.
- **Confissão à noite:** confissões que começam a partir das 18h, por dia.
- **Números da base:** como os horários se distribuem e quais cuidados ter ao ler os números.

É um único `index.html`, sem servidor. "Agora" é calculado no navegador, no fuso de Brasília. O mapa usa Leaflet com o OpenStreetMap (grátis, sem chave).

## Como os dados são atualizados

- [ ] Robô agente realiza leitura a planilha dos fiéis, limpa os horários e atualiza o site sozinho

---

Projeto de [Thays Soares](https://thaays-ss.github.io/), portfólio de Dados & Analytics. **Horários mudam: confirme com a paróquia.**
