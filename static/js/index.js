(function () {
  "use strict";

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const uploadError = document.getElementById("uploadError");
  const inspectPanel = document.getElementById("inspectPanel");
  const fileSummary = document.getElementById("fileSummary");
  const importOptions = document.getElementById("importOptions");
  const previewTable = document.getElementById("previewTable");
  const previewHint = document.getElementById("previewHint");
  const importBtn = document.getElementById("importBtn");
  const importStatus = document.getElementById("importStatus");
  const cancelBtn = document.getElementById("cancelBtn");

  if (!dropzone || !fileInput) return;

  let current = null;
  let refreshTimer = null;

  const ENCODINGS = [
    ["auto", "自动识别"],
    ["utf-8", "UTF-8"],
    ["utf-8-sig", "UTF-8（含 BOM）"],
    ["gb18030", "GB18030 / GBK"],
    ["big5", "Big5"],
    ["latin-1", "Latin-1"],
  ];

  const DELIMITERS = [
    [",", "逗号 ,"],
    [";", "分号 ;"],
    ["\t", "制表符 Tab"],
    ["|", "竖线 |"],
  ];

  function escapeHtml(value) {
    return DV.escapeHtml(value);
  }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) return "—";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showError(message) {
    uploadError.className = "alert alert-error";
    uploadError.textContent = message;
    uploadError.hidden = false;
  }

  function clearError() {
    uploadError.hidden = true;
    uploadError.textContent = "";
  }

  function setLoading(loading) {
    dropzone.classList.toggle("is-loading", loading);
    const title = dropzone.querySelector(".drop-title");
    if (!title) return;
    if (loading) {
      if (!title.dataset.original) title.dataset.original = title.innerHTML;
      title.textContent = "正在读取文件…";
    } else if (title.dataset.original) {
      title.innerHTML = title.dataset.original;
    }
  }

  function selectedOptions() {
    const sheet = document.getElementById("sheetSelect");
    const encoding = document.getElementById("encodingSelect");
    const delimiter = document.getElementById("delimiterSelect");
    const headerRow = document.getElementById("headerRow");
    const hasHeader = document.getElementById("hasHeader");
    const nameInput = document.getElementById("datasetName");
    return {
      sheet: sheet ? sheet.value : null,
      encoding: encoding ? encoding.value : "auto",
      delimiter: delimiter ? delimiter.value : "auto",
      header_row: headerRow ? Number(headerRow.value) || 1 : 1,
      has_header: hasHeader ? hasHeader.checked : true,
      name: nameInput ? nameInput.value.trim() : "",
    };
  }

  function renderTable(columns, rows) {
    if (!columns || !columns.length) {
      previewTable.innerHTML = '<tbody><tr><td class="table-loading">没有可预览的数据。</td></tr></tbody>';
      return;
    }
    const head =
      "<thead><tr>" +
      columns
        .map(function (column) {
          return (
            "<th><span>" +
            escapeHtml(column.name) +
            '</span> <span class="type-badge">' +
            escapeHtml(column.type) +
            "</span></th>"
          );
        })
        .join("") +
      "</tr></thead>";
    let body = "";
    if (!rows || !rows.length) {
      body = '<tr><td class="table-loading" colspan="' + columns.length + '">没有数据。</td></tr>';
    } else {
      body = rows
        .map(function (row) {
          return (
            "<tr>" +
            columns
              .map(function (column) {
                const value = row[column.name];
                if (value === null || value === undefined) {
                  return '<td><span class="null-cell" title="缺失值">空</span></td>';
                }
                return "<td title=\"" + escapeHtml(value) + "\">" + escapeHtml(value) + "</td>";
              })
              .join("") +
            "</tr>"
          );
        })
        .join("");
    }
    previewTable.innerHTML = head + "<tbody>" + body + "</tbody>";
  }

  function renderFileSummary(info) {
    const items = [
      ["文件名", info.file_name],
      ["大小", formatSize(info.size)],
      ["类型", info.kind === "xlsx" ? "Excel 工作簿" : "CSV 文本"],
    ];
    if (info.kind === "xlsx") {
      items.push(["工作表", (info.sheets || []).join(" / ")]);
      items.push(["检测来源", info.encoding_source || "—"]);
    } else {
      items.push(["识别编码", info.encoding || "—"]);
      items.push(["检测来源", info.encoding_source || "—"]);
      items.push(["分隔符", info.delimiter === "\t" ? "Tab" : info.delimiter || "—"]);
    }
    fileSummary.innerHTML = items
      .map(function (item) {
        return (
          '<div class="file-summary-item"><span>' +
          escapeHtml(item[0]) +
          "</span><strong title=\"" +
          escapeHtml(item[1]) +
          '">' +
          escapeHtml(item[1]) +
          "</strong></div>"
        );
      })
      .join("");
  }

  function renderOptions(info) {
    const name = info.file_name.replace(/\.[^.]+$/, "");
    let html = '<div class="options-grid">';
    html +=
      '<div class="field field-wide"><label for="datasetName">数据集名称</label>' +
      '<input type="text" id="datasetName" maxlength="60" value="' +
      escapeHtml(name) +
      '"></div>';

    if (info.kind === "xlsx") {
      html +=
        '<div class="field"><label for="sheetSelect">工作表</label><select id="sheetSelect">' +
        (info.sheets || [])
          .map(function (sheet) {
            return (
              '<option value="' +
              escapeHtml(sheet) +
              '"' +
              (sheet === info.sheet ? " selected" : "") +
              ">" +
              escapeHtml(sheet) +
              "</option>"
            );
          })
          .join("") +
        "</select></div>";
    } else {
      const detected = info.encoding || "utf-8";
      const hasDetected = ENCODINGS.some(function (item) {
        return item[0] === detected;
      });
      let encodingOptions = ENCODINGS.map(function (item) {
        return (
          '<option value="' +
          item[0] +
          '"' +
          (item[0] === detected ? " selected" : "") +
          ">" +
          item[1] +
          (item[0] === detected ? "（已识别）" : "") +
          "</option>"
        );
      }).join("");
      if (!hasDetected) {
        encodingOptions +=
          '<option value="' +
          escapeHtml(detected) +
          '" selected>' +
          escapeHtml(detected) +
          "（已识别）</option>";
      }
      html +=
        '<div class="field"><label for="encodingSelect">文件编码</label><select id="encodingSelect">' +
        encodingOptions +
        "</select></div>";
      html +=
        '<div class="field"><label for="delimiterSelect">分隔符</label><select id="delimiterSelect">' +
        DELIMITERS.map(function (item) {
          return (
            '<option value="' +
            item[0] +
            '"' +
            (item[0] === info.delimiter ? " selected" : "") +
            ">" +
            item[1] +
            "</option>"
          );
        }).join("") +
        "</select></div>";
    }

    html +=
      '<div class="field"><label for="headerRow">表头所在行</label>' +
      '<input type="number" id="headerRow" min="1" max="50" step="1" value="1"></div>';
    html +=
      '<div class="field"><span class="field-label">首行处理</span>' +
      '<label class="radio-item"><input type="checkbox" id="hasHeader" checked> 首行作为字段名</label></div>';
    html += "</div>";
    html += '<p class="form-hint">修改工作表、编码、分隔符或表头行后，下方预览会自动刷新。</p>';

    importOptions.innerHTML = html;

    const hasHeader = document.getElementById("hasHeader");
    const headerRow = document.getElementById("headerRow");
    hasHeader.addEventListener("change", function () {
      headerRow.disabled = !hasHeader.checked;
      schedulePreview();
    });
    ["sheetSelect", "encodingSelect", "delimiterSelect", "headerRow"].forEach(function (id) {
      const element = document.getElementById(id);
      if (element) element.addEventListener("change", schedulePreview);
    });
  }

  function schedulePreview() {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(refreshPreview, 220);
  }

  async function refreshPreview() {
    if (!current) return;
    clearError();
    const options = selectedOptions();
    previewHint.textContent = "正在刷新预览…";
    try {
      const data = await DV.api("/api/files/preview", {
        method: "POST",
        body: Object.assign({ token: current.token }, options),
      });
      renderTable(data.columns, data.preview);
      previewHint.textContent =
        "预览前 " + (data.preview ? data.preview.length : 0) + " 行，字段类型为自动推断结果";
    } catch (error) {
      previewHint.textContent = "";
      showError(error.message);
    }
  }

  function showInspect(info) {
    current = info;
    dropzone.hidden = true;
    inspectPanel.hidden = false;
    importStatus.textContent = "";
    renderFileSummary(info);
    renderOptions(info);
    renderTable(info.columns, info.preview);
    previewHint.textContent =
      "预览前 " + (info.preview ? info.preview.length : 0) + " 行，字段类型为自动推断结果";
    if (info.warnings && info.warnings.length) {
      uploadError.innerHTML = info.warnings.map(escapeHtml).join("<br>");
      uploadError.className = "alert alert-info";
      uploadError.hidden = false;
    } else {
      uploadError.hidden = true;
    }
  }

  function resetInspect() {
    current = null;
    inspectPanel.hidden = true;
    dropzone.hidden = false;
    uploadError.hidden = true;
    uploadError.className = "alert alert-error";
    fileInput.value = "";
    setLoading(false);
  }

  async function uploadFile(file) {
    if (!file) return;
    clearError();
    const name = file.name || "";
    const lower = name.toLowerCase();
    if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx")) {
      showError("仅支持 .csv 与 .xlsx 文件。");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      showError("文件超过 50 MB 限制。");
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const data = await DV.api("/api/files/inspect", { method: "POST", body: formData });
      showInspect(data.file);
    } catch (error) {
      showError(error.message);
    } finally {
      setLoading(false);
    }
  }

  dropzone.addEventListener("click", function () {
    fileInput.click();
  });

  dropzone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach(function (name) {
    dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      dropzone.classList.add("is-dragover");
    });
  });

  ["dragleave", "dragend"].forEach(function (name) {
    dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      dropzone.classList.remove("is-dragover");
    });
  });

  dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    if (event.dataTransfer && event.dataTransfer.files.length) {
      uploadFile(event.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files.length) {
      uploadFile(fileInput.files[0]);
    }
  });

  cancelBtn.addEventListener("click", resetInspect);

  importBtn.addEventListener("click", async function () {
    if (!current) return;
    clearError();
    const options = selectedOptions();
    if (!options.name) {
      showError("请填写数据集名称。");
      return;
    }
    DV.setBusy(importBtn, true, "正在导入…");
    importStatus.textContent = "正在读取完整数据，请稍候…";
    try {
      const data = await DV.api("/api/files/import", {
        method: "POST",
        body: Object.assign(
          {
            token: current.token,
            file_name: current.file_name,
          },
          options
        ),
      });
      DV.flash(data.message || "导入成功。", "success");
      window.location.href = data.redirect;
    } catch (error) {
      showError(error.message);
      importStatus.textContent = "";
      DV.setBusy(importBtn, false);
    }
  });

  document.querySelectorAll(".js-delete-dataset").forEach(function (button) {
    button.addEventListener("click", async function () {
      const id = button.dataset.id;
      const name = button.dataset.name || "该数据集";
      if (!window.confirm("确定删除数据集「" + name + "」？数据文件与版本记录都会删除，历史日志保留。")) {
        return;
      }
      try {
        const data = await DV.api("/api/datasets/" + encodeURIComponent(id), { method: "DELETE" });
        DV.flash(data.message || "数据集已删除。", "success");
        window.location.reload();
      } catch (error) {
        DV.toast(error.message, "error");
      }
    });
  });
})();
