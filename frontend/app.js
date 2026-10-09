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
  mediaRecorder.onstop = sendRecording;
  mediaRecorder.start();
}

async function sendRecording() {
  const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
  const form = new FormData();
  form.append("audio", blob, "speech.webm");

  appendMessage("system", "Transcribing...");
  try {
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
