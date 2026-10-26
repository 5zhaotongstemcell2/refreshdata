(function () {
  "use strict";

  const summaryElement = document.getElementById("dataset-summary");
  if (!summaryElement) return;

  const DS = JSON.parse(summaryElement.textContent);
  const datasetId = DS.id;
  const datasetUrl = "/api/datasets/" + encodeURIComponent(datasetId);
  const columns = DS.columns || [];
  const columnsByName = {};
  columns.forEach(function (column) {
    columnsByName[column.name] = column;
  });

  const chartTypeLabels = DS.chart_labels || {};
  const aggLabels = DS.agg_labels || {};
  const filterLabels = DS.filter_labels || {};
  const operatorMap = DS.operator_map || {};

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return DV.escapeHtml(value);
  }

  function optionsHtml(items, selected, emptyLabel) {
    let html = "";
    if (emptyLabel !== undefined) {
      html += '<option value="">' + escapeHtml(emptyLabel) + "</option>";
    }
    items.forEach(function (item) {
      const value = Array.isArray(item) ? item[0] : item;
      const label = Array.isArray(item) ? item[1] : item;
      const isSelected = Array.isArray(selected)
        ? selected.indexOf(value) !== -1
        : value === selected;
      html +=
        '<option value="' +
        escapeHtml(value) +
        '"' +
        (isSelected ? " selected" : "") +
        ">" +
        escapeHtml(label) +
        "</option>";
    });
    return html;
  }

  function values(select) {
    if (!select) return [];
    return Array.prototype.slice.call(select.selectedOptions).map(function (option) {
      return option.value;
    });
  }

  // ---------------------------------------------------------------------
  // 标签页
  // ---------------------------------------------------------------------

  const tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  const panels = {
    preview: $("tab-preview"),
    clean: $("tab-clean"),
    filter: $("tab-filter"),
    chart: $("tab-chart"),
  };
  let currentTab = "preview";

  function activateTab(name, updateHash) {
    if (!panels[name]) name = "preview";
    currentTab = name;
    tabButtons.forEach(function (button) {
      const active = button.dataset.tab === name;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    Object.keys(panels).forEach(function (key) {
      if (panels[key]) panels[key].hidden = key !== name;
    });
    try {
      sessionStorage.setItem("dv-workspace-tab", name);
    } catch (error) {
      /* ignore */
    }
    if (updateHash !== false) {
      history.replaceState(null, "", "#" + name);
    }
    if (name === "chart") {
      maybeAutoChart();
      window.setTimeout(function () {
        if (chart) chart.resize();
      }, 60);
    }
  }

  tabButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      activateTab(button.dataset.tab, true);
    });
  });

  window.addEventListener("hashchange", function () {
    activateTab(window.location.hash.replace("#", ""), false);
  });

  // ---------------------------------------------------------------------
  // 数据预览分页
  // ---------------------------------------------------------------------

  const dataTable = $("dataTable");
  const pageSizeSelect = $("pageSize");
  const prevPageButton = $("prevPage");
  const nextPageButton = $("nextPage");
  const pageInfo = $("pageInfo");
  const rowRange = $("rowRange");

  let page = 1;
  let pageSize = Number(pageSizeSelect.value) || 20;
  let pages = 1;
  let totalRows = 0;
  let loadingRows = false;

  function cellHtml(value, column) {
    if (value === null || value === undefined) {
      return '<td class="num-null"><span class="null-cell" title="缺失值">空</span></td>';
    }
    let display = value;
    if (column && column.numeric && typeof value === "number") {
      display = DV.number(value, 4);
    }
    return (
      '<td class="' +
      (column && column.numeric ? "num-col" : "") +
      '" title="' +
      escapeHtml(value) +
      '">' +
      escapeHtml(display) +
      "</td>"
    );
  }

  function renderRows(data) {
    const tableColumns = data.columns || [];
    let head = "<thead><tr>";
    tableColumns.forEach(function (column) {
      head +=
        "<th class=\"" +
        (column.numeric ? "num-col" : "") +
        "\"><span>" +
        escapeHtml(column.name) +
        '</span> <span class="type-badge">' +
        escapeHtml(column.type) +
        "</span></th>";
    });
    head += "</tr></thead>";

    let body = "";
    if (!data.rows || !data.rows.length) {
      body =
        '<tr><td class="table-loading" colspan="' +
        Math.max(1, tableColumns.length) +
        '">当前条件下没有数据。</td></tr>';
    } else {
      body = data.rows
        .map(function (row) {
          let line = "<tr>";
          tableColumns.forEach(function (column) {
            line += cellHtml(row[column.name], column);
          });
          line += "</tr>";
          return line;
        })
        .join("");
    }
    dataTable.innerHTML = head + "<tbody>" + body + "</tbody>";
  }

  async function loadRows(targetPage) {
    if (loadingRows) return;
    loadingRows = true;
    page = Math.max(1, targetPage || 1);
    dataTable.innerHTML =
      '<tbody><tr><td class="table-loading">正在加载数据…</td></tr></tbody>';
    try {
      const data = await DV.api(
        datasetUrl +
          "/rows?page=" +
          page +
          "&page_size=" +
          pageSize
      );
      totalRows = data.total;
      pages = data.pages;
      page = data.page;
      renderRows(data);
      if (data.total) {
        rowRange.textContent =
          "第 " + data.start + "–" + data.end + " 行，共 " + data.total + " 行";
      } else {
        rowRange.textContent = "当前条件下共 0 行";
      }
      pageInfo.textContent = page + " / " + pages;
      prevPageButton.disabled = page <= 1;
      nextPageButton.disabled = page >= pages;
    } catch (error) {
      dataTable.innerHTML =
        '<tbody><tr><td class="table-loading">加载失败：' +
        escapeHtml(error.message) +
        "</td></tr></tbody>";
      DV.toast(error.message, "error");
    } finally {
      loadingRows = false;
    }
  }

  if (pageSizeSelect) {
    pageSizeSelect.addEventListener("change", function () {
      pageSize = Number(pageSizeSelect.value) || 20;
      loadRows(1);
    });
  }
  if (prevPageButton) {
    prevPageButton.addEventListener("click", function () {
      if (page > 1) loadRows(page - 1);
    });
  }
  if (nextPageButton) {
    nextPageButton.addEventListener("click", function () {
      if (page < pages) loadRows(page + 1);
    });
  }

  // ---------------------------------------------------------------------
  // 数据清洗
  // ---------------------------------------------------------------------

  const fillMethod = $("fillMethod");
  const fillValueWrap = $("fillValueWrap");
  const convertTarget = $("convertTarget");
  const convertFormatWrap = $("convertFormatWrap");

  function toggleFillValue() {
    if (!fillMethod || !fillValueWrap) return;
    fillValueWrap.hidden = fillMethod.value !== "custom";
  }

  function toggleConvertFormat() {
    if (!convertTarget || !convertFormatWrap) return;
    convertFormatWrap.hidden = convertTarget.value !== "datetime";
  }

  if (fillMethod) fillMethod.addEventListener("change", toggleFillValue);
  if (convertTarget) convertTarget.addEventListener("change", toggleConvertFormat);
  toggleFillValue();
  toggleConvertFormat();

  const dropSelectAll = $("dropSelectAll");
  const dropSelectNone = $("dropSelectNone");
  if (dropSelectAll) {
    dropSelectAll.addEventListener("click", function () {
      document.querySelectorAll('input[name="dropColumn"]').forEach(function (checkbox) {
        checkbox.checked = true;
      });
    });
  }
  if (dropSelectNone) {
    dropSelectNone.addEventListener("click", function () {
      document.querySelectorAll('input[name="dropColumn"]').forEach(function (checkbox) {
        checkbox.checked = false;
      });
    });
  }

  document.querySelectorAll(".js-clean-form").forEach(function (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const action = form.dataset.action;
      const params = {};

      if (action === "dedup") {
        params.subset = values($("dedupSubset"));
      } else if (action === "fillna") {
        params.columns = values($("fillColumns"));
        params.method = fillMethod ? fillMethod.value : "zero";
        if (params.method === "custom") {
          params.value = ($("fillValue") || {}).value || "";
          if (!params.value.trim()) {
            DV.toast("请填写自定义填充值。", "error");
            return;
          }
        }
      } else if (action === "drop_columns") {
        params.columns = Array.prototype.slice
          .call(document.querySelectorAll('input[name="dropColumn"]:checked'))
          .map(function (checkbox) {
            return checkbox.value;
          });
        if (!params.columns.length) {
          DV.toast("请至少选择一个要删除的字段。", "error");
          return;
        }
        if (
          !window.confirm(
            "确定删除字段：" + params.columns.join("、") + "？此操作会生成新版本。"
          )
        ) {
          return;
        }
      } else if (action === "convert") {
        params.column = ($("convertColumn") || {}).value || "";
        params.target = convertTarget ? convertTarget.value : "int";
        params.on_error = ($("convertError") || {}).value || "coerce";
        if (params.target === "datetime") {
          params.format = ($("convertFormat") || {}).value || "";
        }
      }

      const submit = form.querySelector('button[type="submit"]');
      DV.setBusy(submit, true, "处理中…");
      try {
        const data = await DV.api(datasetUrl + "/clean", {
          method: "POST",
          body: { action: action, params: params },
        });
        if (data.changed) {
          DV.flash(data.message || "操作完成。", "success");
          // 当前 hash 与目标地址相同，直接赋值不会触发重载
          window.location.reload();
        } else {
          DV.toast(data.message || "没有需要修改的数据。", "info");
          DV.setBusy(submit, false);
        }
      } catch (error) {
        DV.toast(error.message, "error");
        DV.setBusy(submit, false);
      }
    });
  });

  const undoBtn = $("undoBtn");
  if (undoBtn) {
    undoBtn.addEventListener("click", async function () {
      if (!window.confirm("撤销到上一个数据版本？")) return;
      DV.setBusy(undoBtn, true, "撤销中…");
      try {
        const data = await DV.api(datasetUrl + "/undo", { method: "POST" });
        DV.flash(data.message || "已撤销。", "success");
        window.location.reload();
      } catch (error) {
        DV.toast(error.message, "error");
        DV.setBusy(undoBtn, false);
      }
    });
  }

  const resetBtn = $("resetBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", async function () {
      if (
        !window.confirm(
          "恢复原始数据会丢弃全部清洗版本，并清空筛选、排序和图表配置。确定继续？"
        )
      ) {
        return;
      }
      DV.setBusy(resetBtn, true, "恢复中…");
      try {
        const data = await DV.api(datasetUrl + "/reset", { method: "POST" });
        DV.flash(data.message || "已恢复原始数据。", "success");
        window.location.reload();
      } catch (error) {
        DV.toast(error.message, "error");
        DV.setBusy(resetBtn, false);
      }
    });
  }

  // ---------------------------------------------------------------------
  // 筛选与排序
  // ---------------------------------------------------------------------

  const filterList = $("filterList");
  const sortList = $("sortList");
  const addFilterBtn = $("addFilterBtn");
  const addSortBtn = $("addSortBtn");
  const applyViewBtn = $("applyViewBtn");
  const clearViewBtn = $("clearViewBtn");

  const filterState = (DS.filters || []).map(function (item) {
    return {
      column: item.column,
      op: item.op,
      value: item.value === null || item.value === undefined ? "" : String(item.value),
      value2: item.value2 === null || item.value2 === undefined ? "" : String(item.value2),
    };
  });
  const sortState = (DS.sorts || []).map(function (item) {
    return { column: item.column, order: item.order || "asc" };
  });

  function columnOperators(column) {
    if (!column) return ["contains"];
    if (column.operators && column.operators.length) return column.operators;
    return operatorMap[column.kind] || ["contains"];
  }

  function valuePlaceholder(column) {
    if (!column) return "";
    if (column.kind === "number") return "数值";
    if (column.kind === "datetime") return "YYYY-MM-DD";
    return "关键字";
  }

  function renderFilters() {
    if (!filterList) return;
    if (!filterState.length) {
      filterList.innerHTML =
        '<div class="empty-inline">还没有筛选条件，点击下方按钮添加。</div>';
      return;
    }
    filterList.innerHTML = filterState
      .map(function (item, index) {
        if (!columnsByName[item.column] && columns.length) {
          item.column = columns[0].name;
        }
        const column = columnsByName[item.column] || columns[0];
        if (!column) return "";
        const operators = columnOperators(column);
        if (operators.indexOf(item.op) === -1) {
          item.op = operators[0];
        }
        const operatorOptions = operators
          .map(function (operator) {
            return (
              '<option value="' +
              escapeHtml(operator) +
              '"' +
              (operator === item.op ? " selected" : "") +
              ">" +
              escapeHtml(filterLabels[operator] || operator) +
              "</option>"
            );
          })
          .join("");
        const columnOptions = columns
          .map(function (col) {
            return (
              '<option value="' +
              escapeHtml(col.name) +
              '"' +
              (col.name === item.column ? " selected" : "") +
              ">" +
              escapeHtml(col.name) +
              "</option>"
            );
          })
          .join("");

        let valuesHtml = "";
        if (item.op === "is_null" || item.op === "not_null") {
          valuesHtml = '<span class="hint">无需填写值</span>';
        } else if (item.op === "between") {
          valuesHtml =
            '<input type="text" class="cond-value" value="' +
            escapeHtml(item.value) +
            '" placeholder="' +
            escapeHtml(valuePlaceholder(column)) +
            '"><span class="range-sep">至</span>' +
            '<input type="text" class="cond-value2" value="' +
            escapeHtml(item.value2) +
            '" placeholder="' +
            escapeHtml(valuePlaceholder(column)) +
            '">';
        } else {
          valuesHtml =
            '<input type="text" class="cond-value" value="' +
            escapeHtml(item.value) +
            '" placeholder="' +
            escapeHtml(valuePlaceholder(column)) +
            '">';
        }

        return (
          '<div class="condition-row" data-index="' +
          index +
          '">' +
          '<select class="cond-column" aria-label="筛选字段">' +
          columnOptions +
          "</select>" +
          '<select class="cond-op" aria-label="筛选方式">' +
          operatorOptions +
          "</select>" +
          '<div class="condition-values">' +
          valuesHtml +
          "</div>" +
          '<button type="button" class="icon-btn remove-condition" aria-label="删除条件">×</button>' +
          "</div>"
        );
      })
      .join("");
  }

  if (filterList) {
    filterList.addEventListener("change", function (event) {
      const row = event.target.closest(".condition-row");
      if (!row) return;
      const index = Number(row.dataset.index);
      const item = filterState[index];
      if (!item) return;
      if (event.target.classList.contains("cond-column")) {
        item.column = event.target.value;
        const column = columnsByName[item.column];
        const operators = columnOperators(column);
        item.op = operators[0];
        item.value = "";
        item.value2 = "";
        renderFilters();
      } else if (event.target.classList.contains("cond-op")) {
        item.op = event.target.value;
        if (item.op !== "between") item.value2 = "";
        renderFilters();
      }
    });

    filterList.addEventListener("input", function (event) {
      const row = event.target.closest(".condition-row");
      if (!row) return;
      const index = Number(row.dataset.index);
      const item = filterState[index];
      if (!item) return;
      if (event.target.classList.contains("cond-value")) {
        item.value = event.target.value;
      } else if (event.target.classList.contains("cond-value2")) {
        item.value2 = event.target.value;
      }
    });

    filterList.addEventListener("click", function (event) {
      if (!event.target.closest(".remove-condition")) return;
      const row = event.target.closest(".condition-row");
      if (!row) return;
      filterState.splice(Number(row.dataset.index), 1);
      renderFilters();
    });
  }

  if (addFilterBtn) {
    addFilterBtn.addEventListener("click", function () {
      if (!columns.length) return;
      const column = columns[0];
      const operators = columnOperators(column);
      filterState.push({ column: column.name, op: operators[0], value: "", value2: "" });
      renderFilters();
    });
  }

  function renderSorts() {
    if (!sortList) return;
    if (!sortState.length) {
      sortList.innerHTML =
        '<div class="empty-inline">没有排序字段，将保持数据原始顺序。</div>';
      return;
    }
    sortList.innerHTML = sortState
      .map(function (item, index) {
        const columnOptions = columns
          .map(function (column) {
            return (
              '<option value="' +
              escapeHtml(column.name) +
              '"' +
              (column.name === item.column ? " selected" : "") +
              ">" +
              escapeHtml(column.name) +
              "</option>"
            );
          })
          .join("");
        return (
          '<div class="sort-row" data-index="' +
          index +
          '">' +
          '<select class="sort-column" aria-label="排序字段">' +
          columnOptions +
          "</select>" +
          '<select class="sort-order" aria-label="排序方向">' +
          '<option value="asc"' +
          (item.order === "asc" ? " selected" : "") +
          ">升序</option>" +
          '<option value="desc"' +
          (item.order === "desc" ? " selected" : "") +
          ">降序</option>" +
          "</select>" +
          '<button type="button" class="icon-btn remove-sort" aria-label="删除排序">×</button>' +
          "</div>"
        );
      })
      .join("");
  }

  if (sortList) {
    sortList.addEventListener("change", function (event) {
      const row = event.target.closest(".sort-row");
      if (!row) return;
      const item = sortState[Number(row.dataset.index)];
      if (!item) return;
      if (event.target.classList.contains("sort-column")) {
        item.column = event.target.value;
      } else if (event.target.classList.contains("sort-order")) {
        item.order = event.target.value;
      }
    });

    sortList.addEventListener("click", function (event) {
      if (!event.target.closest(".remove-sort")) return;
      const row = event.target.closest(".sort-row");
      if (!row) return;
      sortState.splice(Number(row.dataset.index), 1);
      renderSorts();
    });
  }

  if (addSortBtn) {
    addSortBtn.addEventListener("click", function () {
      if (sortState.length >= 5) {
        DV.toast("最多添加 5 个排序字段。", "warn");
        return;
      }
      const used = sortState.map(function (item) {
        return item.column;
      });
      const available = columns.filter(function (column) {
        return used.indexOf(column.name) === -1;
      });
      if (!available.length) {
        DV.toast("没有更多可排序字段。", "warn");
        return;
      }
      sortState.push({ column: available[0].name, order: "asc" });
      renderSorts();
    });
  }

  function currentLogic() {
    const checked = document.querySelector('input[name="filterLogic"]:checked');
    return checked ? checked.value : "AND";
  }

  function setLogic(value) {
    document.querySelectorAll('input[name="filterLogic"]').forEach(function (input) {
      input.checked = input.value === value;
    });
  }

  if (applyViewBtn) {
    applyViewBtn.addEventListener("click", async function () {
      const outgoing = [];
      for (let index = 0; index < filterState.length; index += 1) {
        const item = filterState[index];
        if (!item.column) continue;
        const needsValue = item.op !== "is_null" && item.op !== "not_null";
        if (needsValue && String(item.value).trim() === "") {
          DV.toast("请填写「" + item.column + "」的筛选值。", "error");
          return;
        }
        if (item.op === "between" && String(item.value2).trim() === "") {
          DV.toast("请填写「" + item.column + "」的结束值。", "error");
          return;
        }
        outgoing.push({
          column: item.column,
          op: item.op,
          value: needsValue ? String(item.value).trim() : null,
          value2: item.op === "between" ? String(item.value2).trim() : null,
        });
      }

      const outgoingSorts = sortState
        .filter(function (item) {
          return item.column;
        })
        .map(function (item) {
          return { column: item.column, order: item.order };
        });

      DV.setBusy(applyViewBtn, true, "应用中…");
      try {
        const data = await DV.api(datasetUrl + "/filters", {
          method: "POST",
          body: { filters: outgoing, logic: currentLogic(), sorts: outgoingSorts },
        });
        if (data.changed) {
          DV.flash(data.message || "筛选与排序已应用。", "success");
          window.location.reload();
        } else {
          DV.toast(data.message || "筛选与排序没有变化。", "info");
          DV.setBusy(applyViewBtn, false);
        }
      } catch (error) {
        DV.toast(error.message, "error");
        DV.setBusy(applyViewBtn, false);
      }
    });
  }

  if (clearViewBtn) {
    clearViewBtn.addEventListener("click", async function () {
      DV.setBusy(clearViewBtn, true, "清空中…");
      try {
        const data = await DV.api(datasetUrl + "/filters", {
          method: "POST",
          body: { filters: [], logic: "AND", sorts: [] },
        });
        DV.flash(data.message || "已清空筛选与排序。", "success");
        window.location.reload();
      } catch (error) {
        DV.toast(error.message, "error");
        DV.setBusy(clearViewBtn, false);
      }
    });
  }

  // ---------------------------------------------------------------------
  // 图表
  // ---------------------------------------------------------------------

  const chartBox = $("chartBox");
  const chartEmpty = $("chartEmpty");
  const chartInfo = $("chartInfo");
  const chartWarnings = $("chartWarnings");
  const chartTypeGroup = $("chartTypeGroup");
  const chartX = $("chartX");
  const chartY = $("chartY");
  const chartAgg = $("chartAgg");
  const chartAggField = $("chartAggField");
  const chartSort = $("chartSort");
  const chartTopN = $("chartTopN");
  const generateChartBtn = $("generateChartBtn");
  const exportChartBtn = $("exportChartBtn");
  const browserSaveChartBtn = $("browserSaveChartBtn");

  let chart = null;
  let lastConfig = null;
  let chartGenerated = false;
  let selectedChartType = "bar";

  let previousAgg = chartAgg ? chartAgg.value : "sum";

  function updateChartHint() {
    const hint = $("yHint");
    if (!hint) return;
    if (selectedChartType === "pie") {
      hint.textContent = "饼图使用第一个 Y 轴字段，并按 X 轴汇总分类。";
    } else if (selectedChartType === "scatter") {
      hint.textContent = "散点图需要数值型 X 轴和 Y 轴，使用第一个 Y 字段。";
    } else {
      hint.textContent = "柱状图、折线图可多选 Y 轴字段；饼图、散点图使用第一个字段。";
    }
  }

  function setChartType(type) {
    selectedChartType = type;
    if (chartTypeGroup) {
      chartTypeGroup.querySelectorAll("button").forEach(function (button) {
        button.classList.toggle("active", button.dataset.type === type);
      });
    }
    if (chartY) {
      chartY.multiple = true;
    }
    if (chartAggField) {
      chartAggField.hidden = type === "scatter";
    }
    if (chartAgg) {
      if (type === "scatter") {
        if (chartAgg.value !== "none") previousAgg = chartAgg.value;
        chartAgg.value = "none";
      } else if (chartAgg.value === "none") {
        chartAgg.value = previousAgg || "sum";
      }
    }
    if (type === "scatter" && chartX && chartY) {
      const numeric = columns.filter(function (column) {
        return column.numeric;
      });
      const current = columnsByName[chartX.value];
      if (numeric.length && (!current || !current.numeric)) {
        chartX.value = numeric[0].name;
      }
      const selectedY = values(chartY);
      if (!selectedY.length || selectedY[0] === chartX.value) {
        const alternative = numeric.filter(function (column) {
          return column.name !== chartX.value;
        })[0];
        if (alternative) selectValues(chartY, [alternative.name]);
      }
    }
    updateChartHint();
  }

  function selectValues(select, wanted) {
    if (!select) return;
    const set = wanted || [];
    let matched = 0;
    Array.prototype.forEach.call(select.options, function (option) {
      option.selected = set.indexOf(option.value) !== -1;
      if (option.selected) matched += 1;
    });
    if (!matched && select.options.length) {
      select.options[0].selected = true;
    }
  }

  if (chartTypeGroup) {
    chartTypeGroup.querySelectorAll("button").forEach(function (button) {
      button.addEventListener("click", function () {
        setChartType(button.dataset.type);
      });
    });
  }

  function initialiseChartForm() {
    const saved = DS.chart || null;
    if (saved) {
      setChartType(saved.type || "bar");
      if (chartX && saved.x) chartX.value = saved.x;
      selectValues(chartY, saved.y || []);
      if (chartAgg) chartAgg.value = saved.agg || "sum";
      if (chartSort) chartSort.value = saved.sort || "auto";
      if (chartTopN) chartTopN.value = saved.top_n || 0;
    } else {
      setChartType("bar");
      if (chartY) {
        const firstNumeric = columns.filter(function (column) {
          return column.numeric;
        })[0];
        if (firstNumeric) selectValues(chartY, [firstNumeric.name]);
      }
    }
    const numericColumns = columns.filter(function (column) {
      return column.numeric;
    });
    if (!numericColumns.length) {
      if (generateChartBtn) {
        generateChartBtn.disabled = true;
        generateChartBtn.textContent = "没有数值字段";
      }
      if (chartInfo) chartInfo.textContent = "当前数据没有可用于 Y 轴的数值字段。";
    }
  }

  function chartConfig() {
    const ys = values(chartY);
    return {
      type: selectedChartType,
      x: chartX ? chartX.value : "",
      y: ys,
      agg: chartAgg ? chartAgg.value : "sum",
      top_n: chartTopN ? Number(chartTopN.value) || 0 : 0,
      sort: chartSort ? chartSort.value : "auto",
    };
  }

  function ensureChart() {
    if (chart) return chart;
    if (!chartBox || !window.echarts) return null;
    chart = window.echarts.init(chartBox, null, { renderer: "canvas" });
    window.addEventListener("resize", DV.debounce(function () {
      if (chart) chart.resize();
    }, 150));
    return chart;
  }

  async function generateChart(silent) {
    if (!chartX || !chartY) return;
    if (values(chartY).length === 0) {
      if (!silent) DV.toast("请至少选择一个 Y 轴字段。", "error");
      return;
    }
    const config = chartConfig();
    const originalText = generateChartBtn ? generateChartBtn.textContent : "";
    if (generateChartBtn) DV.setBusy(generateChartBtn, true, "生成中…");
    try {
      const data = await DV.api(datasetUrl + "/chart", { method: "POST", body: config });
      const instance = ensureChart();
      if (!instance) {
        throw new Error("ECharts 未加载，无法渲染图表。");
      }
      instance.setOption(data.option, true);
      chartGenerated = true;
      lastConfig = data.config;
      if (chartEmpty) chartEmpty.classList.add("is-hidden");
      if (exportChartBtn) exportChartBtn.disabled = false;
      if (browserSaveChartBtn) browserSaveChartBtn.disabled = false;
      if (chartInfo) {
        chartInfo.textContent =
          (data.meta.type_label || "") +
          " · " +
          (data.meta.agg_label || "") +
          " · " +
          data.meta.rows_used +
          " 行 · " +
          data.meta.category_count +
          " 个分类";
      }
      if (chartWarnings) {
        if (data.meta.warnings && data.meta.warnings.length) {
          chartWarnings.innerHTML = data.meta.warnings
            .map(function (warning) {
              return escapeHtml(warning);
            })
            .join("<br>");
          chartWarnings.hidden = false;
        } else {
          chartWarnings.hidden = true;
          chartWarnings.textContent = "";
        }
      }
      window.setTimeout(function () {
        instance.resize();
      }, 30);
    } catch (error) {
      DV.toast(error.message, "error");
      if (chartWarnings) {
        chartWarnings.textContent = error.message;
        chartWarnings.hidden = false;
      }
    } finally {
      if (generateChartBtn) {
        DV.setBusy(generateChartBtn, false);
        if (!generateChartBtn.disabled) generateChartBtn.textContent = originalText;
      }
    }
  }

  function maybeAutoChart() {
    if (chartGenerated || !DS.chart) return;
    chartGenerated = true;
    generateChart(true);
  }

  if (generateChartBtn) {
    generateChartBtn.addEventListener("click", function () {
      generateChart(false);
    });
  }

  if (exportChartBtn) {
    exportChartBtn.addEventListener("click", async function () {
      if (!lastConfig) {
        DV.toast("请先生成图表。", "warn");
        return;
      }
      DV.setBusy(exportChartBtn, true, "导出中…");
      try {
        await DV.download(
          datasetUrl + "/chart/export",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(lastConfig),
          },
          "chart.png"
        );
        DV.toast("图表已导出为 PNG。", "success");
      } catch (error) {
        DV.toast(error.message, "error");
      } finally {
        DV.setBusy(exportChartBtn, false);
      }
    });
  }

  if (browserSaveChartBtn) {
    browserSaveChartBtn.addEventListener("click", function () {
      if (!chart) return;
      const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "图表.png";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    });
  }

  // ---------------------------------------------------------------------
  // 初始化
  // ---------------------------------------------------------------------

  initialiseChartForm();
  if (filterList) renderFilters();
  if (sortList) renderSorts();
  setLogic(DS.logic || "AND");
  loadRows(1);

  let initialTab = window.location.hash.replace("#", "");
  if (!panels[initialTab]) {
    try {
      initialTab = sessionStorage.getItem("dv-workspace-tab") || "preview";
    } catch (error) {
      initialTab = "preview";
    }
  }
  activateTab(initialTab, false);
})();
