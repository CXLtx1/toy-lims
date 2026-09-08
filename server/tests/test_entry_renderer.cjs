const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

// No DOM, shell, network or app.js globals are available in this context.
const context = vm.createContext({});
vm.runInContext(readFileSync(path.join(__dirname, "../static/entry-renderer.js"), "utf8"), context);
const { readingHasStoredValue, methodFormulaVariables, titrationInputs, readingLineHtml, entryRowHtml } = context.LabflowEntryRenderer;
const sample = {
  id: 7, analyte: "Cu", prep_name: "P1", instrument: "ICP", itype: "ppm",
  readings: [{ id: 11, raw: 0 }], aux: '{"expected":10,"measured":5,"use":true}',
};
const formulaSample = {
  ...sample, itype: "function", method_id: 3, method_name: "M1",
  formula: "(A1/A2)*m*v + A1 + B", method_constants: '{"A2":10,"B":0}',
  prep_mass: 0, prep_vol: 250, readings: [{ id: 21, extra: '{"A1":0}' }, { id: 22, extra: { A1: 4 } }],
};

test("standalone classic script exposes only the five pure helpers", () => {
  assert.deepEqual(Object.keys(context), ["LabflowEntryRenderer"]);
  assert.deepEqual(Object.keys(context.LabflowEntryRenderer).sort(), [
    "entryRowHtml", "methodFormulaVariables", "readingHasStoredValue", "readingLineHtml", "titrationInputs",
  ]);
  const before = structuredClone(formulaSample);
  entryRowHtml(formulaSample);
  entryRowHtml(formulaSample, 2, { readOnly: true });
  assert.deepEqual(formulaSample, before);
});

test("default numeric markup stays editable with the original classes and layout", () => {
  assert.equal(readingLineHtml(sample, sample.readings[0], false),
    '<div class="reading has-value" data-rid="11">\n' +
    '    <span class="input-unit"><input type="number" step="any" class="rd-raw" data-field="raw" value="0"> <span>ppm</span></span>\n' +
    '    \n  </div>');
  const html = entryRowHtml(sample);
  assert.equal(html, entryRowHtml(sample, 1, {}));
  assert.match(html, /^<tr class="task-completed" data-said="7" data-itype="ppm" data-analyte="Cu" data-prep="P1">/);
  assert.equal((html.match(/<td /g) || []).length, 6);
  assert.match(html, /<td class="grid-cell readonly">ICP<\/td>/);
  assert.match(html, /<div class="readings">/);
  assert.match(html, /<button class="rd-add" type="button">/);
  assert.match(html, /class="aux-std" value="10" style="width:55px">/);
  assert.match(html, /class="aux-read" value="5" style="width:55px">/);
  assert.match(html, /class="aux-use" checked>/);
  assert.match(html, /<span class="aux-show">\u00d72\.0000<\/span>/);
  assert.match(html, /<td class="grid-cell readonly st"><\/td><\/tr>$/);
  assert.doesNotMatch(html, /disabled|rd-use|rd-del/);
  for (const [itype, unit] of Object.entries({ xrf: "%", ppm: "ppm", ppb: "ppb", mol: "mol/L", percent: "%", ph: "pH" })) {
    assert.ok(readingLineHtml({ itype }, null, false).includes(`<span>${unit}</span>`));
  }
  const empty = entryRowHtml({ id: 8, analyte: "Zn", itype: "ppm" });
  assert.match(empty, /^<tr class=""/);
  assert.match(empty, /data-rid=""/);
  assert.match(empty, /data-field="raw" value=""/);
  assert.match(empty, /data-prep="\u539f\u6837"/);
  assert.match(entryRowHtml({ ...sample, itype: "" }), /<i style="color:#999">\u5148\u9009\u4eea\u5668<\/i>/);
});

test("readonly mode disables every input and removes all action buttons", () => {
  for (const sa of [sample, formulaSample, { ...sample, readings: [] }, { ...formulaSample, readings: [] }, { ...sample, itype: "" }]) {
    const html = entryRowHtml(sa, 2, { readOnly: true });
    const inputs = html.match(/<input\b[^>]*>/g) || [];
    assert.ok(inputs.length > 0);
    for (const input of inputs) assert.match(input, / disabled>/);
    assert.doesNotMatch(html, /<button\b|rd-add|rd-del|method-detail/);
    assert.match(html, /class="aux-use" checked disabled>/);
  }
  const line = readingLineHtml(sample, sample.readings[0], true, false, { readOnly: true });
  assert.match(line, /class="rd-raw" data-field="raw" value="0" disabled>/);
  assert.match(line, /class="rd-use" checked disabled>/);
  assert.doesNotMatch(line, /<button\b/);
  assert.doesNotMatch(titrationInputs(formulaSample, { readOnly: true }), /<button\b/);
});

test("multi-reading IDs and final/average participation are preserved", () => {
  const sa = { ...sample, readings: [{ id: 31, raw: 1, use_avg: false }, { id: 32, raw: 2 }] };
  for (const options of [{}, { readOnly: true }]) {
    const html = entryRowHtml(sa, 1, options);
    assert.deepEqual([...html.matchAll(/data-rid="([^"]*)"/g)].map((m) => m[1]), ["31", "32"]);
    assert.deepEqual([...html.matchAll(/class="rd-use"([^>]*)>/g)].map((m) => m[1].includes("checked")), [false, true]);
    const final = entryRowHtml({ ...sa, readings: [{ ...sa.readings[0], is_final: true }, sa.readings[1]] }, 1, options);
    assert.deepEqual([...final.matchAll(/class="rd-use"([^>]*)>/g)].map((m) => m[1].includes("checked")), [true, false]);
    assert.equal((html.match(/class="del rd-del"/g) || []).length, options.readOnly ? 0 : 2);
  }
});

test("formula variables, fixed preparation values and blank/zero defaults are preserved", () => {
  assert.deepEqual(Array.from(methodFormulaVariables(formulaSample.formula)), ["A1", "A2", "m", "v", "B"]);
  assert.deepEqual(Array.from(methodFormulaVariables(null)), []);
  const html = entryRowHtml(formulaSample);
  assert.match(html, /<span class="method-label">M1<\/span>/);
  assert.match(html, /<span class="hint">A2=10 B=0 m=0 v=250<\/span>/);
  assert.match(html, /class="method-detail" type="button" data-method-id="3"/);
  assert.match(html, /class="rd-var" data-var="A1" value="0">/);
  assert.match(html, /class="rd-var" data-var="A1" value="4">/);
  assert.doesNotMatch(html, /data-var="(?:A2|m|v|B)"|rd-raw/);
  const blank = readingLineHtml(formulaSample, null, false);
  assert.match(blank, /data-var="A1" value="">/);
  const unfixed = readingLineHtml({ ...formulaSample, method_constants: "{}", prep_mass: null, prep_vol: null }, null, false);
  assert.deepEqual([...unfixed.matchAll(/data-var="([^"]*)" value=""/g)].map((m) => m[1]), ["A1", "A2", "m", "v", "B"]);
  assert.match(readingLineHtml({ itype: "function" }, null, false), /<span class="tit-inputs"><\/span>/);
  assert.match(titrationInputs({}), /\u672a\u8bbe\u7f6e\u516c\u5f0f\u65b9\u6cd5/);
});

test("DB and audit strings are escaped in text and every dynamic attribute", () => {
  const attack = '\"><img src=x onerror="alert(1)">&\'';
  const escaped = "&quot;&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;";
  for (const options of [{}, { readOnly: true }]) {
    const sa = {
      ...sample, id: attack, itype: attack, analyte: attack, prep_name: attack, instrument: attack, method_name: attack,
      readings: [{ id: attack, raw: attack }], aux: JSON.stringify({ expected: attack, measured: attack, use: true }),
    };
    const html = entryRowHtml(sa, 1, options);
    for (const attribute of ["data-said", "data-itype", "data-analyte", "data-prep", "data-rid"]) {
      assert.ok(html.includes(`${attribute}="${escaped}"`), attribute);
    }
    for (const cls of ["rd-raw", "aux-std", "aux-read"]) {
      const input = (html.match(/<input\b[^>]*>/g) || []).find((tag) => tag.includes(`class="${cls}"`));
      assert.ok(input.includes(`value="${escaped}"`), cls);
    }
    const formula = entryRowHtml({
      ...sa, itype: "function", method_id: attack, formula: "A+m+v+K", prep_mass: attack, prep_vol: attack,
      method_constants: JSON.stringify({ K: attack }), readings: [{ id: attack, extra: JSON.stringify({ A: attack }) }],
      aux: JSON.stringify({ use: true, coefficient: attack }),
    }, 1, options);
    assert.ok(formula.includes(`data-var="A" value="${escaped}"`));
    assert.ok(formula.includes(`K=${escaped} m=${escaped} v=${escaped}`));
    assert.ok(formula.includes(`<span class="aux-show">\u00d7${escaped}</span>`));
    if (!options.readOnly) assert.ok(formula.includes(`data-method-id="${escaped}"`));
    for (const markup of [html, formula]) {
      assert.ok(markup.includes(`<small>${escaped}</small>`));
      assert.doesNotMatch(markup, /<img|onerror="|<script/);
      assert.ok(!markup.includes(attack));
    }
  }
});

test("malformed, null and non-object JSON safely fall back to empty values", () => {
  for (const value of [undefined, null, "", "{broken", "null", "false", "42", '"text"', "[]", [], 42]) {
    for (const options of [{}, { readOnly: true }]) {
      const html = entryRowHtml({ ...formulaSample, formula: "A", method_constants: value, aux: value, readings: [{ id: 1, extra: value }] }, 1, options);
      assert.match(html, /data-var="A" value=""/);
      assert.match(html, /class="aux-std" value=""/);
      assert.match(html, /class="aux-read" value=""/);
    }
  }
  assert.equal(entryRowHtml({ ...sample, aux: JSON.parse(sample.aux) }), entryRowHtml(sample));
  assert.equal(titrationInputs({ ...formulaSample, method_constants: JSON.parse(formulaSample.method_constants) }), titrationInputs(formulaSample));
  for (const reading of [null, {}, { raw: "", extra: "{broken" }, { extra: "null" }, { extra: "{}" }]) {
    assert.equal(readingHasStoredValue(reading), false);
  }
  for (const reading of [{ raw: 0 }, { extra: '{"A":0}' }, { extra: { A: 0 } }]) {
    assert.equal(readingHasStoredValue(reading), true);
  }
});
