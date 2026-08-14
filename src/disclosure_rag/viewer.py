"""A single page for asking a question and seeing where the answer came from.

Deliberately one self-contained file with no build step, no framework and no
external requests. The interesting part of this project is the citation, not the
front end, and a viewer that needs npm to demonstrate a Python service is a
liability rather than a feature.

It shows what the API returns rather than prettifying it: the route taken, the
confidence, whether the citation is exact or predicted, and the region drawn on
the actual page. An abstention is displayed as a result, not an error, because
that is what it is.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>disclosure-rag</title>
<style>
  :root { color-scheme: light dark; --line: #d6d9de; --muted: #6b7280;
          --exact: #137333; --exact-bg: #e6f4ea; --soft: #b06000; --soft-bg: #fef7e0;
          --stop: #c5221f; --stop-bg: #fde8e8; }
  @media (prefers-color-scheme: dark) {
    :root { --line: #33383f; --exact-bg: #16281c; --soft-bg: #2b2412; --stop-bg: #2c1717; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
  header { padding: 18px 24px; border-bottom: 1px solid var(--line); }
  h1 { margin: 0; font-size: 17px; letter-spacing: -0.01em; }
  header p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
  main { display: grid; grid-template-columns: minmax(340px, 2fr) 3fr; gap: 24px; padding: 24px; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  label { display: block; font-size: 12px; text-transform: uppercase;
          letter-spacing: .06em; color: var(--muted); margin-bottom: 6px; }
  select, textarea, button { width: 100%; font: inherit; padding: 9px 11px;
          border: 1px solid var(--line); border-radius: 7px; background: transparent;
          color: inherit; }
  textarea { min-height: 78px; resize: vertical; }
  button { margin-top: 12px; cursor: pointer; font-weight: 600; }
  button:disabled { opacity: .5; cursor: default; }
  .field { margin-bottom: 16px; }
  .answer { border: 1px solid var(--line); border-radius: 9px; padding: 16px; margin-top: 18px; }
  .answer.exact { border-color: var(--exact); background: var(--exact-bg); }
  .answer.soft { border-color: var(--soft); background: var(--soft-bg); }
  .answer.stop { border-color: var(--stop); background: var(--stop-bg); }
  .headline { font-size: 22px; font-weight: 650; margin: 0 0 8px; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .tag { font-size: 11px; padding: 2px 8px; border: 1px solid var(--line);
         border-radius: 999px; color: var(--muted); }
  .reason { color: var(--muted); font-size: 13px; }
  .examples { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
  .examples button { width: auto; text-align: left; margin: 0; padding: 6px 10px;
          font-size: 12px; font-weight: 400; color: var(--muted); }
  figure { margin: 0; }
  figure img { width: 100%; border: 1px solid var(--line); border-radius: 7px; }
  figcaption { color: var(--muted); font-size: 12px; margin-top: 8px; }
  .empty { color: var(--muted); padding: 40px 0; text-align: center; }
  code { font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>disclosure-rag</h1>
  <p>Ask about a figure and see the region it came from. <span id="snap"></span></p>
</header>

<main>
  <section>
    <div class="field">
      <label for="doc">Filing</label>
      <select id="doc"></select>
    </div>
    <div class="field">
      <label for="q">Question</label>
      <textarea id="q" placeholder="Wie hoch war ... im Geschaeftsjahr 2022?"></textarea>
      <div id="examples" class="examples"></div>
      <button id="ask">Ask</button>
    </div>
    <div id="out"></div>
  </section>
  <section id="pane"><div class="empty">The cited region will appear here.</div></section>
</main>

<script>
const $ = (id) => document.getElementById(id);
let corpus = [];

function escape(text) {
  const node = document.createElement("span");
  node.textContent = text;
  return node.innerHTML;
}

function showExamples() {
  const doc = corpus.find(d => d.document_id === $("doc").value);
  const questions = (doc && doc.example_questions) || [];
  $("examples").innerHTML = questions
    .map(q => `<button type="button" data-q="${escape(q)}">${escape(q)}</button>`)
    .join("");
  if (questions.length && !$("q").value.trim()) $("q").value = questions[0];
}

async function boot() {
  const [docs, health] = await Promise.all([
    fetch("/documents").then(r => r.json()),
    fetch("/health").then(r => r.json()),
  ]);
  $("snap").textContent = health.snapshot_id ? `Corpus ${health.snapshot_id}.` : "";
  if (!docs.length) {
    $("out").innerHTML = '<p class="reason">No corpus loaded. Set DISCLOSURE_RAG_CORPUS.</p>';
    $("ask").disabled = true;
    return;
  }
  corpus = docs;
  $("doc").innerHTML = docs
    .map(d => {
      const detail = `${d.pages} pages, ${d.tagged_facts} tagged facts`;
      const id = escape(d.document_id);
      return `<option value="${id}">${id} (${detail})</option>`;
    })
    .join("");
  showExamples();
}

// Document text is untrusted input, so nothing from a filing reaches innerHTML
// unescaped. The stated threat in this project is hidden text in a PDF; the
// same text arriving as a quote must not become markup here.
function tag(text) { return `<span class="tag">${escape(text)}</span>`; }

function show(answer, documentId) {
  const abstained = answer.status !== "answered";
  const exact = (answer.citations || []).some(c => c.exact);
  const cls = abstained ? "stop" : exact ? "exact" : "soft";

  const tags = [
    tag(`route: ${answer.route}`),
    tag(`confidence: ${answer.confidence.toFixed(2)}`),
    exact ? tag("citation: exact, the filer's own tag") : tag("citation: predicted"),
  ];
  if (answer.period) tags.push(tag(answer.period));
  if (answer.audit_id) tags.push(tag(`audit ${answer.audit_id}`));

  const headline = escape(abstained ? "No answer given" : answer.text);
  const body = abstained
    ? `<p class="reason">${escape(answer.reason || "not supported")}</p>`
    : "";

  $("out").innerHTML =
    `<div class="answer ${cls}">
       <p class="headline">${headline}</p>
       <div class="tags">${tags.join("")}</div>
       ${body}
     </div>`;

  const citation = (answer.citations || [])[0];
  if (!citation || !citation.spans.length) {
    $("pane").innerHTML = '<div class="empty">Nothing to show for this question.</div>';
    return;
  }
  const regions = citation.spans
    .map(s => [s.x0, s.y0, s.x1, s.y1].join(","))
    .join(";");
  const url = `/page/${encodeURIComponent(documentId)}/${citation.page}.png`
            + `?regions=${encodeURIComponent(regions)}&dpi=150`;
  const note = abstained ? "Nearest evidence considered" : "Cited region";
  const quote = citation.quote ? `, <code>${escape(citation.quote.slice(0, 200))}</code>` : "";
  $("pane").innerHTML =
    `<figure>
       <img src="${url}" alt="Page ${citation.page} with the cited region outlined">
       <figcaption>${note}, page ${citation.page}${quote}</figcaption>
     </figure>`;
}

async function ask() {
  const documentId = $("doc").value;
  const question = $("q").value.trim();
  if (!question) return;
  $("ask").disabled = true;
  $("out").innerHTML = '<p class="reason">Asking...</p>';
  try {
    const response = await fetch("/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, document_id: documentId }),
    });
    if (!response.ok) throw new Error(await response.text());
    show(await response.json(), documentId);
  } catch (error) {
    const message = escape(String(error));
    $("out").innerHTML = `<div class="answer stop"><p class="reason">${message}</p></div>`;
  } finally {
    $("ask").disabled = false;
  }
}

$("ask").addEventListener("click", ask);
$("doc").addEventListener("change", () => { $("q").value = ""; showExamples(); });
$("examples").addEventListener("click", (e) => {
  const button = e.target.closest("button[data-q]");
  if (!button) return;
  $("q").value = button.dataset.q;
  ask();
});
$("q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask();
});
boot();
</script>
</body>
</html>
"""
