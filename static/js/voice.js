let activeAudio = null;
let activeAudioUrl = null;

function cleanupActiveAudio() {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio = null;
  }
  if (activeAudioUrl) {
    URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
  }
}

document.addEventListener("speak", async (event) => {
  const message = (event?.detail?.message || "").trim();
  if (!message) {
    return;
  }

  const csrftoken = document.body.dataset.csrftoken;

  try {
    const response = await fetch("/api/tts/", {
      method: "POST",
      headers: {
        "X-CSRFToken": csrftoken,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text: message }),
    });

    if (!response.ok) {
      let errorPayload = { detail: "tts_request_failed" };
      try {
        errorPayload = await response.json();
      } catch (_) {
        // Keep fallback error payload.
      }
      console.error("TTS request failed:", errorPayload);
      return;
    }

    const blob = await response.blob();
    if (!blob.size) {
      return;
    }

    cleanupActiveAudio();
    activeAudioUrl = URL.createObjectURL(blob);
    activeAudio = new Audio(activeAudioUrl);
    activeAudio.addEventListener("ended", cleanupActiveAudio, { once: true });
    activeAudio.addEventListener("error", cleanupActiveAudio, { once: true });

    await activeAudio.play();
  } catch (error) {
    console.error("Error fetching TTS audio:", error);
  }
});
