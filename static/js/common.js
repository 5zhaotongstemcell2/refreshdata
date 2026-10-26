(function () {
  "use strict";

  const DV = window.DV || {};
  window.DV = DV;

  DV.escapeHtml = function (value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (char) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[char];
    });
  };

  DV.api = async function (url, options) {
    const opts = Object.assign({}, options || {});
    const headers = Object.assign({}, opts.headers || {});
    if (opts.body && !(opts.body instanceof FormData) && !(opts.body instanceof URLSearchParams)) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    opts.headers = headers;

    let response;
    try {
      response = await fetch(url, opts);
    } catch (error) {
      throw new Error("网络请求失败，请确认服务仍在运行。");
    }

    const contentType = response.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("application/json")) {
      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }
    }
    if (!response.ok || (data && data.ok === false)) {
      const message = (data && data.error) || "请求失败（HTTP " + response.status + "）";
      throw new Error(message);
    }
    return data;
  };

  DV.toast = function (message, type, timeout) {
    const element = document.getElementById("toast");
    if (!element) return;
    type = type || "info";
    element.textContent = message;
    element.className = "toast toast-" + type;
    element.hidden = false;
    window.clearTimeout(DV._toastTimer);
    DV._toastTimer = window.setTimeout(
      function () {
        element.hidden = true;
      },
      timeout || (type === "error" ? 6000 : 4200)
    );
  };

  DV.flash = function (message, type) {
    try {
      sessionStorage.setItem(
        "dv-flash",
        JSON.stringify({ message: message, type: type || "success", time: Date.now() })
      );
    } catch (error) {
      DV.toast(message, type);
    }
  };

  DV.consumeFlash = function () {
    try {
      const raw = sessionStorage.getItem("dv-flash");
      if (!raw) return;
      sessionStorage.removeItem("dv-flash");
      const payload = JSON.parse(raw);
      if (payload && payload.message && Date.now() - payload.time < 30000) {
        DV.toast(payload.message, payload.type || "success");
      }
    } catch (error) {
      sessionStorage.removeItem("dv-flash");
    }
  };

  DV.debounce = function (fn, wait) {
    let timer = null;
    return function () {
      const args = arguments;
      const context = this;
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        fn.apply(context, args);
      }, wait);
    };
  };

  DV.number = function (value, digits) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return number.toLocaleString("zh-CN", {
      maximumFractionDigits: digits === undefined ? 2 : digits,
      minimumFractionDigits: 0,
    });
  };

  DV.setBusy = function (button, busy, busyText) {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.disabled = true;
      if (busyText) button.textContent = busyText;
    } else {
      button.disabled = false;
      if (button.dataset.originalText) button.textContent = button.dataset.originalText;
    }
  };

  DV.filenameFromDisposition = function (header, fallback) {
    if (!header) return fallback || "download";
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (encoded) {
      try {
        return decodeURIComponent(encoded[1]);
      } catch (error) {
        /* ignore */
      }
    }
    const normal = /filename="?([^";]+)"?/i.exec(header);
    return normal ? normal[1] : fallback || "download";
  };

  DV.download = async function (url, options, fallbackName) {
    let response;
    try {
      response = await fetch(url, options || {});
    } catch (error) {
      throw new Error("下载失败，请确认服务仍在运行。");
    }
    if (!response.ok) {
      let message = "下载失败（HTTP " + response.status + "）";
      try {
        const data = await response.json();
        if (data && data.error) message = data.error;
      } catch (error) {
        /* ignore */
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const filename = DV.filenameFromDisposition(
      response.headers.get("content-disposition"),
      fallbackName
    );
    const blobUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(blobUrl);
    }, 1500);
  };

  document.addEventListener("DOMContentLoaded", function () {
    DV.consumeFlash();
  });
})();
