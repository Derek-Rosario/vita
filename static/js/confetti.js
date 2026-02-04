document.addEventListener("DOMContentLoaded", () => {
  document.addEventListener("confetti", function (event) {
    confetti({
      particleCount: 100,
      spread: 70,
      origin: { y: 0.6 },
    });
  });
});
