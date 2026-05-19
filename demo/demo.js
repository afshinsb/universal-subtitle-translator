const pageMeta = {
    home: ["Subtitle Translator", "Clean subtitles for your library"],
    batch: ["Batch Translation", "Translate a folder of movies or shows"],
    outputs: ["Outputs", "Finished subtitle translations"],
    about: ["About", "Universal Subtitle Translator"],
    settings: ["Settings", "Loaded from your environment"],
    logs: ["Logs", "Activity, warnings, errors, provider usage, and cleanup events"],
};

const initialJobs = [
    { id: "job-demo-104", input: "Pilot.en.srt", output: "Pilot.fa.srt", status: "done", progress: 100 },
    { id: "job-demo-103", input: "Movie.Night.2026.mkv", output: "Movie.Night.2026.fa.srt", status: "running", progress: 68 },
    { id: "job-demo-102", input: "Episode.02.mkv", output: "", status: "skipped", progress: 100 },
    { id: "job-demo-101", input: "Archive.Special.en.srt", output: "Archive.Special.fa.srt", status: "done", progress: 100 },
];

const scanRows = [
    {
        video: "Movie.Night.2026.mkv",
        subfolder: ".",
        source: "external en",
        reason: "External subtitle preferred by language priority",
        step: "found external subtitle",
        subtitles: "524",
        output: "Movie.Night.2026.fa.srt",
        note: "",
    },
    {
        video: "Shows/Episode.01.mkv",
        subfolder: "Shows",
        source: "embedded en",
        reason: "Embedded subtitle selected by language priority",
        step: "extracting embedded subtitle",
        subtitles: "760",
        output: "Episode.01.fa.srt",
        note: "Read-only media; output will be saved in OUTPUT_DIR",
    },
    {
        video: "Shows/Episode.02.mkv",
        subfolder: "Shows",
        source: "none",
        reason: "No external or extractable embedded subtitle found",
        step: "skipped",
        subtitles: "0",
        output: "-",
        note: "",
    },
];

const batches = [
    { folder: "/media/Movies", status: "running", done: 2, failed: 0, total: 4 },
    { folder: "/media/Shows", status: "partial", done: 7, failed: 1, total: 8 },
    { folder: "/media/Archive", status: "done", done: 12, failed: 0, total: 12 },
];

const readiness = [
    ["OpenAI API key", "Mocked", "Demo mode never uses a real API key."],
    ["OpenAI model", "Mock provider", "No provider requests are sent."],
    ["Upload folder", "Disabled", "Browser uploads are not available in the public demo."],
    ["Output folder", "Mocked", "No real files are written."],
    ["Media root", "/media", "Sample mounted path for Docker deployments."],
    ["Authentication", "Demo session", "No real login is required."],
];

const settingsRows = [
    ["Model", "mock-demo-provider"],
    ["Upload dir", "disabled in public demo"],
    ["Output dir", "/app/data/outputs"],
    ["Temp dir", "/app/data/temp"],
    ["Database", "not used"],
    ["Media root", "/media"],
    ["Default source language", "Auto"],
    ["Default target language", "Persian"],
    ["Default style", "natural_conversational"],
    ["Batch size", "40"],
    ["Max chars per batch", "12000"],
    ["Batch file concurrency", "4"],
    ["Max upload size", "disabled"],
    ["FFmpeg timeout", "simulated"],
    ["OpenAI timeout", "simulated"],
];

let jobs = initialJobs.map((job) => ({ ...job }));
let logs = [
    {
        id: "log-208",
        severity: "success",
        category: "translation",
        title: "Translation completed",
        message: "Demo job completed for Pilot.en.srt. Output: Pilot.fa.srt.",
        time: "2 minutes ago",
        event: "job_completed",
        context: [["Job", "job-demo-104"], ["Model", "mock-demo-provider"], ["Tokens", "1,284"]],
        quiet: false,
    },
    {
        id: "log-207",
        severity: "info",
        category: "media",
        title: "Source subtitle selected",
        message: "External subtitle selected for Movie.Night.2026.mkv. Source: Movie.Night.2026.en.srt.",
        time: "4 minutes ago",
        event: "source_subtitle_selected",
        context: [["Batch", "batch-demo-18"], ["Language", "en"]],
        quiet: false,
    },
    {
        id: "log-206",
        severity: "warning",
        category: "config",
        title: "Public demo mode",
        message: "Real uploads, provider calls, and database writes are disabled.",
        time: "5 minutes ago",
        event: "demo_mode_enabled",
        context: [["Mode", "DEMO_MODE"], ["Backend", "none"]],
        quiet: false,
    },
    {
        id: "log-205",
        severity: "info",
        category: "translation",
        title: "Provider request completed",
        message: "Mock provider returned simulated subtitles for batch 1 of 3.",
        time: "7 minutes ago",
        event: "provider_request_completed",
        context: [["Input tokens", "612"], ["Output tokens", "490"]],
        quiet: true,
    },
    {
        id: "log-204",
        severity: "error",
        category: "media",
        title: "Media file skipped",
        message: "Episode.02.mkv was skipped because no readable subtitle track was found.",
        time: "9 minutes ago",
        event: "media_file_skipped",
        context: [["File", "Episode.02.mkv"], ["Status", "skipped"]],
        quiet: false,
    },
];

const pageTitle = document.getElementById("page-title");
const pageSubtitle = document.getElementById("page-subtitle");
const pages = Array.from(document.querySelectorAll("[data-page]"));
const pageLinks = Array.from(document.querySelectorAll("[data-page-link]"));
const themeToggle = document.querySelector("[data-theme-toggle]");
const uiModeToggle = document.querySelector("[data-ui-mode-toggle]");

function setMenuState(button, isOpen) {
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
    button.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
}

function closeHeaderNav(header) {
    const button = header.querySelector("[data-menu-toggle]");
    header.classList.remove("nav-open");
    if (button) {
        setMenuState(button, false);
    }
}

function updateHeaderNav(header) {
    const brand = header.querySelector(".brand");
    const nav = header.querySelector(".nav");
    const button = header.querySelector("[data-menu-toggle]");

    if (!brand || !nav || !button) {
        return;
    }

    const wasOpen = header.classList.contains("nav-open");
    header.classList.remove("nav-collapsed", "nav-open");
    setMenuState(button, false);

    const previousWrap = nav.style.flexWrap;
    nav.style.flexWrap = "nowrap";
    const shouldCollapse = brand.offsetWidth + nav.scrollWidth + 18 > header.clientWidth;
    nav.style.flexWrap = previousWrap;

    if (shouldCollapse) {
        header.classList.add("nav-collapsed");
        if (wasOpen) {
            header.classList.add("nav-open");
            setMenuState(button, true);
        }
    }
}

function updateAllHeaderNavs() {
    for (const header of document.querySelectorAll(".topbar")) {
        updateHeaderNav(header);
    }
}

function applyTheme(theme) {
    const nextTheme = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    localStorage.setItem("demoTheme", nextTheme);
    themeToggle.textContent = "Light";
    themeToggle.setAttribute("aria-pressed", nextTheme === "light" ? "true" : "false");
    window.requestAnimationFrame(updateAllHeaderNavs);
}

function applyUiMode(mode) {
    const nextMode = mode === "minimal" ? "minimal" : "default";
    document.documentElement.dataset.uiMode = nextMode;
    localStorage.setItem("demoUiMode", nextMode);
    uiModeToggle.textContent = "Minimal";
    uiModeToggle.setAttribute("aria-pressed", nextMode === "minimal" ? "true" : "false");
    window.requestAnimationFrame(updateAllHeaderNavs);
}

function setAccountMenu(menu, isOpen) {
    const button = menu.querySelector("[data-account-toggle]");
    const popover = menu.querySelector("[data-account-popover]");

    if (!button || !popover) {
        return;
    }

    popover.hidden = !isOpen;
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
    button.setAttribute("aria-label", isOpen ? "Close account menu" : "Open account menu");
}

function closeAccountMenus(exceptMenu = null) {
    for (const menu of document.querySelectorAll(".account-menu")) {
        if (menu !== exceptMenu) {
            setAccountMenu(menu, false);
        }
    }
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function showPage(pageName) {
    const safePage = pageMeta[pageName] ? pageName : "home";

    for (const page of pages) {
        page.hidden = page.dataset.page !== safePage;
    }

    for (const link of pageLinks) {
        link.classList.toggle("active", link.dataset.pageLink === safePage);
    }

    pageTitle.textContent = pageMeta[safePage][0];
    pageSubtitle.textContent = pageMeta[safePage][1];

    if (location.hash.slice(1) !== safePage) {
        history.replaceState(null, "", `#${safePage}`);
    }
}

function renderHome() {
    const outputs = document.getElementById("recent-outputs");
    const recentJobs = document.getElementById("recent-jobs");

    outputs.innerHTML = jobs
        .filter((job) => job.output)
        .slice(0, 5)
        .map((job) => `
            <div class="recent-item">
                <div>
                    <strong>${escapeHtml(job.output)}</strong>
                    <span>${escapeHtml(job.input)}</span>
                </div>
            </div>
        `)
        .join("");

    recentJobs.innerHTML = jobs
        .slice(0, 6)
        .map((job) => `
            <a class="recent-item recent-link" href="#logs" data-page-link="logs">
                <div>
                    <strong>${escapeHtml(job.input)}</strong>
                    <span>${job.progress}% complete</span>
                </div>
                <span class="status ${job.status}">${job.status}</span>
            </a>
        `)
        .join("");
}

function renderOutputs() {
    document.getElementById("outputs-table").innerHTML = jobs
        .filter((job) => job.output)
        .map((job) => `
            <tr>
                <td class="path">${escapeHtml(job.output)}</td>
                <td class="path">${escapeHtml(job.input)}</td>
                <td><span class="status ${job.status}">${job.status}</span></td>
                <td><button type="button" class="primary" data-open-log>Download</button></td>
            </tr>
        `)
        .join("");
}

function renderScanRows() {
    document.getElementById("scan-table").innerHTML = scanRows.map((row) => `
        <tr>
            <td class="path">${escapeHtml(row.video)}</td>
            <td class="path">${escapeHtml(row.subfolder)}</td>
            <td>
                <div>${escapeHtml(row.source)}</div>
                <div class="file-subtext">${escapeHtml(row.reason)}</div>
            </td>
            <td>${escapeHtml(row.step)}</td>
            <td>${escapeHtml(row.subtitles)}</td>
            <td class="path">
                ${escapeHtml(row.output)}
                ${row.note ? `<div class="file-subtext">${escapeHtml(row.note)}</div>` : ""}
            </td>
        </tr>
    `).join("");
}

function renderBatches() {
    document.getElementById("recent-batches").innerHTML = batches.map((batch) => `
        <tr>
            <td class="path">${escapeHtml(batch.folder)}</td>
            <td><span class="status ${batch.status}">${batch.status}</span></td>
            <td>${batch.done} done${batch.failed ? `, ${batch.failed} failed` : ""} / ${batch.total}</td>
            <td><button type="button" class="secondary" data-open-log>View</button></td>
        </tr>
    `).join("");
}

function renderSettings() {
    document.getElementById("readiness-grid").innerHTML = readiness.map((check) => `
        <div class="readiness-item">
            <div class="readiness-topline">
                <span>${escapeHtml(check[0])}</span>
                <span class="status done">Ready</span>
            </div>
            <strong>${escapeHtml(check[1])}</strong>
            <p>${escapeHtml(check[2])}</p>
        </div>
    `).join("");

    document.getElementById("settings-table").innerHTML = settingsRows.map((row) => `
        <tr>
            <th>${escapeHtml(row[0])}</th>
            <td class="path">${escapeHtml(row[1])}</td>
        </tr>
    `).join("");
}

function renderLogHero() {
    const translated = jobs.filter((job) => job.status === "done").length;
    const errors = logs.filter((log) => log.severity === "error").length;
    const warnings = logs.filter((log) => log.severity === "warning").length;
    const skipped = jobs.filter((job) => job.status === "skipped").length;

    document.getElementById("log-hero").innerHTML = [
        ["Files translated", translated, ""],
        ["Tokens used", "3,418", ""],
        ["Estimated cost", "$0.0000", ""],
        ["Errors", errors, "severity-error"],
        ["Warnings", warnings, "severity-warning"],
        ["Skipped", skipped, ""],
    ].map((metric) => `
        <div class="log-metric ${metric[2]}">
            <span>${metric[0]}</span>
            <strong>${metric[1]}</strong>
        </div>
    `).join("");
}

function renderLogs() {
    const timeline = document.getElementById("log-timeline");
    timeline.innerHTML = logs.map((log) => {
        const search = `${log.severity} ${log.category} ${log.title} ${log.message} ${log.event}`.toLowerCase();
        return `
            <article class="log-entry severity-${log.severity} ${log.quiet ? "is-quiet" : ""}"
                data-severity="${log.severity}"
                data-category="${log.category}"
                data-quiet="${log.quiet}"
                data-search="${escapeHtml(search)}">
                <div class="timeline-dot"></div>
                <div class="log-entry-main">
                    <div class="log-entry-topline">
                        <div class="log-title-wrap">
                            <span class="status ${log.severity}">${log.severity}</span>
                            <span class="pill">${escapeHtml(log.category)}</span>
                            <h2>${escapeHtml(log.title)}</h2>
                        </div>
                        <time>${escapeHtml(log.time)}</time>
                    </div>
                    <p class="log-message">${escapeHtml(log.message)}</p>
                    <div class="log-context">
                        ${log.context.map((item) => `<span><strong>${escapeHtml(item[0])}</strong>${escapeHtml(item[1])}</span>`).join("")}
                    </div>
                </div>
            </article>
        `;
    }).join("");

    document.getElementById("total-log-count").textContent = logs.length;
    renderLogHero();
    applyLogFilters();
}

function applyLogFilters() {
    const query = (document.getElementById("log-search").value || "").trim().toLowerCase();
    const severity = document.getElementById("log-severity-filter").value || "all";
    const category = document.getElementById("log-category-filter").value || "all";
    const includeQuiet = document.getElementById("log-show-quiet").checked;
    const entries = Array.from(document.querySelectorAll(".log-entry"));
    let visible = 0;

    for (const entry of entries) {
        const shouldShow = (!query || entry.dataset.search.includes(query))
            && (severity === "all" || entry.dataset.severity === severity)
            && (category === "all" || entry.dataset.category === category)
            && (includeQuiet || entry.dataset.quiet !== "true");

        entry.hidden = !shouldShow;
        if (shouldShow) {
            visible += 1;
        }
    }

    document.getElementById("visible-log-count").textContent = visible;
    document.getElementById("log-empty").hidden = visible !== 0;
}

function addLog(log) {
    logs.unshift({
        id: `log-demo-${Math.floor(Math.random() * 9000) + 1000}`,
        time: "just now",
        quiet: false,
        ...log,
    });
    renderLogs();
}

function resetDemoData() {
    jobs = initialJobs.map((job) => ({ ...job }));
    logs = logs.slice(-5);
    renderHome();
    renderOutputs();
    renderLogs();
}

function bindEvents() {
    document.addEventListener("click", (event) => {
        const pageLink = event.target.closest("[data-page-link]");
        if (pageLink) {
            event.preventDefault();
            showPage(pageLink.dataset.pageLink);
            closeAccountMenus();
            const header = pageLink.closest(".topbar");
            if (header) {
                closeHeaderNav(header);
            }
        }

        if (event.target.matches("[data-open-log]")) {
            showPage("logs");
        }
    });

    themeToggle.addEventListener("click", () => {
        applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });

    uiModeToggle.addEventListener("click", () => {
        applyUiMode(document.documentElement.dataset.uiMode === "minimal" ? "default" : "minimal");
    });

    for (const button of document.querySelectorAll("[data-menu-toggle]")) {
        const header = button.closest(".topbar");
        button.addEventListener("click", () => {
            const isOpen = !header.classList.contains("nav-open");
            header.classList.toggle("nav-open", isOpen);
            setMenuState(button, isOpen);
        });
    }

    for (const button of document.querySelectorAll("[data-account-toggle]")) {
        const menu = button.closest(".account-menu");
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            const popover = menu.querySelector("[data-account-popover]");
            const isOpen = Boolean(popover && popover.hidden);
            closeAccountMenus(menu);
            setAccountMenu(menu, isOpen);
        });
    }

    document.addEventListener("click", (event) => {
        if (!event.target.closest(".account-menu")) {
            closeAccountMenus();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeAccountMenus();
        }
    });

    document.getElementById("single-file-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const button = document.getElementById("single-submit");
        button.disabled = true;
        button.textContent = "Simulating...";

        window.setTimeout(() => {
            jobs.unshift({
                id: "job-demo-new",
                input: "Demo.Movie.en.srt",
                output: "Demo.Movie.fa.srt",
                status: "done",
                progress: 100,
            });
            addLog({
                severity: "success",
                category: "translation",
                title: "Demo translation completed",
                message: "Simulated translation completed for Demo.Movie.en.srt.",
                event: "demo_translation_completed",
                context: [["Job", "job-demo-new"], ["Provider", "mock"]],
            });
            renderHome();
            renderOutputs();
            button.disabled = false;
            button.textContent = "Simulate Translation";
        }, 800);
    });

    document.getElementById("pick-folder-button").addEventListener("click", () => {
        document.getElementById("folder_path").value = "/media/Shows";
        addLog({
            severity: "info",
            category: "media",
            title: "Demo folder selected",
            message: "Mock folder picker selected /media/Shows.",
            event: "demo_folder_selected",
            context: [["Path", "/media/Shows"]],
        });
    });

    document.getElementById("scan-button").addEventListener("click", () => {
        const scanButton = document.getElementById("scan-button");
        const label = document.getElementById("scan-button-label");
        const startButton = document.getElementById("start-button");
        scanButton.classList.add("is-scanning");
        scanButton.disabled = true;
        label.textContent = "Scanning... 12 files checked";

        window.setTimeout(() => {
            scanButton.classList.remove("is-scanning");
            scanButton.disabled = false;
            label.textContent = "Scan Path";
            startButton.disabled = false;
            document.getElementById("scan-error").textContent = "";
            renderScanRows();
            addLog({
                severity: "info",
                category: "media",
                title: "Preview scan completed",
                message: "Demo scan found 3 ready files and 1 skipped file.",
                event: "demo_scan_completed",
                context: [["Path", document.getElementById("folder_path").value], ["Files", "3"]],
            });
        }, 900);
    });

    document.getElementById("batch-form").addEventListener("submit", (event) => {
        event.preventDefault();
        batches.unshift({ folder: document.getElementById("folder_path").value, status: "running", done: 1, failed: 0, total: 3 });
        renderBatches();
        addLog({
            severity: "success",
            category: "translation",
            title: "Demo batch started",
            message: "Mock batch translation started. No files were read or written.",
            event: "demo_batch_started",
            context: [["Concurrency", document.getElementById("max_concurrency").value], ["Provider", "mock"]],
        });
        showPage("batch");
    });

    document.getElementById("cleanup-button").addEventListener("click", () => {
        resetDemoData();
        document.getElementById("cleanup-result").hidden = false;
        addLog({
            severity: "info",
            category: "cleanup",
            title: "Demo cleanup completed",
            message: "Mock history was reset in browser memory.",
            event: "demo_cleanup_completed",
            context: [["Files deleted", "0"], ["External media", "not touched"]],
        });
    });

    for (const controlId of ["log-search", "log-severity-filter", "log-category-filter", "log-show-quiet"]) {
        const control = document.getElementById(controlId);
        control.addEventListener("input", applyLogFilters);
        control.addEventListener("change", applyLogFilters);
    }

    document.getElementById("download-csv").addEventListener("click", () => {
        addLog({
            severity: "info",
            category: "logs",
            title: "Demo CSV requested",
            message: "CSV download is simulated in public demo mode.",
            event: "demo_csv_requested",
            context: [["Download", "simulated"]],
        });
    });

    document.getElementById("raw-json").addEventListener("click", () => {
        addLog({
            severity: "info",
            category: "logs",
            title: "Demo raw JSON requested",
            message: "Raw JSON view is simulated in public demo mode.",
            event: "demo_json_requested",
            context: [["API", "disabled"]],
        });
    });

    window.addEventListener("hashchange", () => showPage(location.hash.slice(1) || "home"));
}

renderHome();
renderOutputs();
renderScanRows();
renderBatches();
renderSettings();
renderLogs();
applyTheme(localStorage.getItem("demoTheme") || "dark");
applyUiMode(localStorage.getItem("demoUiMode") || "default");
bindEvents();
showPage(location.hash.slice(1) || "home");
updateAllHeaderNavs();
window.addEventListener("resize", updateAllHeaderNavs);
window.addEventListener("load", updateAllHeaderNavs);
