const chatLog = document.getElementById("chatLog");
const userIdInput = document.getElementById("userId");
const textInput = document.getElementById("textInput");
const player = document.getElementById("player");

function currentUserId() {
  return userIdInput.value.trim() || "demo-user";
}

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
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
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
});

document.getElementById("endBtn").addEventListener("click", async () => {
  try {
    const { reply } = await postJson(`/api/sessions/${currentUserId()}/end`);
    appendMessage("system", "Session ended.");
    appendMessage("assistant", reply);
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`);
  }
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
}

document.getElementById("sendBtn").addEventListener("click", sendText);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendText();
});

// --- Voice recording (hold the mic button to talk) ---
let mediaRecorder = null;
let chunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  chunks = [];
  mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    sendRecording();
  };
  mediaRecorder.start();
}

// Azure speech-to-text only accepts WAV/OGG, while browsers record WebM, so
// decode the recording and re-encode it as 16 kHz mono 16-bit PCM WAV.
const TARGET_SAMPLE_RATE = 16000;

async function toWav(blob) {
  const decodeCtx = new AudioContext();
  const decoded = await decodeCtx.decodeAudioData(await blob.arrayBuffer());
  decodeCtx.close();

  const length = Math.ceil(decoded.duration * TARGET_SAMPLE_RATE);
  const offline = new OfflineAudioContext(1, length, TARGET_SAMPLE_RATE);
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

async function sendRecording() {
  appendMessage("system", "Transcribing...");
  try {
    const recorded = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
    const form = new FormData();
    form.append("audio", await toWav(recorded), "speech.wav");

    const res = await fetch(`/api/sessions/${currentUserId()}/voice`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    appendMessage("user", data.user_text);
    appendMessage("assistant", data.reply);
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
micBtn.addEventListener("mouseup", () => mediaRecorder && mediaRecorder.stop());
micBtn.addEventListener("mouseleave", () => {
  if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
});
