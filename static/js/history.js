(function () {
  "use strict";

  const dialog = document.getElementById("detailDialog");
  const content = document.getElementById("detailContent");
  if (!dialog || !content) return;

  function closeDialog() {
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  document.querySelectorAll(".js-log-detail").forEach(function (button) {
    button.addEventListener("click", function () {
      let detail = {};
      try {
        detail = JSON.parse(button.dataset.detail || "{}");
      } catch (error) {
        detail = { raw: button.dataset.detail };
      }
      content.textContent = JSON.stringify(detail, null, 2);
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        window.alert(content.textContent);
      }
    });
  });

  const closeButton = document.getElementById("closeDetailBtn");
  const closeButton2 = document.getElementById("closeDetailBtn2");
  if (closeButton) closeButton.addEventListener("click", closeDialog);
  if (closeButton2) closeButton2.addEventListener("click", closeDialog);

  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      const inside =
        event.clientX >= rect.left &&
        event.clientX <= rect.right &&
        event.clientY >= rect.top &&
        event.clientY <= rect.bottom;
      if (!inside) closeDialog();
    }
  });
})();
