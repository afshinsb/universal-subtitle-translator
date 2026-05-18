(function () {
    const root = document.documentElement;
    const savedTheme = localStorage.getItem("theme") || "dark";
    const savedUiMode = localStorage.getItem("uiMode") || "default";

    function applyTheme(theme) {
        const nextTheme = theme === "light" ? "light" : "dark";
        root.dataset.theme = nextTheme;
        localStorage.setItem("theme", nextTheme);

        for (const button of document.querySelectorAll("[data-theme-toggle]")) {
            button.textContent = "Light";
            button.setAttribute("aria-pressed", nextTheme === "light" ? "true" : "false");
            button.setAttribute("aria-label", `Switch to ${nextTheme === "dark" ? "light" : "dark"} mode`);
        }
    }

    function applyUiMode(mode) {
        const nextMode = mode === "minimal" ? "minimal" : "default";
        root.dataset.uiMode = nextMode;
        localStorage.setItem("uiMode", nextMode);

        for (const button of document.querySelectorAll("[data-ui-mode-toggle]")) {
            button.textContent = "Minimal";
            button.setAttribute("aria-pressed", nextMode === "minimal" ? "true" : "false");
            button.setAttribute("aria-label", `Switch to ${nextMode === "minimal" ? "full" : "minimal"} UI`);
        }
    }

    function closeMobileNav() {
        for (const header of document.querySelectorAll(".topbar")) {
            header.classList.remove("nav-open");
        }

        for (const button of document.querySelectorAll("[data-menu-toggle]")) {
            button.setAttribute("aria-expanded", "false");
            button.setAttribute("aria-label", "Open navigation");
        }
    }

    function loginUrl() {
        const next = `${window.location.pathname}${window.location.search}`;
        return `/login?next=${encodeURIComponent(next)}`;
    }

    function handleAuthExpired(response) {
        if (response && response.status === 401) {
            window.location.href = loginUrl();
            return true;
        }

        return false;
    }

    async function authFetch(url, options) {
        const response = await fetch(url, options);
        handleAuthExpired(response);
        return response;
    }

    async function fetchJson(url, options) {
        const response = await authFetch(url, options);
        const payload = await response.json();

        if (!response.ok || payload.error) {
            throw new Error(payload.error || payload.detail || "Request failed.");
        }

        return payload;
    }

    function setTemporaryButtonText(button, text, duration = 1600) {
        const originalText = button.textContent;
        button.textContent = text;
        setTimeout(() => {
            button.textContent = originalText;
        }, duration);
    }

    async function copyLogs(url, button) {
        const payload = await fetchJson(url);
        const lines = (payload.logs || []).map((log) =>
            `[${log.created_at}] ${log.level} ${log.event}: ${log.message}`
        );
        await navigator.clipboard.writeText(lines.join("\n"));
        setTemporaryButtonText(button, "Copied");
    }

    window.UST = {
        copyLogs,
        authFetch,
        fetchJson,
        handleAuthExpired,
        setTemporaryButtonText,
    };

    applyTheme(savedTheme);
    applyUiMode(savedUiMode);

    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(localStorage.getItem("theme") || "dark");
        applyUiMode(localStorage.getItem("uiMode") || "default");

        for (const button of document.querySelectorAll("[data-theme-toggle]")) {
            button.addEventListener("click", () => {
                applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
            });
        }

        for (const button of document.querySelectorAll("[data-ui-mode-toggle]")) {
            button.addEventListener("click", () => {
                applyUiMode(root.dataset.uiMode === "minimal" ? "default" : "minimal");
            });
        }

        for (const button of document.querySelectorAll("[data-menu-toggle]")) {
            const header = button.closest(".topbar");

            button.addEventListener("click", () => {
                const isOpen = !header.classList.contains("nav-open");
                header.classList.toggle("nav-open", isOpen);
                button.setAttribute("aria-expanded", isOpen ? "true" : "false");
                button.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
            });
        }

        for (const link of document.querySelectorAll(".nav a")) {
            link.addEventListener("click", closeMobileNav);
        }

        window.addEventListener("resize", () => {
            if (window.innerWidth > 900) {
                closeMobileNav();
            }
        });
    });
})();
