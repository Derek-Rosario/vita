document.addEventListener("DOMContentLoaded", () => {
  const toastContainer = document.querySelector(".toast-container");
  const toastTemplate = document.getElementById("task-toast-template");

  function toast({ type = "info", header, message = "" }) {
    const toastClone = toastTemplate.content.cloneNode(true);
    const toastElement = toastClone.querySelector(".toast");
    const toastBody = toastClone.querySelector(".toast-body");
    const toastTitle = toastClone.querySelector(".toast-header .toast-title");

    toastBody.textContent = message;
    if (header) {
      toastTitle.textContent = header;
    } else {
      // remove header if not provided
      toastClone.querySelector(".toast-header").remove();
    }

    if (type === "success") {
      toastElement.classList.add("bg-success", "text-white");
    } else if (type === "error") {
      toastElement.classList.add("bg-danger", "text-white");
    } else if (type === "warning") {
      toastElement.classList.add("bg-warning", "text-dark");
    } else {
      toastElement.classList.add("bg-info", "text-white");
    }

    toastContainer.appendChild(toastClone);
    const bsToast = new bootstrap.Toast(toastElement);
    bsToast.show();

    toastElement.addEventListener("hidden.bs.toast", () => {
      toastElement.remove();
    });
  }

  document.addEventListener("toastMessage", function (event) {
    toast(event.detail);
  });
});
