const listForm = document.getElementById("list-form");
const listInput = document.getElementById("number-list");
const pasteBtn = document.getElementById("paste-btn");
const xlsxForm = document.getElementById("xlsx-form");
const xlsxInput = document.getElementById("xlsx-file");
const xlsxDrop = document.getElementById("xlsx-drop");
const xlsxSummary = document.getElementById("xlsx-summary");
const pdfForm = document.getElementById("pdf-form");
const pdfInput = document.getElementById("pdf-file");
const pdfDirInput = document.getElementById("pdf-dir");
const pdfDrop = document.getElementById("pdf-drop");
const pdfPickFiles = document.getElementById("pdf-pick-files");
const pdfPickDir = document.getElementById("pdf-pick-dir");
const pdfSummary = document.getElementById("pdf-summary");
const resultsBody = document.getElementById("results-body");
const exportBtn = document.getElementById("export-btn");
const pageSizeEl = document.getElementById("page-size");
const resultsMetaEl = document.getElementById("results-meta");
const paginationEl = document.getElementById("pagination");
const prevPageBtn = document.getElementById("prev-page");
const nextPageBtn = document.getElementById("next-page");
const pageIndicatorEl = document.getElementById("page-indicator");
const progressEl = document.getElementById("progress");
const searchLoaderEl = document.getElementById("search-loader");
const searchLoaderBarEl = document.getElementById("search-loader-bar");
const traceLogEl = document.getElementById("trace-log");
const traceLogWrap = document.querySelector(".trace-log-wrap");
const settingsToggle = document.getElementById("settings-toggle");
const settingsDropdown = document.getElementById("settings-dropdown");
const clearCacheBtn = document.getElementById("clear-cache-btn");
const fullReloadBtn = document.getElementById("full-reload-btn");
const appVersionEl = document.getElementById("app-version");

function redirectToLogin() {
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
    window.location.href = `/login?next=${next}`;
}

async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (response.status === 401) {
        redirectToLogin();
        throw new Error("Unauthorized");
    }
    return response;
}

function getAppVersion() {
    return document.querySelector('meta[name="app-version"]')?.content || "";
}

function formatRuntimeLabel(version, generation) {
    if (!version) {
        return generation ? `gen ${generation}` : "";
    }
    return generation ? `v${version} · gen ${generation}` : `v${version}`;
}

function updateAppVersionLabel(version, generation) {
    if (!appVersionEl) {
        return;
    }
    const label = formatRuntimeLabel(version, generation);
    if (label) {
        appVersionEl.textContent = label;
    }
    appVersionEl.title = label
        ? `Версия ${version || "?"}${generation ? `, generation ${generation}` : ""}`
        : "Версия приложения";
}

async function syncRuntimeInfo() {
    try {
        const response = await apiFetch("/health/live");
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        updateAppVersionLabel(payload.version || getAppVersion(), payload.generation);
        const embedded = getAppVersion();
        if (payload.version && embedded && payload.version !== embedded) {
            appVersionEl?.classList.add("app-version--stale");
            appVersionEl.title = `Доступна v${payload.version}. Обновите страницу (Ctrl+F5).`;
        }
    } catch {
        // ignore health probe errors on startup
    }
}

void syncRuntimeInfo();

let selectedPdfs = [];
let currentResults = [];
let currentPage = 1;
let busy = false;
let traceLines = [];
let pendingTraceLines = [];
let extractPdfEndpoint = null;
let extractPdfStreamEndpoint = null;
let lookupStreamEndpoint = null;
const retryingRows = new Set();
let openRowMenuIndex = null;

const NON_RETRIABLE_ERROR_CODES = new Set([
    "no_numbers_in_pdf",
    "no_numbers_in_xlsx",
    "invalid_number",
    "unsupported_country",
]);

pageSizeEl.addEventListener("change", () => {
    currentPage = 1;
    renderRows(currentResults);
});

prevPageBtn.addEventListener("click", () => {
    if (currentPage > 1) {
        currentPage -= 1;
        renderRows(currentResults);
    }
});

nextPageBtn.addEventListener("click", () => {
    if (currentPage < totalPages(currentResults.length)) {
        currentPage += 1;
        renderRows(currentResults);
    }
});

exportBtn.addEventListener("click", async () => {
    if (!currentResults.length || busy) {
        return;
    }
    await exportResults();
});

resultsBody.addEventListener("click", async (event) => {
    const toggle = event.target.closest(".row-menu__toggle");
    if (toggle) {
        event.stopPropagation();
        const index = Number(toggle.dataset.rowIndex);
        if (!Number.isNaN(index)) {
            toggleRowMenu(index);
        }
        return;
    }
    const retryBtn = event.target.closest(".retry-btn");
    if (retryBtn && !retryBtn.disabled) {
        event.stopPropagation();
        closeRowMenus();
        const index = Number(retryBtn.dataset.rowIndex);
        if (!Number.isNaN(index)) {
            await retryRow(index);
        }
    }
});

settingsToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleSettingsMenu(!isSettingsMenuOpen());
});

clearCacheBtn?.addEventListener("click", async () => {
    closeSettingsMenu();
    await clearServerCache();
});

fullReloadBtn?.addEventListener("click", async () => {
    closeSettingsMenu();
    await reloadService();
});

document.addEventListener("click", (event) => {
    if (!event.target.closest(".settings-menu")) {
        closeSettingsMenu();
    }
    if (!event.target.closest(".row-menu")) {
        closeRowMenus();
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closeSettingsMenu();
        closeRowMenus();
    }
});

listForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const numbers = parseNumbers(listInput.value);
    if (!numbers.length) {
        return;
    }
    await runLookup(numbers);
});

pasteBtn.addEventListener("click", async () => {
    try {
        const text = await navigator.clipboard.readText();
        if (!text) {
            return;
        }
        const current = listInput.value.trim();
        listInput.value = current ? `${current}\n${text}` : text;
        listInput.focus();
    } catch {
        listInput.focus();
    }
});

xlsxForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = xlsxInput.files && xlsxInput.files[0];
    if (!file) {
        return;
    }
    await runXlsxLookup(file);
});

xlsxDrop.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        xlsxInput.click();
    }
});

xlsxInput.addEventListener("change", () => {
    updateXlsxSelection();
});

pdfForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedPdfs.length) {
        return;
    }
    await runPdfLookups(selectedPdfs);
});

pdfPickFiles.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    pdfInput.click();
});

pdfPickDir.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    pdfDirInput.click();
});

pdfDrop.addEventListener("click", (event) => {
    if (event.target.closest("button")) {
        return;
    }
    pdfInput.click();
});

pdfDrop.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        pdfInput.click();
    }
});

pdfInput.addEventListener("change", () => {
    setSelectedPdfs(pdfInput.files);
});

pdfDirInput.addEventListener("change", () => {
    setSelectedPdfs(pdfDirInput.files);
});

["dragenter", "dragover"].forEach((name) => {
    pdfDrop.addEventListener(name, (event) => {
        event.preventDefault();
        pdfDrop.classList.add("is-dragover");
    });
});

["dragleave", "drop"].forEach((name) => {
    pdfDrop.addEventListener(name, () => {
        pdfDrop.classList.remove("is-dragover");
    });
});

pdfDrop.addEventListener("drop", async (event) => {
    event.preventDefault();
    const files = await filesFromDrop(event.dataTransfer);
    setSelectedPdfs(files);
});

function parseNumbers(text) {
    return String(text || "")
        .split(/\r?\n/)
        .map((line) => line.split("\t")[0].trim())
        .filter(Boolean);
}

function setSelectedPdfs(fileList) {
    selectedPdfs = uniquePdfs(fileList);
    if (!selectedPdfs.length) {
        pdfSummary.textContent = "Файлы не выбраны";
        return;
    }
    const names = selectedPdfs.slice(0, 3).map((file) => file.name).join(", ");
    const extra = selectedPdfs.length > 3 ? ` и ещё ${selectedPdfs.length - 3}` : "";
    pdfSummary.textContent = selectedPdfs.length === 1
        ? names
        : `${selectedPdfs.length} PDF: ${names}${extra}`;
}

function updateXlsxSelection() {
    const file = xlsxInput.files && xlsxInput.files[0];
    const hasFile = Boolean(file);
    xlsxSummary.textContent = hasFile ? file.name : "Файл не выбран";
    xlsxDrop.classList.toggle("is-selected", hasFile);
}

function uniquePdfs(fileList) {
    const seen = new Set();
    const collected = [];
    for (const file of fileList || []) {
        if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
            continue;
        }
        const key = `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        collected.push(file);
    }
    return collected;
}

async function filesFromDrop(dataTransfer) {
    const items = dataTransfer && dataTransfer.items ? [...dataTransfer.items] : [];
    if (!items.length) {
        return dataTransfer ? [...(dataTransfer.files || [])] : [];
    }
    const nested = await Promise.all(items.map((item) => filesFromItem(item)));
    return nested.flat();
}

async function filesFromItem(item) {
    const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
    if (entry) {
        return filesFromEntry(entry);
    }
    const file = item.getAsFile && item.getAsFile();
    return file ? [file] : [];
}

async function filesFromEntry(entry) {
    if (!entry) {
        return [];
    }
    if (entry.isFile) {
        return new Promise((resolve) => {
            entry.file((file) => resolve([file]), () => resolve([]));
        });
    }
    if (!entry.isDirectory) {
        return [];
    }
    const reader = entry.createReader();
    const children = await readAllEntries(reader);
    const nested = await Promise.all(children.map(filesFromEntry));
    return nested.flat();
}

function readAllEntries(reader) {
    return new Promise((resolve) => {
        const all = [];
        const readBatch = () => {
            reader.readEntries((batch) => {
                if (!batch.length) {
                    resolve(all);
                    return;
                }
                all.push(...batch);
                readBatch();
            }, () => resolve(all));
        };
        readBatch();
    });
}

async function runLookup(numbers, options = {}) {
    const { preserveTrace = false } = options;
    setBusy(true);
    renderRows([]);
    if (!preserveTrace) {
        resetTrace();
    }
    const collected = [];
    let currentNumber = "";
    try {
        for (let index = 0; index < numbers.length; index += 1) {
            const current = numbers[index];
            currentNumber = current;
            showProgress(
                progressLabel("номер", index + 1, numbers.length),
                waitingHint(current),
            );
            if (numbers.length > 1) {
                appendTraceLine(`— ${current} —`);
            }
            const chunk = await lookupChunk([current], (step) => {
                appendTraceLine(step);
                showProgress(progressLabel("номер", index + 1, numbers.length), step);
            });
            collected.push(...chunk);
            renderRows(collected);
        }
    } catch (error) {
        clearPendingTrace();
        collected.push({
            query: currentNumber,
            error: humanizeError(error),
            error_code: "client_error",
            trace: [humanizeError(error)],
        });
        appendTraceSteps(collected[collected.length - 1], Boolean(currentNumber), currentNumber);
        renderRows(collected);
    } finally {
        hideProgress();
        setBusy(false);
    }
}

async function lookupChunk(numbers, onStep) {
    if (lookupStreamEndpoint !== false) {
        try {
            return await lookupChunkStream(numbers, onStep);
        } catch (error) {
            if (lookupStreamEndpoint === false) {
                return lookupChunkJson(numbers, onStep);
            }
            throw error;
        }
    }
    return lookupChunkJson(numbers, onStep);
}

async function lookupChunkStream(numbers, onStep) {
    const response = await apiFetch("/api/lookup/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ numbers }),
    });
    if (response.status === 404) {
        lookupStreamEndpoint = false;
        throw new Error("Not Found");
    }
    let done = null;
    await readNdjson(response, (event) => {
        if (event.type === "step") {
            if (onStep) {
                onStep(event.text);
            }
            return;
        }
        if (event.type === "error") {
            throw new Error(event.detail || "Ошибка потока поиска");
        }
        if (event.type === "done") {
            done = event.result;
        }
    });
    lookupStreamEndpoint = true;
    if (!done) {
        throw new Error("Сервер не вернул результат поиска");
    }
    return [done];
}

async function lookupChunkJson(numbers, onStep) {
    const response = await apiFetch("/api/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ numbers }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(httpErrorMessage(response, payload));
    }
    const results = payload.results || [];
    if (onStep && results[0] && results[0].trace) {
        for (const step of results[0].trace) {
            onStep(step);
        }
    }
    return results;
}

async function runXlsxLookup(file) {
    setBusy(true);
    renderRows([]);
    resetTrace();
    showProgress("Читаю Excel", "Собираю номера из столбца A…");
    setPendingTrace(["Читаю Excel и собираю номера из столбца A…"]);
    let numbers;
    try {
        const body = new FormData();
        body.append("file", file);
        const response = await apiFetch("/api/extract-xlsx", { method: "POST", body });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = payload.detail || `Ошибка сервера (${response.status})`;
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
        clearPendingTrace();
        if (payload.error_code === "no_numbers_in_xlsx") {
            const row = {
                query: file.name,
                error: payload.error || "В Excel не найдены номера в столбце A",
                error_code: payload.error_code,
                trace: [payload.error || "В Excel не найдены номера в столбце A"],
            };
            appendTraceSteps(row, false);
            renderRows([row]);
            return;
        }
        numbers = payload.numbers || [];
        appendTraceSteps({
            trace: [`Excel: найдено ${numbers.length} ${pluralizeNumbers(numbers.length)}`],
        }, false);
        if (!numbers.length) {
            throw new Error("В Excel не найдены номера в столбце A");
        }
    } catch (error) {
        clearPendingTrace();
        const row = {
            query: file.name,
            error: error.message || "Не удалось прочитать Excel",
            error_code: "client_error",
            trace: [error.message || "Не удалось прочитать Excel"],
        };
        appendTraceSteps(row, false);
        renderRows([row]);
        return;
    } finally {
        hideProgress();
        setBusy(false);
    }
    await runLookup(numbers, { preserveTrace: true });
}

async function runPdfLookups(files) {
    setBusy(true);
    renderRows([]);
    resetTrace();
    const collected = [];
    let currentFile = null;
    try {
        for (let index = 0; index < files.length; index += 1) {
            const file = files[index];
            currentFile = file;
            showProgress(
                progressLabel("PDF", index + 1, files.length, file.name),
                "Извлекаю номер из PDF…",
            );
            appendTraceLine("— PDF —");
            appendTraceLine(`Файл: ${file.name}`);
            const extracted = await extractPdfFile(file, (step) => {
                appendTraceLine(step);
                showProgress(
                    progressLabel("PDF", index + 1, files.length, file.name),
                    step,
                );
            });
            if (extracted.warning) {
                appendTraceLine(extracted.warning);
            }
            if (extracted.legacy) {
                appendTraceSection("", extracted.extractTrace);
                for (const result of extracted.results) {
                    appendTraceSteps(
                        result,
                        extracted.results.length > 1 || files.length > 1,
                        file.name,
                    );
                }
                collected.push(...extracted.results);
                renderRows(collected);
                continue;
            }
            if (extracted.errorCode === "no_numbers_in_pdf") {
                collected.push({
                    query: file.name,
                    error: extracted.error || "В PDF не найден номер сертификата",
                    error_code: extracted.errorCode,
                    trace: extracted.extractTrace,
                });
                renderRows(collected);
                continue;
            }
            for (const number of extracted.numbers) {
                showProgress(
                    progressLabel("PDF", index + 1, files.length, file.name),
                    waitingHint(number),
                );
                if (extracted.numbers.length > 1 || files.length > 1) {
                    appendTraceLine(`— ${number} —`);
                }
                const chunk = await lookupChunk([number], (step) => {
                    appendTraceLine(step);
                    showProgress(
                        progressLabel("PDF", index + 1, files.length, file.name),
                        step,
                    );
                });
                collected.push(...chunk);
                renderRows(collected);
            }
        }
    } catch (error) {
        clearPendingTrace();
        collected.push({
            query: currentFile ? currentFile.name : "",
            error: humanizeError(error),
            error_code: "client_error",
            trace: [humanizeError(error)],
        });
        appendTraceSteps(
            collected[collected.length - 1],
            true,
            currentFile ? currentFile.name : "",
        );
        renderRows(collected);
    } finally {
        hideProgress();
        setBusy(false);
    }
}

async function extractPdfFile(file, onStep) {
    if (extractPdfEndpoint === false) {
        return lookupPdfLegacy(file);
    }
    if (extractPdfStreamEndpoint !== false) {
        try {
            return await extractPdfFileStream(file, onStep);
        } catch (error) {
            if (extractPdfStreamEndpoint === false) {
                return extractPdfFileJson(file, onStep);
            }
            throw error;
        }
    }
    return extractPdfFileJson(file, onStep);
}

async function extractPdfFileStream(file, onStep) {
    const body = new FormData();
    body.append("file", file);
    const response = await apiFetch("/api/extract-pdf/stream", { method: "POST", body });
    if (response.status === 404) {
        extractPdfStreamEndpoint = false;
        throw new Error("Not Found");
    }
    let done = null;
    await readNdjson(response, (event) => {
        if (event.type === "step") {
            if (onStep) {
                onStep(event.text);
            }
            return;
        }
        if (event.type === "error") {
            throw new Error(event.detail || "Не удалось прочитать PDF");
        }
        if (event.type === "done") {
            done = event;
        }
    });
    extractPdfStreamEndpoint = true;
    extractPdfEndpoint = true;
    if (!done) {
        throw new Error("Сервер не вернул результат разбора PDF");
    }
    return {
        legacy: false,
        streamed: true,
        numbers: done.numbers || [],
        extractTrace: [],
        error: done.error,
        errorCode: done.error_code,
        truncated: Boolean(done.truncated),
        totalFound: done.total_found,
        warning: done.warning,
    };
}

async function extractPdfFileJson(file, onStep) {
    const body = new FormData();
    body.append("file", file);
    const response = await apiFetch("/api/extract-pdf", { method: "POST", body });
    if (response.status === 404) {
        extractPdfEndpoint = false;
        return lookupPdfLegacy(file);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(httpErrorMessage(response, payload));
    }
    extractPdfEndpoint = true;
    const extractTrace = payload.extract_trace || [];
    if (onStep) {
        for (const step of extractTrace) {
            onStep(step);
        }
    }
    return {
        legacy: false,
        streamed: false,
        numbers: payload.numbers || [],
        extractTrace,
        error: payload.error,
        errorCode: payload.error_code,
        truncated: Boolean(payload.truncated),
        totalFound: payload.total_found,
        warning: payload.warning,
    };
}

async function lookupPdfLegacy(file) {
    setPendingTrace([
        `Файл: ${file.name}`,
        "Извлекаю номер из PDF и ищу в реестре…",
    ]);
    const body = new FormData();
    body.append("file", file);
    const response = await apiFetch("/api/lookup-pdf", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(httpErrorMessage(response, payload));
    }
    const extractTrace = payload.extract_trace || [];
    if (payload.error_code === "no_numbers_in_pdf") {
        return {
            legacy: true,
            extractTrace,
            results: [{
                query: file.name,
                error: payload.error || "В PDF не найден номер сертификата",
                error_code: payload.error_code,
                trace: extractTrace,
            }],
        };
    }
    return {
        legacy: true,
        extractTrace,
        results: payload.results || [],
    };
}

function renderRows(results) {
    currentResults = Array.isArray(results) ? [...results] : [];
    const pages = totalPages(currentResults.length);
    currentPage = Math.min(Math.max(currentPage, 1), pages);
    updateResultsControls(currentResults.length, pages);
    if (!currentResults.length) {
        resultsBody.innerHTML = '<tr class="empty"><td colspan="7">Пока ничего не искали</td></tr>';
        return;
    }
    closeRowMenus();
    const start = (currentPage - 1) * pageSize();
    const pageRows = currentResults.slice(start, start + pageSize());
    resultsBody.innerHTML = pageRows.map((item, localIndex) => rowHtml(item, start + localIndex)).join("");
}

function isRetriableRow(item) {
    if (!item || !item.error || !item.query) {
        return false;
    }
    if (item.error_code && NON_RETRIABLE_ERROR_CODES.has(item.error_code)) {
        return false;
    }
    return true;
}

async function retryRow(globalIndex) {
    if (retryingRows.has(globalIndex) || busy) {
        return;
    }
    const item = currentResults[globalIndex];
    if (!item || !isRetriableRow(item)) {
        return;
    }
    const number = item.query;
    retryingRows.add(globalIndex);
    renderRows(currentResults);
    try {
        appendTraceLine(`— Повтор: ${number} —`);
        showProgress("Повтор", waitingHint(number));
        const chunk = await lookupChunk([number], (step) => {
            appendTraceLine(step);
            showProgress("Повтор", step);
        });
        const result = chunk[0] || {
            query: number,
            error: "Сервер не вернул результат поиска",
            error_code: "client_error",
        };
        currentResults[globalIndex] = result;
        appendTraceSteps(result, false, number);
    } catch (error) {
        clearPendingTrace();
        const failed = {
            query: number,
            error: humanizeError(error),
            error_code: "client_error",
            trace: [humanizeError(error)],
        };
        currentResults[globalIndex] = failed;
        appendTraceSteps(failed, false, number);
    } finally {
        retryingRows.delete(globalIndex);
        hideProgress();
        renderRows(currentResults);
    }
}

function updateResultsControls(total, pages) {
    resultsMetaEl.textContent = total === 1
        ? "1 запись"
        : `${total} ${pluralizeRecords(total)}`;
    exportBtn.disabled = busy || total === 0;
    paginationEl.hidden = total === 0;
    pageIndicatorEl.textContent = total === 0
        ? "Страница 0 из 0"
        : `Страница ${currentPage} из ${pages}`;
    prevPageBtn.disabled = busy || currentPage <= 1;
    nextPageBtn.disabled = busy || currentPage >= pages;
    pageSizeEl.disabled = busy || total === 0;
}

function pageSize() {
    return Number(pageSizeEl.value) || 20;
}

function totalPages(total) {
    return Math.max(1, Math.ceil(total / pageSize()));
}

function pluralizeRecords(total) {
    const mod10 = total % 10;
    const mod100 = total % 100;
    if (mod10 === 1 && mod100 !== 11) {
        return "запись";
    }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
        return "записи";
    }
    return "записей";
}

async function exportResults() {
    setBusy(true);
    try {
        const response = await apiFetch("/api/export-xlsx", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ results: currentResults }),
        });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            const detail = payload.detail || `Ошибка сервера (${response.status})`;
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "cert-parser-results.xlsx";
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (error) {
        traceLogEl.innerHTML = `<li class="muted">${escapeHtml(error.message || "Не удалось экспортировать результаты")}</li>`;
        scrollTraceToBottom();
    } finally {
        setBusy(false);
    }
}

function resetTrace() {
    traceLines = [];
    pendingTraceLines = [];
    renderTraceView();
}

const TRACE_TIME_RE = /^(\d{2}:\d{2}:\d{2})\t(.*)$/s;

function formatTraceTime(date = new Date()) {
    const pad = (value) => String(value).padStart(2, "0");
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function stampTraceLine(line) {
    if (TRACE_TIME_RE.test(line)) {
        return line;
    }
    return `${formatTraceTime()}\t${line}`;
}

function parseTraceLine(line) {
    const match = TRACE_TIME_RE.exec(line);
    if (match) {
        return { time: match[1], text: match[2] };
    }
    return { time: formatTraceTime(), text: line };
}

function appendTraceLine(line) {
    if (!line) {
        return;
    }
    pendingTraceLines = [];
    traceLines.push(stampTraceLine(line));
    renderTraceView();
}

function appendTraceSection(header, steps) {
    if (header) {
        traceLines.push(stampTraceLine(header));
    }
    for (const step of steps || []) {
        if (step) {
            traceLines.push(stampTraceLine(step));
        }
    }
    renderTraceView();
}

function appendTraceSteps(item, withHeader, headerFallback) {
    const steps = [...(item.trace || [])];
    if (!steps.length && item.error) {
        steps.push(item.error);
    }
    if (!steps.length) {
        return;
    }
    if (withHeader) {
        traceLines.push(stampTraceLine(`— ${traceItemLabel(item, headerFallback)} —`));
    }
    traceLines.push(...steps.map(stampTraceLine));
    renderTraceView();
}

function traceItemLabel(item, fallback) {
    return item.official_number || item.normalized || item.query || fallback || "запрос";
}

function humanizeError(error) {
    const message = error && error.message ? error.message : "";
    if (message === "Not Found") {
        return "Метод API не найден. Перезапустите сервер приложения.";
    }
    if (message === "Failed to fetch") {
        return "Не удалось связаться с сервером. Проверьте, что uvicorn запущен.";
    }
    return message || "Неизвестная ошибка";
}

function httpErrorMessage(response, payload) {
    const detail = payload && payload.detail;
    if (typeof detail === "string" && detail && detail !== "Not Found") {
        return detail;
    }
    if (Array.isArray(detail) && detail.length) {
        return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    if (response.status === 404) {
        return "Метод API не найден. Перезапустите сервер приложения.";
    }
    if (response.status === 503) {
        return typeof detail === "string" && detail
            ? detail
            : "Сервис перезапускается, повторите через несколько секунд";
    }
    if (response.status === 409) {
        return typeof detail === "string" && detail
            ? detail
            : "Операция временно недоступна, повторите позже";
    }
    if (response.status === 400) {
        return "Неверный запрос к серверу";
    }
    if (response.status >= 500) {
        return `Ошибка сервера (${response.status})`;
    }
    return `Ошибка сервера (${response.status})`;
}

function setPendingTrace(steps) {
    pendingTraceLines = (steps || []).filter(Boolean);
    renderTraceView();
}

function clearPendingTrace() {
    pendingTraceLines = [];
    renderTraceView();
}

function renderTraceView() {
    const lines = [...traceLines];
    if (pendingTraceLines.length) {
        lines.push(...pendingTraceLines.map(stampTraceLine));
    }
    if (!lines.length) {
        traceLogEl.innerHTML = '<li class="muted">Здесь появятся шаги: разбор номера, страна, GET/POST в реестр, сколько строк вернулось.</li>';
        scrollTraceToBottom();
        return;
    }
    traceLogEl.innerHTML = lines.map((line, index) => {
        const { time, text } = parseTraceLine(line);
        const pending = index >= traceLines.length;
        const cssClass = pending ? " trace-line pending" : " trace-line";
        const stepNumber = index + 1;
        return `<li class="${cssClass.trim()}"><span class="trace-time">${escapeHtml(time)}</span><span class="trace-index">${stepNumber}.</span><span class="trace-text">${escapeHtml(text)}</span></li>`;
    }).join("");
    scrollTraceToBottom();
}

function rowHtml(item, globalIndex) {
    const number = escapeHtml(item.official_number || item.normalized || item.query || "—");
    const country = escapeHtml(item.country_code || "—");
    const safeUrl = safeHref(item.url);
    const link = safeUrl
        ? `<a href="${escapeAttr(safeUrl)}" target="_blank" rel="noopener noreferrer">Открыть карточку</a>`
        : "—";
    const validFrom = escapeHtml(formatDate(item.valid_from));
    const validUntil = escapeHtml(formatDate(item.valid_until));
    const statusClass = statusCss(item.status_code);
    const status = escapeHtml(item.status || "—");
    const errorContent = item.error ? `<span class="error">${escapeHtml(item.error)}</span>` : "—";
    const rowClasses = ["result-row"];
    if (retryingRows.has(globalIndex)) {
        rowClasses.push("row-retrying");
    }
    if (isRetriableRow(item)) {
        rowClasses.push("result-row--has-menu");
    }
    const menu = rowMenuHtml(item, globalIndex);
    return `<tr class="${rowClasses.join(" ")}">
        <td>${number}</td>
        <td>${country}</td>
        <td>${link}</td>
        <td>${validFrom}</td>
        <td>${validUntil}</td>
        <td class="${statusClass}">${status}</td>
        <td class="error-cell">${errorContent}${menu}</td>
    </tr>`;
}

function rowMenuHtml(item, globalIndex) {
    if (!isRetriableRow(item)) {
        return "";
    }
    const retrying = retryingRows.has(globalIndex);
    const disabled = busy || retrying ? " disabled" : "";
    const retryLabel = retrying ? "Повтор…" : "Повторить";
    return `<div class="row-menu" data-row-index="${globalIndex}">
        <button type="button" class="row-menu__toggle" title="Действия" aria-label="Действия строки"
                aria-haspopup="menu" aria-expanded="false" data-row-index="${globalIndex}">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
                 fill="currentColor" aria-hidden="true">
                <circle cx="12" cy="5" r="2"/>
                <circle cx="12" cy="12" r="2"/>
                <circle cx="12" cy="19" r="2"/>
            </svg>
        </button>
        <div class="row-menu__dropdown" role="menu" hidden>
            <button type="button" class="row-menu__item retry-btn" role="menuitem"
                    data-row-index="${globalIndex}"${disabled}>${retryLabel}</button>
        </div>
    </div>`;
}

function closeRowMenus() {
    openRowMenuIndex = null;
    for (const menu of document.querySelectorAll(".row-menu")) {
        const toggle = menu.querySelector(".row-menu__toggle");
        const dropdown = menu.querySelector(".row-menu__dropdown");
        menu.classList.remove("is-open");
        if (dropdown) {
            dropdown.hidden = true;
        }
        if (toggle) {
            toggle.setAttribute("aria-expanded", "false");
        }
    }
}

function toggleRowMenu(globalIndex) {
    const menu = document.querySelector(`.row-menu[data-row-index="${globalIndex}"]`);
    if (!menu) {
        return;
    }
    const isOpen = openRowMenuIndex === globalIndex;
    closeRowMenus();
    if (isOpen) {
        return;
    }
    const toggle = menu.querySelector(".row-menu__toggle");
    const dropdown = menu.querySelector(".row-menu__dropdown");
    openRowMenuIndex = globalIndex;
    menu.classList.add("is-open");
    if (dropdown) {
        dropdown.hidden = false;
    }
    if (toggle) {
        toggle.setAttribute("aria-expanded", "true");
    }
}

function statusCss(code) {
    if (code === "01" || code === "04" || code === "05" || code === "ISSUED" || code === "6") {
        return "status-ok";
    }
    if (code === "02" || code === "03" || code === "09" || code === "CANCELED" || code === "SUSPENDED") {
        return "status-bad";
    }
    return "";
}

function formatDate(value) {
    if (!value) {
        return "—";
    }
    const [year, month, day] = value.split("-");
    if (!day) {
        return value;
    }
    return `${day}.${month}.${year}`;
}

function waitingHint(number) {
    const upper = String(number || "").toUpperCase();
    if (/\bKZ\b/.test(upper)) {
        return "Казахстан, tech.eaeunion.org; если не найден — eokno.gov.kz (JSF, 10–30 с).";
    }
    if (/\bRU\b/.test(upper)) {
        return "Россия, tech.eaeunion.org; если не найден — pub.fsa.gov.ru.";
    }
    if (/\bBY\b/.test(upper)) {
        return "Беларусь, tech.eaeunion.org; если не найден — api.belgiss.by.";
    }
    if (/\bKG\b/.test(upper)) {
        return "Кыргызстан, tech.eaeunion.org; если не найден — swis.trade.kg.";
    }
    return "Идёт поиск в реестре…";
}

function progressLabel(kind, current, total, detail) {
    const kindLabel = kind === "PDF" ? "PDF" : "Номер";
    const base = total > 1 ? `${kindLabel} ${current} из ${total}` : kindLabel;
    return detail ? `${base}: ${detail}` : base;
}

function pluralizeNumbers(total) {
    const mod10 = total % 10;
    const mod100 = total % 100;
    if (mod10 === 1 && mod100 !== 11) {
        return "номер";
    }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
        return "номера";
    }
    return "номеров";
}

function showProgress(label, detail) {
    progressEl.hidden = false;
    progressEl.textContent = detail ? `${label}. ${detail}` : label;
    setSearchLoader(true);
}

function hideProgress() {
    progressEl.hidden = true;
    setSearchLoader(false);
}

function setSearchLoader(active) {
    if (searchLoaderEl) {
        searchLoaderEl.hidden = !active;
    }
    if (searchLoaderBarEl) {
        searchLoaderBarEl.hidden = !active;
    }
}

function scrollTraceToBottom() {
    if (traceLogWrap) {
        traceLogWrap.scrollTop = traceLogWrap.scrollHeight;
    }
}

function setBusy(isBusy) {
    busy = isBusy;
    for (const button of document.querySelectorAll("button:not([data-keep-enabled])")) {
        button.disabled = isBusy;
    }
    updateResultsControls(currentResults.length, totalPages(currentResults.length));
}

function isSettingsMenuOpen() {
    return !settingsDropdown.hidden;
}

function toggleSettingsMenu(open) {
    settingsDropdown.hidden = !open;
    settingsToggle.setAttribute("aria-expanded", open ? "true" : "false");
}

function closeSettingsMenu() {
    toggleSettingsMenu(false);
}

async function clearServerCache() {
    try {
        const response = await apiFetch("/api/cache/clear", { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(httpErrorMessage(response, payload));
        }
        traceLogEl.innerHTML = `<li class="status-ok">${escapeHtml(payload.message || "Кэш очищен")}</li>`;
        scrollTraceToBottom();
    } catch (error) {
        traceLogEl.innerHTML = `<li class="error">${escapeHtml(humanizeError(error))}</li>`;
        scrollTraceToBottom();
    }
}

async function reloadService() {
    resetTrace();
    showProgress("Перезапуск сервиса", "Сбрасываю HTTP-сессии, провайдеры и OCR…");
    setPendingTrace([
        "Перезапуск сервиса…",
        "Закрываю соединения с реестрами, перечитываю настройки, сбрасываю OCR.",
    ]);
    try {
        const response = await apiFetch("/api/reload", { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(httpErrorMessage(response, payload));
        }
        clearPendingTrace();
        appendTraceSteps({
            query: "сервис",
            trace: [payload.message || "Сервис перезапущен"],
        }, false);
        showProgress("Перезапуск сервиса", "Готово, обновляю страницу…");
        await sleep(400);
        const version = payload.version || getAppVersion() || String(Date.now());
        window.location.href = `${window.location.pathname}?v=${encodeURIComponent(version)}`;
    } catch (error) {
        hideProgress();
        clearPendingTrace();
        appendTraceSteps({
            query: "сервис",
            error: humanizeError(error),
            trace: [humanizeError(error)],
        }, false);
    }
}

function sleep(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}

async function readNdjson(response, onEvent) {
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(httpErrorMessage(response, payload));
    }
    const emitLines = (chunk) => {
        const lines = chunk.split("\n");
        const rest = lines.pop() || "";
        for (const line of lines) {
            if (!line.trim()) {
                continue;
            }
            onEvent(JSON.parse(line));
        }
        return rest;
    };
    if (!response.body || !response.body.getReader) {
        emitLines(`${await response.text()}\n`);
        return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        buffer = emitLines(buffer);
        if (done) {
            break;
        }
    }
    if (buffer.trim()) {
        onEvent(JSON.parse(buffer));
    }
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
    return escapeHtml(value).replaceAll("'", "&#39;");
}

function safeHref(url) {
    if (!url) {
        return null;
    }
    try {
        const parsed = new URL(url);
        if (parsed.protocol === "http:" || parsed.protocol === "https:") {
            return parsed.href;
        }
    } catch {
        return null;
    }
    return null;
}
