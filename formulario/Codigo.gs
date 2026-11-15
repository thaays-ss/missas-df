/**
 * Onde tem missa? · DF — recebe as respostas do formulário das paróquias
 * (missanodf.com.br/formulario) e grava na aba "Respostas" desta planilha.
 *
 * - Resposta da PARÓQUIA: os horários semanais e os de 24/12 e 25/12 vão direto
 *   para a planilha de curadoria (o robô publica em até 1 hora).
 * - Resposta de PAROQUIANO: fica esperando. Depois de confirmar com a paróquia,
 *   marque "Aprovado ✔" na linha e ela é publicada do mesmo jeito.
 * - Missas especiais, 31/12 e 01/01 e mutirão de confissão são texto livre:
 *   ficam na aba Respostas para você (ou o Claude) passar para a curadoria.
 *
 * Como instalar (uma vez só):
 * 1. Crie uma planilha nova e PRIVADA no Google Sheets ("Respostas · Onde tem missa").
 * 2. Extensões → Apps Script. Apague o que tiver lá e cole este arquivo inteiro. Salve.
 * 3. Escolha a função "prepara" lá em cima e clique em Executar. Autorize com a sua conta.
 * 4. Implantar → Nova implantação → tipo "App da Web".
 *    Executar como: Eu · Quem pode acessar: Qualquer pessoa. → Implantar.
 * 5. Copie o "URL do app da Web" (termina em /exec) e mande pro Claude.
 */
const CURADORIA_ID = "1GNIsgfB31KY2Ij4MmEcIjxJ2BQITxuvY2Q8B9P24Juo";
const ABA = "Respostas";
const CAB = ["Recebido em", "Quem enviou", "Contato da paróquia", "Paróquia", "ID", "Bairro",
  "Horários certos?", "O que mexeu", "Missas", "Confissões", "Adoração", "Missas especiais",
  "24/12", "25/12", "31/12 e 01/01", "Mutirão de confissão", "WhatsApp", "Dados (robô)",
  "Aprovado ✔", "Publicado"];
const COL = n => CAB.indexOf(n) + 1;
const AVISAR_POR_EMAIL = true; // manda um e-mail pra você a cada resposta
const DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];
const TIPOS = ["Missa", "Confissão", "Adoração"];
const ANO = 2026;

function prepara() {
  aba_();
  const ss = SpreadsheetApp.getActive();
  if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === "aoEditar"))
    ScriptApp.newTrigger("aoEditar").forSpreadsheet(ss).onEdit().create();
  SpreadsheetApp.openById(CURADORIA_ID).getName(); // pede permissão para a curadoria já agora
  ss.toast("Pronto! Agora é só implantar como App da Web.");
}

function aba_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(ABA);
  if (!sh) {
    sh = ss.insertSheet(ABA);
    sh.appendRow(CAB);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, CAB.length).setFontWeight("bold").setBackground("#EFF4F7");
    sh.setColumnWidths(COL("Missas"), 4, 240);
  }
  return sh;
}

// impede que um texto vire fórmula na planilha
function limpa_(v, max) {
  const s = String(v == null ? "" : v).slice(0, max || 600);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const d = JSON.parse(e.postData.contents || "{}");
    if (d.hp || !d.paroquia) return ContentService.createTextOutput("ignorado"); // robô de spam
    const daParoquia = d.quem === "paroquia";
    const sh = aba_();
    sh.appendRow([new Date(), daParoquia ? "Paróquia" : "Paroquiano", limpa_(d.contatoParoquia, 150),
      limpa_(d.paroquia, 150), limpa_(d.id, 12), limpa_(d.bairro, 80),
      limpa_(d.certo, 5), limpa_(d.mexeu, 60), limpa_(d.missas), limpa_(d.confissoes), limpa_(d.adoracao),
      limpa_(d.especiais, 400), limpa_(d.n24, 200), limpa_(d.n25, 200), limpa_(d.n31, 200),
      limpa_(d.mutirao, 200), limpa_(d.zap, 40),
      limpa_(JSON.stringify({rotulo: d.rotulo, mexeu: d.mexeuIdx || [], bruto: d.bruto || ""}), 6000),
      daParoquia, ""]);
    const linha = sh.getLastRow();
    sh.getRange(linha, COL("Aprovado ✔")).insertCheckboxes();
    let res = "aguardando aprovação";
    if (daParoquia) res = publica_(sh, linha);
    if (AVISAR_POR_EMAIL) {
      MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
        "Onde tem missa? · " + (daParoquia ? "paróquia" : "paroquiano") + " · " + String(d.paroquia).slice(0, 80),
        "Chegou uma resposta no formulário:\n\n" + d.paroquia + "\nQuem enviou: " + (daParoquia ? "a paróquia" : "paroquiano(a), contato da paróquia: " + d.contatoParoquia) +
        "\nHorários certos? " + d.certo + (d.mexeu ? " (mexeu em: " + d.mexeu + ")" : "") +
        (d.n24 || d.n25 ? "\nNatal: 24/12 " + (d.n24 || "-") + " · 25/12 " + (d.n25 || "-") : "") +
        (d.especiais ? "\nMissas especiais: " + d.especiais : "") +
        "\n\nSituação: " + res + "\n" + SpreadsheetApp.getActive().getUrl());
    }
    return ContentService.createTextOutput("ok");
  } finally {
    lock.releaseLock();
  }
}

// marcou "Aprovado ✔" numa resposta de paroquiano → publica
function aoEditar(e) {
  const r = e.range, sh = r.getSheet();
  if (sh.getName() !== ABA || r.getColumn() !== COL("Aprovado ✔") || r.getRow() < 2 || e.value !== "TRUE") return;
  if (sh.getRange(r.getRow(), COL("Publicado")).getValue()) return;
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { publica_(sh, r.getRow()) } finally { lock.releaseLock() }
}

function publica_(sh, linha) {
  const v = sh.getRange(linha, 1, 1, CAB.length).getValues()[0];
  const g = n => v[COL(n) - 1];
  let dados = {};
  try { dados = JSON.parse(String(g("Dados (robô)")).replace(/^'/, "")) } catch (err) {}
  const igreja = dados.rotulo || g("Paróquia");
  const hoje = Utilities.formatDate(new Date(), "America/Sao_Paulo", "dd/MM/yyyy");
  const cur = SpreadsheetApp.openById(CURADORIA_ID);
  const feito = [];

  // 1. horários semanais: troca, na curadoria, os tipos que a pessoa mexeu
  if (g("Horários certos?") === "Não" && dados.bruto) {
    const E = JSON.parse(dados.bruto);
    const hs = cur.getSheetByName("Horários");
    (dados.mexeu || []).forEach(ti => {
      apaga_(hs, row => mesmaIgreja_(row[0], igreja) && row[1] === TIPOS[ti]);
      const novas = [];
      E[ti].forEach((itens, di) => itens.forEach(x => {
        if (ti === 0) novas.push([igreja, "Missa", DIAS[di], x, "", "", "", hoje, ""]);
        else if (x[0] === "00:00" && x[1] === "23:59") novas.push([igreja, TIPOS[ti], DIAS[di], "00:00", "23:59", "", "24 horas", hoje, ""]);
        else novas.push([igreja, TIPOS[ti], DIAS[di], x[0], x[1] || "", "", "", hoje, ""]);
      }));
      if (novas.length) acrescenta_(hs, novas);
      feito.push(TIPOS[ti] + ": " + novas.length + " horários");
    });
  }

  // 2. Natal (24/12 e 25/12) → aba Especiais
  const natal = [];
  horas_(g("24/12")).forEach(h => natal.push(h === "00:00"
    ? ["Missa do Galo", "25/12/" + ANO, "00:00"] : ["Missa do Galo", "24/12/" + ANO, h]));
  horas_(g("25/12")).forEach(h => natal.push(["Missa de Natal", "25/12/" + ANO, h]));
  if (natal.length) {
    const es = cur.getSheetByName("Especiais");
    apaga_(es, row => mesmaIgreja_(row[0], igreja) && /^Missa (do Galo|de Natal)$/.test(row[1]));
    acrescenta_(es, natal.map(([cel, data, h]) =>
      [igreja, cel, "Missa", "Só uma vez", data, "", "", "", "", h, "", "", "Solenidades e festas", ""]));
    feito.push("Natal: " + natal.length + " missas");
  }

  const res = feito.length ? "publicado (" + feito.join(" · ") + ")" : "nada para publicar automaticamente";
  sh.getRange(linha, COL("Publicado")).setValue(res + " em " + hoje);
  return res;
}

// "Imaculado Coração de Maria — Taguatinga" == "Imaculado Coração de Maria — Taguatinga"
function mesmaIgreja_(a, b) {
  const k = s => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  return k(a) === k(b);
}

// apaga, de baixo pra cima, as linhas que batem
function apaga_(aba, bate) {
  const n = aba.getLastRow();
  if (n < 2) return;
  const vals = aba.getRange(2, 1, n - 1, aba.getLastColumn()).getValues();
  for (let i = vals.length - 1; i >= 0; i--) if (bate(vals[i])) aba.deleteRow(i + 2);
}

// grava logo abaixo da última linha preenchida (sem pular nem sobrescrever)
function acrescenta_(aba, linhas) {
  const larg = Math.min(linhas[0].length, aba.getMaxColumns());
  aba.getRange(aba.getLastRow() + 1, 1, linhas.length, larg)
    .setNumberFormat("@").setValues(linhas.map(l => l.slice(0, larg)));
}

// "19h, 22h30 e meia-noite" → ["19:00", "22:30", "00:00"]
function horas_(txt) {
  const s = String(txt || "").toLowerCase().replace(/meia[- ]?noite/g, "0h");
  const out = [];
  const re = /(\d{1,2})\s*(?:h|:)\s*(\d{2})?/g;
  let m;
  while ((m = re.exec(s))) {
    const h = +m[1], mi = m[2] ? +m[2] : 0;
    if (h > 24 || mi > 59) continue;
    const x = String(h % 24).padStart(2, "0") + ":" + String(mi).padStart(2, "0");
    if (out.indexOf(x) < 0) out.push(x);
  }
  return out;
}

function doGet() {
  return ContentService.createTextOutput("Formulário Onde tem missa? · DF: no ar.");
}
