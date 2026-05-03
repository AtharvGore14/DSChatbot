/**
 * Shared import / export / clear for portfolio JSON (instance/user_portfolio.json).
 */
(function () {
    function escapeHtml(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function setPfUI(root, st) {
        const el = root.querySelector("[data-pf-status]");
        if (!el || !st) return;
        if (st.loaded) {
            el.innerHTML =
                '<strong class="text-dark">Portfolio data</strong> — '
                + String(st.positions)
                + " position(s) · "
                + escapeHtml(String(st.source || ""))
                + (st.filename ? " (" + escapeHtml(String(st.filename)) + ")" : "");
            const ex = root.querySelector("[data-pf-export]");
            if (ex) {
                ex.classList.remove("disabled", "opacity-50");
            }
            const cl = root.querySelector("[data-pf-clear]");
            if (cl) cl.disabled = false;
        } else {
            el.innerHTML =
                '<strong class="text-dark">Portfolio data</strong> — none loaded — import JSON to drive dashboard &amp; chat';
            const ex = root.querySelector("[data-pf-export]");
            if (ex) ex.classList.add("disabled", "opacity-50");
            const cl = root.querySelector("[data-pf-clear]");
            if (cl) cl.disabled = true;
        }
    }

    async function refreshPfStatus(root) {
        const url = root.getAttribute("data-status-url");
        if (!url) return;
        try {
            const r = await fetch(url);
            const d = await r.json();
            if (d.status === "ok") setPfUI(root, d);
        } catch (e) {
            /* ignore */
        }
    }

    function bind(root) {
        const apiUrl = root.getAttribute("data-api-url");
        const fileInput = root.querySelector("[data-pf-file]");
        const clearBtn = root.querySelector("[data-pf-clear]");

        if (fileInput && apiUrl) {
            fileInput.addEventListener("change", async function () {
                const f = fileInput.files && fileInput.files[0];
                if (!f) return;
                const fd = new FormData();
                fd.append("file", f);
                try {
                    const r = await fetch(apiUrl, { method: "POST", body: fd });
                    const d = await r.json();
                    if (d.status !== "ok") {
                        window.alert(d.message || "Import failed");
                    } else {
                        setPfUI(root, d);
                        window.location.reload();
                    }
                } catch (e) {
                    window.alert("Import failed — network error");
                }
                fileInput.value = "";
            });
        }

        if (clearBtn && apiUrl) {
            clearBtn.addEventListener("click", async function () {
                if (!window.confirm("Remove the imported portfolio file from this server?")) return;
                try {
                    const r = await fetch(apiUrl, { method: "DELETE" });
                    const d = await r.json();
                    await refreshPfStatus(root);
                    if (d.message) window.alert(d.message);
                    window.location.reload();
                } catch (e) {
                    window.alert("Could not clear — try again.");
                }
            });
        }
    }

    function boot() {
        document.querySelectorAll("#portfolioIoToolbar").forEach(bind);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
