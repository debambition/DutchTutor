const chatLog = document.getElementById("chatLog");
const userIdInput = document.getElementById("userId");
const textInput = document.getElementById("textInput");
const player = document.getElementById("player");
const feedbackLang = document.getElementById("feedbackLang");

function currentUserId() {
  return userIdInput.value.trim() || "demo-user";
}

function scrollChatToBottom() {
  chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: "smooth" });
}

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  chatLog.appendChild(div);
  scrollChatToBottom();
}

async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

document.getElementById("startBtn").addEventListener("click", async () => {
  appendMessage("system", "Starting session...");
  try {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/start`);
    appendMessage("assistant", reply);
    setProgressFilter("session");
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
  refreshProgress();
});

document.getElementById("endBtn").addEventListener("click", async () => {
  appendMessage("system", "Ending session...");
  try {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/end`);
    appendMessage("system", "Session ended.");
    appendMessage("assistant", reply);
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
  refreshProgress();
});

async function sendText() {
  const text = textInput.value.trim();
  if (!text) return;
  appendMessage("user", text);
  textInput.value = "";
  try {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/message`, { text });
    appendMessage("assistant", reply);
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
  refreshProgress();
}

document.getElementById("sendBtn").addEventListener("click", sendText);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendText();
});

// --- Feedback language (stored on the learner's profile) ---
async function loadProfile() {
  const res = await fetch(`/api/sessions/${currentUserId()}/profile`);
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
    const res = await fetch(`/api/sessions/${currentUserId()}/profile`);
    if (!res.ok) throw new Error(await res.text());
    const profile = { ...(await res.json()), feedback_language: feedbackLang.value };
    const put = await fetch(`/api/sessions/${currentUserId()}/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!put.ok) throw new Error(await put.text());
    appendMessage("system", `Feedback language set to ${feedbackLang.value}.`);
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

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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
      top.append(el("span", "item-text", item.text), el("span", "item-kind", item.kind));
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

async function refreshProgress() {
  try {
    const res = await fetch(`/api/sessions/${currentUserId()}/progress`);
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

userIdInput.addEventListener("change", () => {
  pickDefaultFilter = true;
  loadProfile();
  refreshProgress();
});
loadProfile();
refreshProgress();

// --- Voice recording (hold the mic button to talk) ---
// Azure speech-to-text only accepts WAV/OGG. Rather than decoding the
// browser's compressed MediaRecorder output (WebM/MP4, which decodeAudioData
// rejects in some browsers), capture raw PCM from the mic via Web Audio and
// encode it as 16 kHz mono 16-bit PCM WAV.
const TARGET_SAMPLE_RATE = 16000;
const MIN_RECORDING_SECONDS = 0.3;

let recording = null; // { ctx, stream, source, processor, pcm: Float32Array[] }
let stopRequested = false;

async function startRecording() {
  if (recording) return;
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

async function sendRecording(samples, sampleRate) {
  appendMessage("system", "Transcribing...");
  try {
    const form = new FormData();
    form.append("audio", await toWav(samples, sampleRate), "speech.wav");

    const res = await fetch(`/api/sessions/${currentUserId()}/voice`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    appendMessage("user", data.user_text);
    appendMessage("assistant", data.reply);
    refreshProgress();
    if (data.reply_audio_base64) {
      player.src = `data:audio/mp3;base64,${data.reply_audio_base64}`;
      player.hidden = false;
      player.play();
    }
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
}

const micBtn = document.getElementById("micBtn");
micBtn.addEventListener("mousedown", startRecording);
micBtn.addEventListener("mouseup", stopRecording);
micBtn.addEventListener("mouseleave", () => {
  if (recording) stopRecording();
});
