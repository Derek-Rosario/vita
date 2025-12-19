document.addEventListener("speak", function (event) {
  // Get CSRF token from body element data attribute
  const csrftoken = document.body.dataset.csrftoken;

  // Make an API call to the TTS endpoint
  fetch("/api/tts/", {
    method: "POST",
    headers: {
      "X-CSRFToken": csrftoken,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text: event.detail.message }),
  })
    .then((response) => response.blob())
    .then((blob) => {
      const audio = new Audio(URL.createObjectURL(blob));
      audio.play();
    })
    .catch((error) => {
      const errorData = error.response
        ? error.response.json()
        : { detail: "Unknown error" };
      console.error("Error fetching TTS audio:", errorData);
    });
});
