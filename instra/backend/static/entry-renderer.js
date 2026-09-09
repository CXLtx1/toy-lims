/* Pure data-entry markup, shared by the editable app and standalone readonly views. */
(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  function templateJson(value, fallback) {
    try {
      const parsed = typeof value === "string" ? JSON.parse(value) : value;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : fallback;
    } catch (_) { return fallback; }
  }

  function readingHasStoredValue(reading) {
    if (!reading) return false;
    if (reading.raw !== null && reading.raw !== undefined && reading.raw !== "") return true;
    let extra = reading.extra;
    if (typeof extra === "string") {
      try { extra = JSON.parse(extra || "{}"); } catch (_) { extra = {}; }
    }
    return Boolean(extra && typeof extra === "object" && Object.keys(extra).length);
  }

  function methodFormulaVariables(formula) {
    const found = String(formula || "").match(/\b[A-Za-z_][A-Za-z0-9_]*\b/g) || [];
    return [...new Set(found)];
  }

  function titrationInputs(sa, options = {}) {
    const constants = templateJson(sa.method_constants, {});
    const variables = methodFormulaVariables(sa.formula);
    const fixedValues = { ...constants };
    if (variables.includes("m") && sa.prep_mass != null) fixedValues.m = sa.prep_mass;
    if (variables.includes("v") && sa.prep_vol != null) fixedValues.v = sa.prep_vol;
    const fixed = Object.entries(fixedValues).map(([key, value]) => `${key}=${value}`).join(" ");
    return `<span class="method-label">${esc(sa.method_name || "未设置公式方法")}</span>
    ${fixed ? `<span class="hint">${esc(fixed)}</span>` : ""}
    ${sa.method_id && !options.readOnly ? `<button class="method-detail" type="button" data-method-id="${esc(sa.method_id)}">详情</button>` : ""}`;
  }

  // A null rd is an unsaved reading; a single reading needs no participation checkbox.
  function readingLineHtml(sa, rd, multiple, hasFinal = false, options = {}) {
    const disabled = options.readOnly ? " disabled" : "";
    const unitMap = { xrf: "%", ppm: "ppm", ppb: "ppb", mol: "mol/L", percent: "%", ph: "pH" };
    const rawUnit = unitMap[sa.itype] || "";
    const rdExtra = templateJson(rd?.extra, {});
    let valueCell;
    if (sa.itype === "function") {
      const constants = templateJson(sa.method_constants, {});
      let inputs = "";
      if (sa.formula) {
        for (const variable of methodFormulaVariables(sa.formula)) {
          const supplied = Object.hasOwn(constants, variable) ||
            (variable === "m" && sa.prep_mass != null) || (variable === "v" && sa.prep_vol != null);
          if (!supplied) {
            inputs += `${esc(variable)}=<input type="number" step="any" class="rd-var" data-var="${esc(variable)}" value="${esc(rdExtra[variable] ?? "")}"${disabled}>`;
          }
        }
      }
      valueCell = `<span class="tit-inputs">${inputs}</span>`;
    } else {
      valueCell = `<span class="input-unit"><input type="number" step="any" class="rd-raw" data-field="raw" value="${esc(rd?.raw ?? "")}"${disabled}> <span>${esc(rawUnit)}</span></span>`;
    }
    const included = hasFinal ? !!rd?.is_final : rd?.use_avg !== false;
    const toggles = multiple
      ? `<label class="inline rd-use-label" title="勾选后参与结果计算"><input type="checkbox" class="rd-use" ${included ? "checked" : ""}${disabled}>参与</label>`
      : "";
    return `<div class="reading ${readingHasStoredValue(rd) ? "has-value" : ""}" data-rid="${esc(rd?.id ?? "")}">
    ${valueCell}${toggles}
    ${rd && multiple && !options.readOnly ? '<button class="del rd-del" type="button" title="删除这遍">删</button>' : ""}
  </div>`;
  }

  function entryRowHtml(sa, analyteCount = 1, options = {}) {
    const disabled = options.readOnly ? " disabled" : "";
    const aux = templateJson(sa.aux, {});
    const rdCount = (sa.readings && sa.readings.length) || 0;
    const hasFinal = !!sa.readings?.some((rd) => rd.is_final);
    const readingsHtml = rdCount
      ? sa.readings.map((rd) => readingLineHtml(sa, rd, rdCount > 1, hasFinal, options)).join("")
      : readingLineHtml(sa, null, false, false, options);
    const addButton = options.readOnly ? "" : '<button class="rd-add" type="button">+ 再测一遍</button>';
    let cell;
    if (!sa.itype) cell = '<i style="color:#999">先选仪器</i>';
    else if (sa.itype === "function") cell = `${titrationInputs(sa, options)}
    <div class="readings">${readingsHtml}</div>
    ${addButton}`;
    else cell = `<div class="readings">${readingsHtml}</div>
    ${addButton}`;
    let coeffText = "";
    if (aux.use) {
      if (aux.expected && aux.measured) coeffText = "×" + (aux.expected / aux.measured).toFixed(4);
      else if (aux.coefficient) coeffText = "×" + aux.coefficient;
    }
    const hasStoredValue = sa.readings?.some(readingHasStoredValue) || readingHasStoredValue(sa);
    return `<tr class="${sa.status === "completed" || hasStoredValue ? "task-completed" : ""}" data-said="${esc(sa.id)}" data-itype="${esc(sa.itype || "")}" data-analyte="${esc(sa.analyte)}" data-prep="${esc(sa.prep_name || '原样')}">
    <td class="grid-cell readonly">${esc(sa.analyte)}</td>
    <td class="grid-cell readonly">${esc(sa.prep_name || "原样")}</td>
    <td class="grid-cell readonly">${sa.instrument ? esc(sa.instrument) : '<i class="bad-text">未分配（请到来样页设置）</i>'}${sa.method_name ? `<small>${esc(sa.method_name)}</small>` : ""}</td>
    <td class="grid-cell">${cell}</td>
    <td class="grid-cell"><span class="aux-box">标称<input type="number" step="any" class="aux-std" value="${esc(aux.expected ?? "")}" style="width:55px"${disabled}>
      回读<input type="number" step="any" class="aux-read" value="${esc(aux.measured ?? "")}" style="width:55px"${disabled}>
      <label class="inline" title="带标计算"><input type="checkbox" class="aux-use" ${aux.use ? "checked" : ""}${disabled}>带标</label>
      <span class="aux-show">${esc(coeffText)}</span></span></td>
    <td class="grid-cell readonly st"></td></tr>`;
  }

  globalThis.LabflowEntryRenderer = {
    readingHasStoredValue, methodFormulaVariables, titrationInputs, readingLineHtml, entryRowHtml,
  };
})();
