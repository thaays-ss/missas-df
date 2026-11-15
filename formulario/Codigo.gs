/**
 * Onde tem missa? · DF — recebe as respostas do formulário das paróquias
 * (missanodf.com.br/formulario) e grava na aba "Respostas" desta planilha.
 *
 * Como instalar (uma vez só):
 * 1. Crie uma planilha nova e PRIVADA no Google Sheets ("Respostas · Onde tem missa").
 * 2. Extensões → Apps Script. Apague o que tiver lá e cole este arquivo inteiro. Salve.
 * 3. Escolha a função "prepara" lá em cima e clique em Executar. Autorize com a sua conta.
 * 4. Implantar → Nova implantação → tipo "App da Web".
 *    Executar como: Eu · Quem pode acessar: Qualquer pessoa. → Implantar.
 * 5. Copie o "URL do app da Web" (termina em /exec) e mande pro Claude.
 */
const ABA = "Respostas";
const CAB = ["Recebido em", "Paróquia", "ID", "Bairro", "Horários certos?", "O que mexeu",
  "Missas", "Confissões", "Adoração", "Missas especiais", "24/12", "25/12", "31/12 e 01/01", "Mutirão de confissão",
  "WhatsApp", "Dados (robô)", "Aprovado ✔"];
const AVISAR_POR_EMAIL = true; // manda um e-mail pra você a cada resposta

function prepara() {
  aba_();
  SpreadsheetApp.getActive().toast("Aba Respostas pronta. Agora é só implantar como App da Web.");
}

function aba_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(ABA);
  if (!sh) {
    sh = ss.insertSheet(ABA);
    sh.appendRow(CAB);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, CAB.length).setFontWeight("bold").setBackground("#EFF4F7");
    sh.setColumnWidths(7, 3, 260);
  }
  return sh;
}

// impede que um texto vire fórmula na planilha
function limpa_(v, max) {
  let s = String(v == null ? "" : v).slice(0, max || 600);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    const d = JSON.parse(e.postData.contents || "{}");
    if (d.hp || !d.paroquia) return ContentService.createTextOutput("ignorado"); // robô de spam
    const sh = aba_();
    sh.appendRow([new Date(), limpa_(d.paroquia, 150), limpa_(d.id, 12), limpa_(d.bairro, 80),
      limpa_(d.certo, 5), limpa_(d.mexeu, 60), limpa_(d.missas), limpa_(d.confissoes), limpa_(d.adoracao), limpa_(d.especiais, 400),
      limpa_(d.n24, 200), limpa_(d.n25, 200), limpa_(d.n31, 200), limpa_(d.mutirao, 200),
      limpa_(d.zap, 40), limpa_(d.bruto, 4000), false]);
    sh.getRange(sh.getLastRow(), CAB.length).insertCheckboxes();
    if (AVISAR_POR_EMAIL) {
      MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
        "Onde tem missa? · resposta de " + String(d.paroquia).slice(0, 80),
        "Chegou uma resposta no formulário:\n\n" + d.paroquia + "\nHorários certos? " + d.certo +
        (d.n24 || d.n25 ? "\nNatal: 24/12 " + (d.n24 || "-") + " · 25/12 " + (d.n25 || "-") : "") +
        "\n\nAbra a planilha para conferir e marcar Aprovado ✔:\n" + SpreadsheetApp.getActive().getUrl());
    }
    return ContentService.createTextOutput("ok");
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  return ContentService.createTextOutput("Formulário Onde tem missa? · DF: no ar.");
}
