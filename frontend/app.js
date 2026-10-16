const chatLog = document.getElementById("chatLog");
const textInput = document.getElementById("textInput");
const player = document.getElementById("player");
const feedbackLang = document.getElementById("feedbackLang");
const startBtn = document.getElementById("startBtn");
const endBtn = document.getElementById("endBtn");
const sendBtn = document.getElementById("sendBtn");
const micBtn = document.getElementById("micBtn");

// --- Sign-in ---
// The token is kept in localStorage so a reload stays signed in; every API
// call sends it, and a 401 brings the sign-in form back.
const AUTH_KEY = "dutchTutorAuth";
let authState = null; // { userId, token }

function loadAuth() {
  try {
    authState = JSON.parse(localStorage.getItem(AUTH_KEY)) || null;
  } catch {
    authState = null;
  }
}

function saveAuth(state) {
  authState = state;
  try {
    if (state) localStorage.setItem(AUTH_KEY, JSON.stringify(state));
    else localStorage.removeItem(AUTH_KEY);
  } catch {
    // Storage unavailable (private mode): stay signed in for this page only.
  }
}

function currentUserId() {
  return authState ? authState.userId : "";
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authState) headers.Authorization = `Bearer ${authState.token}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    showSignIn("Please sign in again.");
    throw new Error("Please sign in.");
  }
  return res;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollChatToBottom() {
  chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: "smooth" });
}

// --- Minimal, safe markdown for tutor replies ---
// Builds DOM nodes (never innerHTML), supporting **bold**, *italic*, `code`,
// bullet/numbered lists and paragraphs — what the tutor actually produces.
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*|`[^`\n]+`)/;

function renderInline(text) {
  const frag = document.createDocumentFragment();
  for (const part of text.split(INLINE)) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      frag.append(el("strong", "", part.slice(2, -2)));
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      frag.append(el("code", "", part.slice(1, -1)));
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      frag.append(el("em", "", part.slice(1, -1)));
    } else {
      frag.append(part);
    }
  }
  return frag;
}

function renderMarkdown(text) {
  const frag = document.createDocumentFragment();
  let list = null;
  let para = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const tag = bullet ? "UL" : "OL";
      if (!list || list.tagName !== tag) {
        list = document.createElement(tag.toLowerCase());
        frag.append(list);
      }
      const li = el("li");
      li.append(renderInline((bullet || numbered)[1]));
      list.append(li);
      para = null;
      continue;
    }
    list = null;
    if (!line.trim()) {
      para = null;
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (para) para.append(el("br"));
    else {
      para = el("p");
      frag.append(para);
    }
    para.append(heading ? el("strong", "", heading[1]) : renderInline(line));
  }
  return frag;
}

// --- Reply audio: play any tutor message, normal or slow ---
let playingButton = null;

async function playReply(div, slow, button) {
  const key = slow ? "slow" : "normal";
  div._audio = div._audio || {};
  try {
    if (!div._audio[key]) {
      button.disabled = true;
      const res = await api("/api/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: div._text, slow }),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      if (!blob.size) throw new Error("no audio (speech provider is in mock mode)");
      div._audio[key] = URL.createObjectURL(blob);
    }
    playAudio(div._audio[key], button);
  } catch (err) {
    appendMessage("system", `Error: could not play audio (${err.message})`);
  } finally {
    button.disabled = false;
  }
}

function playAudio(src, button) {
  if (playingButton) playingButton.classList.remove("playing");
  player.src = src;
  player.play();
  playingButton = button || null;
  if (button) button.classList.add("playing");
}

player.addEventListener("ended", () => {
  if (playingButton) playingButton.classList.remove("playing");
  playingButton = null;
});

function audioActions(div) {
  const actions = el("div", "msg-actions");
  const play = el("button", "chip", "▶ Play");
  const slow = el("button", "chip", "🐢 Slow");
  play.title = "Play this reply";
  slow.title = "Play this reply slowly";
  play.addEventListener("click", () => playReply(div, false, play));
  slow.addEventListener("click", () => playReply(div, true, slow));
  actions.append(play, slow);
  return actions;
}

function appendMessage(role, content) {
  const div = el("div", `msg ${role}`);
  div._text = content;
  if (role === "assistant") {
    const body = el("div", "msg-body");
    body.append(renderMarkdown(content));
    div.append(body, audioActions(div));
  } else {
    div.textContent = content;
  }
  chatLog.appendChild(div);
  scrollChatToBottom();
  return div;
}

// --- Busy state + "thinking" indicator ---
let busy = false;

function setBusy(value, label = "Tutor is thinking") {
  busy = value;
  for (const btn of [startBtn, endBtn, sendBtn, micBtn]) btn.disabled = value;
  document.getElementById("thinking")?.remove();
  if (value) {
    const bubble = el("div", "msg assistant thinking");
    bubble.id = "thinking";
    bubble.setAttribute("aria-label", label);
    bubble.append(el("span", "thinking-label", label), el("span", "dots"));
    bubble.querySelector(".dots").append(el("i"), el("i"), el("i"));
    chatLog.appendChild(bubble);
    scrollChatToBottom();
  }
}

async function postJson(path, body) {
  const res = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail;
    try {
      message = JSON.parse(detail).detail || detail;
    } catch {}
    throw new Error(message);
  }
  return res.json();
}

async function run(label, task) {
  if (busy) return;
  setBusy(true, label);
  try {
    await task();
  } catch (err) {
    setBusy(false);
    appendMessage("system", `Error: ${err.message}`);
  } finally {
    setBusy(false);
    refreshProgress();
  }
}

startBtn.addEventListener("click", () =>
  run("Starting session", async () => {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/start`);
    chatLog.replaceChildren();
    setBusy(false);
    appendMessage("assistant", reply);
    setProgressFilter("session");
  })
);

endBtn.addEventListener("click", () =>
  run("Writing your session summary", async () => {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/end`);
    setBusy(false);
    appendMessage("system", "Session ended.");
    appendMessage("assistant", reply);
  })
);

function sendText() {
  const text = textInput.value.trim();
  if (!text || busy) return;
  appendMessage("user", text);
  textInput.value = "";
  run("Tutor is thinking", async () => {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/message`, { text });
    setBusy(false);
    appendMessage("assistant", reply);
  });
}

sendBtn.addEventListener("click", sendText);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendText();
});

// --- Restore the current conversation on load ---
async function loadConversation() {
  chatLog.replaceChildren();
  try {
    const res = await api(`/api/sessions/${currentUserId()}/conversation`);
    if (!res.ok) return;
    const turns = await res.json();
    if (!turns.length) {
      appendMessage("system", "Press “Start session” to begin.");
      return;
    }
    for (const turn of turns) appendMessage(turn.role, turn.content);
    chatLog.scrollTop = chatLog.scrollHeight;
  } catch {
    // Starting fresh is fine if history can't be loaded.
  }
}

// --- Feedback language (stored on the learner's profile) ---
async function loadProfile() {
  const res = await api(`/api/sessions/${currentUserId()}/profile`);
  if (!res.ok) return;
  const profile = await res.json();
  const language = profile.feedback_language || profile.native_languages[0] || "English";
  if (![...feedbackLang.options].some((o) => o.value === language)) {
    feedbackLang.add(new Option(language));
  }
  feedbackLang.value = language;
}

feedbackLang.addEventListener("change", async () => {
  try {
    const res = await api(`/api/sessions/${currentUserId()}/profile`);
    if (!res.ok) throw new Error(await res.text());
    const profile = { ...(await res.json()), feedback_language: feedbackLang.value };
    const put = await api(`/api/sessions/${currentUserId()}/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!put.ok) throw new Error(await put.text());
    appendMessage("system", `Explanations will be in ${feedbackLang.value}.`);
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
});

// --- Progress panel ---
const SKILL_LABELS = {
  listening: "Listening",
  speaking: "Speaking",
  reading: "Reading",
  writing: "Writing",
  grammar_vocab: "Grammar & vocab",
};
const progressPanel = document.getElementById("progressPanel");
let progressFilter = "session";
let progressData = null;
// On first load for a user, fall back to "All" when the current session has
// nothing yet, so past progress is visible straight away.
let pickDefaultFilter = true;

function setProgressFilter(filter) {
  progressFilter = filter;
  document.querySelectorAll(".filter button").forEach((b) =>
    b.classList.toggle("active", b.dataset.filter === filter)
  );
}

// Same rule as the backend's skill progress: strong = 80%+ over 2+ attempts.
function isStrong(item) {
  return item.attempts >= 2 && item.score >= 80;
}

function scoreBand(item) {
  const { score } = item;
  if (score === null) return { cls: "", label: "New" };
  if (isStrong(item)) return { cls: "strong", label: "Strong" };
  if (score >= 80) return { cls: "strong", label: "Good start" };
  if (score >= 50) return { cls: "okay", label: "Getting there" };
  return { cls: "weak", label: "Needs practice" };
}

function renderProgress() {
  if (!progressData) return;
  const items = progressData.items.filter((i) => progressFilter === "all" || i.this_session);
  const practised = items.filter((i) => i.score !== null);

  document.getElementById("statCovered").textContent = items.length;
  document.getElementById("statAvg").textContent = practised.length
    ? `${Math.round(practised.reduce((n, i) => n + i.score, 0) / practised.length)}%`
    : "–";
  document.getElementById("statStrong").textContent = practised.filter(isStrong).length;
  document.getElementById("statWeak").textContent = practised.filter((i) => i.score < 50).length;

  const due = progressData.items.filter((i) => i.due).length;
  document.getElementById("dueNote").textContent = due
    ? `${due} item${due === 1 ? "" : "s"} due for review — drills pick these first.`
    : "Nothing due for review right now.";

  const levels = document.getElementById("levels");
  levels.replaceChildren(
    ...progressData.skills.map((p) => {
      const row = el("div", `level${p.next_level && p.percent >= 100 ? " ready" : ""}`);
      const top = el("div", "level-top");
      top.append(
        el("span", "level-name", SKILL_LABELS[p.skill] || p.skill),
        el("span", "level-badge", p.next_level ? `${p.level} → ${p.next_level}` : p.level)
      );
      row.append(top);
      if (!p.next_level) {
        row.append(el("div", "level-detail", "Top level reached"));
        return row;
      }
      const bar = el("div", "bar");
      const fill = el("span");
      fill.style.width = `${p.percent}%`;
      bar.append(fill);
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", `${p.percent}% of the way to ${p.next_level}`);
      row.append(bar);
      const detail = p.percent >= 100
        ? `Ready for a ${p.next_level} check`
        : `${p.strong_items}/${p.target} strong` +
          (p.accuracy === null ? " · no attempts yet" : ` · ${p.accuracy}% accuracy`);
      row.append(el("div", "level-detail", detail));
      return row;
    })
  );

  renderHistory(progressData.history);

  const list = document.getElementById("items");
  if (!items.length) {
    list.replaceChildren(
      el("li", "empty", progressFilter === "all"
        ? "Words and sentences appear here as you learn them."
        : "Nothing covered yet this session.")
    );
    return;
  }
  list.replaceChildren(
    ...items.map((item) => {
      const { cls, label } = scoreBand(item);
      const li = el("li", `item ${cls}`);
      const top = el("div", "item-top");
      const tags = el("span", "item-tags");
      if (item.due) tags.append(el("span", "due-badge", "Review due"));
      tags.append(el("span", "item-kind", item.kind));
      top.append(el("span", "item-text", item.text), tags);
      li.append(top);
      if (item.translation) li.append(el("div", "item-translation", item.translation));

      const score = el("div", "item-score");
      const bar = el("div", "bar");
      const fill = el("span");
      fill.style.width = `${item.score ?? 0}%`;
      bar.append(fill);
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", item.score === null ? "Not practised yet" : `Score ${item.score}%`);
      const detail = item.score === null
        ? "not practised yet"
        : `${item.score}% · ${item.correct}/${item.attempts} correct`;
      score.append(el("span", "label", label), bar, el("span", "", detail));
      li.append(score);
      return li;
    })
  );
}

// --- Level history: one small step chart per skill (small multiples) ---
// Five skills usually share a level, so one multi-line chart would overplot;
// separate panels on a shared scale keep each readable with a single hue.
const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];
const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

const historyTip = el("div", "chart-tip");
historyTip.hidden = true;
document.body.append(historyTip);

function renderHistory(history) {
  const box = document.getElementById("history");
  const table = document.getElementById("historyTable");
  if (history.length < 2) {
    box.replaceChildren(el("p", "empty", "Your level history appears after your first session."));
    table.replaceChildren();
    return;
  }
  // Shared y-scale: A1 up to one level above the highest reached.
  const top = Math.min(
    LEVELS.length - 1,
    Math.max(1, ...history.flatMap((h) => Object.values(h.levels).map((l) => LEVELS.indexOf(l)))) + 1
  );
  const W = 300, H = 22 + top * 16, padL = 24, padR = 10, padT = 8, padB = 6;
  const x = (i) => padL + (i * (W - padL - padR)) / (history.length - 1);
  const y = (lvl) => padT + ((top - lvl) * (H - padT - padB)) / top;

  box.replaceChildren(
    ...Object.keys(SKILL_LABELS).map((skill) => {
      const panel = el("div", "history-panel");
      const points = history
        .map((h, i) => ({ i, h, lvl: LEVELS.indexOf(h.levels[skill]) }))
        .filter((p) => p.lvl >= 0);
      const now = points.length ? LEVELS[points[points.length - 1].lvl] : "–";
      const head = el("div", "history-head");
      head.append(el("span", "level-name", SKILL_LABELS[skill]), el("span", "level-badge", now));
      panel.append(head);

      const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "history-chart", role: "img" });
      chart.setAttribute("aria-label", `${SKILL_LABELS[skill]} level by session, now ${now}`);
      for (let lvl = 0; lvl <= top; lvl++) {
        chart.append(svg("line", { x1: padL, x2: W - padR, y1: y(lvl), y2: y(lvl), class: "grid" }));
        const label = svg("text", { x: padL - 6, y: y(lvl) + 3, class: "tick" });
        label.textContent = LEVELS[lvl];
        chart.append(label);
      }
      if (points.length) {
        // Step line: a level holds until the next snapshot.
        let d = `M${x(points[0].i)},${y(points[0].lvl)}`;
        for (const p of points.slice(1)) d += ` H${x(p.i)} V${y(p.lvl)}`;
        chart.append(svg("path", { d, class: "step" }));
        for (const p of points) {
          const dot = svg("circle", { cx: x(p.i), cy: y(p.lvl), r: 4, class: "dot" });
          const hit = svg("circle", { cx: x(p.i), cy: y(p.lvl), r: 11, class: "hit" });
          const tip = `${p.h.label === "Now" ? "Now" : `Session ${p.h.label.slice(1)}`} · ${p.h.date} · ${LEVELS[p.lvl]}`;
          hit.addEventListener("pointerenter", (e) => {
            historyTip.textContent = tip;
            historyTip.hidden = false;
            const r = e.target.getBoundingClientRect();
            historyTip.style.left = `${r.left + r.width / 2}px`;
            historyTip.style.top = `${r.top}px`;
            dot.classList.add("active");
          });
          hit.addEventListener("pointerleave", () => {
            historyTip.hidden = true;
            dot.classList.remove("active");
          });
          chart.append(dot, hit);
        }
      }
      panel.append(chart);
      return panel;
    })
  );

  // Table view of the same data, for screen readers and exact values.
  const thead = el("tr");
  thead.append(el("th", "", "Skill"), ...history.map((h) => el("th", "", h.label)));
  table.replaceChildren(
    thead,
    ...Object.entries(SKILL_LABELS).map(([skill, label]) => {
      const row = el("tr");
      row.append(el("th", "", label), ...history.map((h) => el("td", "", h.levels[skill] || "–")));
      return row;
    })
  );
}

async function refreshProgress() {
  try {
    const res = await api(`/api/sessions/${currentUserId()}/progress`);
    if (!res.ok) return;
    progressData = await res.json();
    if (pickDefaultFilter) {
      pickDefaultFilter = false;
      setProgressFilter(progressData.items.some((i) => i.this_session) ? "session" : "all");
    }
    renderProgress();
  } catch {
    // The panel is informational; a failed refresh shouldn't interrupt the chat.
  }
}

document.querySelectorAll(".filter button").forEach((btn) =>
  btn.addEventListener("click", () => {
    setProgressFilter(btn.dataset.filter);
    renderProgress();
  })
);

const progressToggle = document.getElementById("progressToggle");
function setProgressOpen(open) {
  progressPanel.classList.toggle("open", open);
  progressToggle.setAttribute("aria-expanded", String(open));
}
progressToggle.addEventListener("click", () => setProgressOpen(!progressPanel.classList.contains("open")));
document.getElementById("progressClose").addEventListener("click", () => setProgressOpen(false));

// --- Listening & reading drills (graded by the server, shown in the chat) ---
async function startDrill(kind) {
  setProgressOpen(false);
  const card = el("div", "msg drill");
  chatLog.appendChild(card);
  card.append(el("div", "drill-title", kind === "listening" ? "🎧 Listening drill" : "📖 Reading drill"));
  const body = el("div", "drill-body", "Loading…");
  card.append(body);
  scrollChatToBottom();

  let drill;
  try {
    drill = await postJson(`/api/sessions/${currentUserId()}/drills/${kind}`);
  } catch (err) {
    body.textContent = err.message;
    return;
  }
  body.replaceChildren();

  const submit = async (answer, controls) => {
    controls.forEach((c) => (c.disabled = true));
    try {
      const result = await postJson(`/api/sessions/${currentUserId()}/drills/${kind}/answer`, {
        prompt_id: drill.prompt_id,
        answer,
      });
      const verdict = el("div", `drill-result ${result.correct ? "right" : "wrong"}`);
      verdict.append(
        el("strong", "", result.correct ? "✅ Correct!" : result.close ? "🟡 Close — check the spelling." : "❌ Not quite."),
        el("div", "", `${result.expected}${result.translation ? ` — ${result.translation}` : ""}`)
      );
      const next = el("button", "chip", "Next →");
      next.addEventListener("click", () => startDrill(kind));
      verdict.append(next);
      card.append(verdict);
      scrollChatToBottom();
      refreshProgress();
    } catch (err) {
      controls.forEach((c) => (c.disabled = false));
      appendMessage("system", `Error: ${err.message}`);
    }
  };

  if (kind === "listening") {
    body.append(el("div", "", "Listen, then type exactly what you hear."));
    const audioRow = el("div", "msg-actions");
    const play = el("button", "chip", "▶ Play");
    const slow = el("button", "chip", "🐢 Slow");
    play.addEventListener("click", () => playAudio(`data:audio/mp3;base64,${drill.audio_base64}`, play));
    slow.addEventListener("click", () => playAudio(`data:audio/mp3;base64,${drill.audio_slow_base64}`, slow));
    audioRow.append(play, slow);
    const form = el("form", "drill-form");
    const input = el("input");
    input.placeholder = "Type what you heard…";
    input.setAttribute("aria-label", "What you heard");
    const check = el("button", "", "Check");
    form.append(input, check);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (input.value.trim()) submit(input.value, [input, check]);
    });
    body.append(audioRow, form);
    if (drill.audio_base64) playAudio(`data:audio/mp3;base64,${drill.audio_base64}`, play);
    input.focus();
  } else {
    body.append(el("div", "", "What does this mean?"), el("div", "drill-dutch", drill.text));
    const options = el("div", "drill-options");
    const buttons = drill.options.map((option) => {
      const btn = el("button", "option", option);
      btn.addEventListener("click", () => {
        btn.classList.add("chosen");
        submit(option, buttons);
      });
      return btn;
    });
    options.append(...buttons);
    body.append(options);
  }
  scrollChatToBottom();
}

document.getElementById("listenDrillBtn").addEventListener("click", () => startDrill("listening"));
document.getElementById("readDrillBtn").addEventListener("click", () => startDrill("reading"));

// --- Voice recording (hold the mic button to talk) ---
// Azure speech-to-text only accepts WAV/OGG. Rather than decoding the
// browser's compressed MediaRecorder output (WebM/MP4, which decodeAudioData
// rejects in some browsers), capture raw PCM from the mic via Web Audio and
// encode it as 16 kHz mono 16-bit PCM WAV.
const TARGET_SAMPLE_RATE = 16000;
const MIN_RECORDING_SECONDS = 0.3;
const WEAK_PRONUNCIATION_SCORE = 75;

let recording = null; // { ctx, stream, source, processor, pcm: Float32Array[] }
let stopRequested = false;

async function startRecording() {
  if (recording || busy) return;
  stopRequested = false;
  // Create the AudioContext synchronously inside the user gesture (Safari).
  const ctx = new AudioContext();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    ctx.close();
    appendMessage("system", `Error: microphone unavailable (${err.message})`);
    return;
  }
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  const pcm = [];
  processor.onaudioprocess = (e) => pcm.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(processor);
  processor.connect(ctx.destination);
  recording = { ctx, stream, source, processor, pcm };
  micBtn.classList.add("recording");
  // The button was released while mic access was still starting.
  if (stopRequested) stopRecording();
}

function stopRecording() {
  if (!recording) {
    stopRequested = true;
    return;
  }
  const { ctx, stream, source, processor, pcm } = recording;
  recording = null;
  micBtn.classList.remove("recording");
  source.disconnect();
  processor.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  const sampleRate = ctx.sampleRate;
  ctx.close();

  const total = pcm.reduce((n, c) => n + c.length, 0);
  if (total / sampleRate < MIN_RECORDING_SECONDS) {
    appendMessage("system", "Hold the mic button while you speak.");
    return;
  }
  const samples = new Float32Array(total);
  let offset = 0;
  for (const c of pcm) {
    samples.set(c, offset);
    offset += c.length;
  }
  sendRecording(samples, sampleRate);
}

async function toWav(input, inputRate) {
  const length = Math.ceil((input.length / inputRate) * TARGET_SAMPLE_RATE);
  const offline = new OfflineAudioContext(1, length, TARGET_SAMPLE_RATE);
  const decoded = offline.createBuffer(1, input.length, inputRate);
  decoded.copyToChannel(input, 0);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => {
    const clamped = Math.max(-1, Math.min(1, s));
    view.setInt16(44 + i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return new Blob([buffer], { type: "audio/wav; codecs=audio/pcm; samplerate=16000" });
}

function pronunciationBlock(p) {
  const block = el("div", "pron");
  block.append(
    el("span", "pron-score", `🗣️ Pronunciation ${Math.round(p.overall)}`),
    el("span", "", ` · accuracy ${Math.round(p.accuracy)} · fluency ${Math.round(p.fluency)}`)
  );
  const weak = p.words.filter(([, score]) => score < WEAK_PRONUNCIATION_SCORE);
  if (weak.length) {
    const words = el("div", "pron-words");
    words.append("Work on: ");
    for (const [word, score] of weak) words.append(el("span", "pron-word", `${word} ${Math.round(score)}`));
    block.append(words);
  }
  return block;
}

async function sendRecording(samples, sampleRate) {
  run("Listening and thinking", async () => {
    const form = new FormData();
    form.append("audio", await toWav(samples, sampleRate), "speech.wav");
    const res = await api(`/api/sessions/${currentUserId()}/voice`, { method: "POST", body: form });
    if (!res.ok) {
      const detail = await res.text();
      let message = detail;
      try {
        message = JSON.parse(detail).detail || detail;
      } catch {}
      throw new Error(message);
    }
    const data = await res.json();
    setBusy(false);
    const userMsg = appendMessage("user", data.user_text);
    if (data.pronunciation) userMsg.append(pronunciationBlock(data.pronunciation));
    const reply = appendMessage("assistant", data.reply);
    if (data.reply_audio_base64) {
      const src = `data:audio/mp3;base64,${data.reply_audio_base64}`;
      reply._audio = { normal: src };
      playAudio(src, reply.querySelector(".msg-actions .chip"));
    }
  });
}

// Pointer events cover mouse, touch and pen, so hold-to-talk works on phones.
micBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  micBtn.setPointerCapture(e.pointerId);
  startRecording();
});
micBtn.addEventListener("pointerup", stopRecording);
micBtn.addEventListener("pointercancel", () => {
  if (recording) stopRecording();
});
micBtn.addEventListener("contextmenu", (e) => e.preventDefault());

// --- Initial load ---
const signInDialog = document.getElementById("signIn");
const signInForm = document.getElementById("signInForm");
const signInError = document.getElementById("signInError");

function showSignIn(message = "") {
  saveAuth(null);
  document.getElementById("whoami").textContent = "";
  signInError.textContent = message;
  signInDialog.hidden = false;
  document.getElementById("signInUser").focus();
}

signInForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submit = signInForm.querySelector("button");
  submit.disabled = true;
  signInError.textContent = "";
  try {
    const res = await fetch("/api/auth/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: document.getElementById("signInUser").value.trim(),
        passphrase: document.getElementById("signInPass").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Sign-in failed.");
    saveAuth({ userId: data.user_id, token: data.token });
    document.getElementById("signInPass").value = "";
    signInDialog.hidden = true;
    loadUser();
    if (data.created) appendMessage("system", `Passphrase set for “${data.user_id}”. Keep it safe — you'll need it to sign in again.`);
  } catch (err) {
    signInError.textContent = err.message;
  } finally {
    submit.disabled = false;
  }
});

document.getElementById("signOutBtn").addEventListener("click", () => {
  chatLog.replaceChildren();
  progressData = null;
  showSignIn();
});

function loadUser() {
  document.getElementById("whoami").textContent = `Signed in as ${currentUserId()}`;
  pickDefaultFilter = true;
  loadProfile();
  loadConversation();
  refreshProgress();
}

loadAuth();
if (authState) {
  signInDialog.hidden = true;
  loadUser();
} else {
  showSignIn();
}
