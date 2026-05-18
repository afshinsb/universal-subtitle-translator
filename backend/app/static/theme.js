(function () {
    const root = document.documentElement;
    const savedTheme = localStorage.getItem("theme") || "dark";

    function applyTheme(theme) {
        const nextTheme = theme === "light" ? "light" : "dark";
        root.dataset.theme = nextTheme;
        localStorage.setItem("theme", nextTheme);

        for (const button of document.querySelectorAll("[data-theme-toggle]")) {
            button.textContent = nextTheme === "dark" ? "Dark mode" : "Light mode";
            button.setAttribute("aria-label", `Switch to ${nextTheme === "dark" ? "light" : "dark"} mode`);
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

    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(localStorage.getItem("theme") || "dark");

        for (const button of document.querySelectorAll("[data-theme-toggle]")) {
            button.addEventListener("click", () => {
                applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
            });
        }

    });
})();
