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

        const available = header.clientWidth;
        const needed = brand.offsetWidth + nav.scrollWidth + 18;
        const shouldCollapse = needed > available;

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
                window.requestAnimationFrame(updateAllHeaderNavs);
            });
        }

        for (const button of document.querySelectorAll("[data-ui-mode-toggle]")) {
            button.addEventListener("click", () => {
                applyUiMode(root.dataset.uiMode === "minimal" ? "default" : "minimal");
                window.requestAnimationFrame(updateAllHeaderNavs);
            });
        }

        for (const button of document.querySelectorAll("[data-menu-toggle]")) {
            const header = button.closest(".topbar");

            button.addEventListener("click", () => {
                const isOpen = !header.classList.contains("nav-open");
                header.classList.toggle("nav-open", isOpen);
                setMenuState(button, isOpen);
            });
        }

        for (const link of document.querySelectorAll(".nav a")) {
            link.addEventListener("click", () => {
                const header = link.closest(".topbar");

                if (header) {
                    closeHeaderNav(header);
                }
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

        updateAllHeaderNavs();
        window.addEventListener("resize", updateAllHeaderNavs);
        window.addEventListener("load", updateAllHeaderNavs);
    });
})();
