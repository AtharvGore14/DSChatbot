const chartInstances = {};

function buildChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") {
        return;
    }
    if (chartInstances[canvasId]) {
        chartInstances[canvasId].destroy();
    }
    chartInstances[canvasId] = new Chart(canvas, config);
}

function initDashboardLensMode(catalog) {
    function pulseConfig(labels, series) {
        return {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "Change %",
                    data: series,
                    borderColor: "#00c2ff",
                    backgroundColor: "rgba(0, 194, 255, 0.14)",
                    fill: true,
                    tension: 0.35,
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        };
    }

    function snapshotConfig(rows) {
        const labels = rows.map((s) => s.symbol.replace(".NS", ""));
        const prices = rows.map((s) => Number(s.price));
        const changes = rows.map((s) => Number(s.change));
        return {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        type: "bar",
                        label: "Price (₹)",
                        data: prices,
                        backgroundColor: "rgba(93, 62, 255, 0.55)",
                        yAxisID: "y",
                    },
                    {
                        type: "line",
                        label: "Change %",
                        data: changes,
                        borderColor: "#00c2ff",
                        backgroundColor: "rgba(0, 194, 255, 0.15)",
                        tension: 0.35,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        position: "left",
                        title: { display: true, text: "Price" },
                        grid: { color: "rgba(24, 46, 92, 0.08)" },
                    },
                    y1: {
                        position: "right",
                        title: { display: true, text: "Δ %" },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        };
    }

    function renderSnapshot(rows) {
        const box = document.getElementById("dashSnapshotBody");
        if (!box) {
            return;
        }
        box.innerHTML = "";
        if (!rows.length) {
            box.innerHTML = "<div class=\"small text-muted px-1 py-2\">No symbols in this view.</div>";
            return;
        }
        rows.forEach((item) => {
            const row = document.createElement("div");
            row.className = "snapshot-row";
            const ch = Number(item.change);
            row.innerHTML = `<span>${item.symbol}</span><span>₹ ${item.price}</span><span class="${ch >= 0 ? "text-success" : "text-danger"}">${ch}%</span>`;
            box.appendChild(row);
        });
    }

    function renderTopMovers(rows) {
        const box = document.getElementById("dashTopMoversBody");
        if (!box) {
            return;
        }
        box.innerHTML = "";
        if (!rows.length) {
            box.innerHTML = "<div class=\"small text-muted px-1 py-2\">No movers in this lens.</div>";
            return;
        }
        rows.forEach((item) => {
            const row = document.createElement("div");
            row.className = "snapshot-row";
            const ch = Number(item.change);
            row.innerHTML = `<span>${item.symbol}</span><span>₹ ${item.price}</span><span class="${ch >= 0 ? "text-success" : "text-danger"}">${ch}%</span>`;
            box.appendChild(row);
        });
    }

    function setLensActive(lens) {
        document.querySelectorAll("[data-dash-lens]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-dash-lens") === lens);
        });
    }

    function applyLens(lens) {
        let filtered = catalog;
        if (lens === "up") {
            filtered = catalog.filter((s) => s.change > 0);
        } else if (lens === "down") {
            filtered = catalog.filter((s) => s.change < 0);
        } else if (lens !== "all") {
            filtered = catalog.filter((s) => s.sector === lens);
        }

        const hint = document.getElementById("dashLensHint");
        if (!filtered.length) {
            buildChart("marketPulseChart", pulseConfig(["—"], [0]));
            if (document.getElementById("snapshotPriceChart")) {
                buildChart("snapshotPriceChart", snapshotConfig([{
                    symbol: "—",
                    price: 0,
                    change: 0,
                }]));
            }
            renderSnapshot([]);
            renderTopMovers([]);
            if (hint) {
                hint.textContent = "No symbols match this lens — pick another filter.";
            }
            setLensActive(lens);
            return;
        }

        const byAbs = [...filtered].sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
        const pulseRows = byAbs.slice(0, 6);
        buildChart("marketPulseChart", pulseConfig(
            pulseRows.map((s) => s.symbol.replace(".NS", "")),
            pulseRows.map((s) => s.change),
        ));

        const snapRows = byAbs.slice(0, 8);
        renderSnapshot(snapRows);
        if (document.getElementById("snapshotPriceChart")) {
            buildChart("snapshotPriceChart", snapshotConfig(snapRows));
        }

        const movers = [...filtered].sort((a, b) => b.change - a.change).slice(0, 5);
        renderTopMovers(movers);

        if (hint) {
            hint.textContent = `${filtered.length} symbol(s) in this lens · pulse shows top 6 by absolute move`;
        }
        setLensActive(lens);
    }

    document.querySelectorAll("[data-dash-lens]").forEach((btn) => {
        btn.addEventListener("click", () => applyLens(btn.getAttribute("data-dash-lens") || "all"));
    });

    applyLens("all");
}

function initCharts() {
    const dashLensRoot = document.getElementById("dashLensBar");
    const dashCatalog = window.dashboardCatalogData;
    if (dashLensRoot && Array.isArray(dashCatalog) && dashCatalog.length) {
        initDashboardLensMode(dashCatalog);
    } else {
        const dashboardPulse = window.dashboardPulseData || {};
        const pulseLabels = Array.isArray(dashboardPulse.labels) && dashboardPulse.labels.length
            ? dashboardPulse.labels
            : ["Mon", "Tue", "Wed", "Thu", "Fri"];
        const pulseSeries = Array.isArray(dashboardPulse.change_series) && dashboardPulse.change_series.length
            ? dashboardPulse.change_series
            : [0.4, 0.7, 0.2, 0.9, 1.1];

        buildChart("marketPulseChart", {
            type: "line",
            data: {
                labels: pulseLabels,
                datasets: [{
                    label: "Top Movers Change %",
                    data: pulseSeries,
                    borderColor: "#00c2ff",
                    backgroundColor: "rgba(0, 194, 255, 0.14)",
                    fill: true,
                    tension: 0.35,
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    const sectorRows = Array.isArray(window.dashboardSectorData) ? window.dashboardSectorData : [];
    if (sectorRows.length) {
        buildChart("sectorStrengthChart", {
            type: "bar",
            data: {
                labels: sectorRows.map((row) => row.sector),
                datasets: [
                    {
                        label: "Avg Change %",
                        data: sectorRows.map((row) => row.avg_change),
                        backgroundColor: sectorRows.map((row) => row.avg_change >= 0 ? "#4adbc5" : "#ff8a8a"),
                    },
                ],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    const breadth = window.dashboardBreadthData || {};
    if (document.getElementById("marketBreadthChart") && Array.isArray(breadth.labels) && breadth.labels.length) {
        buildChart("marketBreadthChart", {
            type: "doughnut",
            data: {
                labels: breadth.labels,
                datasets: [{
                    data: breadth.values || [],
                    backgroundColor: ["#4adbc5", "#ff8a8a", "#cfd8ea"],
                    borderWidth: 2,
                    borderColor: "#ffffff",
                }],
            },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        });
    }

    const buckets = window.dashboardChangeBucketsData || {};
    if (document.getElementById("changeBucketsChart") && Array.isArray(buckets.labels) && buckets.labels.length) {
        buildChart("changeBucketsChart", {
            type: "bar",
            data: {
                labels: buckets.labels,
                datasets: [{
                    label: "Symbols",
                    data: buckets.values || [],
                    backgroundColor: ["#ff6377", "#ffb347", "#87d187", "#5d3eff"],
                }],
            },
            options: {
                indexAxis: "y",
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    y: { grid: { display: false } },
                },
            },
        });
    }

    const dashCatalogSkipSnap = document.getElementById("dashLensBar") && Array.isArray(window.dashboardCatalogData) && window.dashboardCatalogData.length;
    const snap = window.dashboardSnapshotPriceData || {};
    if (!dashCatalogSkipSnap && document.getElementById("snapshotPriceChart") && Array.isArray(snap.labels) && snap.labels.length) {
        buildChart("snapshotPriceChart", {
            type: "bar",
            data: {
                labels: snap.labels,
                datasets: [
                    {
                        type: "bar",
                        label: "Price (₹)",
                        data: snap.prices || [],
                        backgroundColor: "rgba(93, 62, 255, 0.55)",
                        yAxisID: "y",
                    },
                    {
                        type: "line",
                        label: "Change %",
                        data: snap.changes || [],
                        borderColor: "#00c2ff",
                        backgroundColor: "rgba(0, 194, 255, 0.15)",
                        tension: 0.35,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        position: "left",
                        title: { display: true, text: "Price" },
                        grid: { color: "rgba(24, 46, 92, 0.08)" },
                    },
                    y1: {
                        position: "right",
                        title: { display: true, text: "Δ %" },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        });
    }

    const searchChartPayload = window.searchChartData || {};
    if (
        document.getElementById("searchChangeChart")
        && Array.isArray(searchChartPayload.labels)
        && searchChartPayload.labels.length
    ) {
        const deltas = searchChartPayload.changes || [];
        buildChart("searchChangeChart", {
            type: "bar",
            data: {
                labels: searchChartPayload.labels,
                datasets: [{
                    label: "Change %",
                    data: deltas,
                    backgroundColor: deltas.map((value) => (Number(value) >= 0 ? "#4adbc5" : "#ff8a8a")),
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        });
        buildChart("searchPriceChart", {
            type: "bar",
            data: {
                labels: searchChartPayload.labels,
                datasets: [{
                    label: "Price ₹",
                    data: searchChartPayload.prices || [],
                    backgroundColor: "rgba(93, 62, 255, 0.55)",
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    const analysisSource = window.analysisChartData || {
        labels: ["W1", "W2", "W3", "W4", "W5", "W6"],
        priceSeries: [2710, 2780, 2822, 2891, 2910, 2920],
        dma50Series: [2660, 2690, 2728, 2762, 2810, 2866],
        symbol: "Price",
    };

    buildChart("analysisChart", {
        type: "line",
        data: {
            labels: analysisSource.labels,
            datasets: [
                { label: analysisSource.symbol + " Price", data: analysisSource.priceSeries, borderColor: "#00c2ff", tension: 0.3 },
                { label: "50 DMA", data: analysisSource.dma50Series, borderColor: "#7d71ff", tension: 0.3 },
            ],
        },
    });

    const gapSrc = window.analysisGapChartData || {};
    if (document.getElementById("analysisGapChart") && Array.isArray(gapSrc.labels) && gapSrc.labels.length) {
        const gaps = gapSrc.gaps || [];
        buildChart("analysisGapChart", {
            type: "bar",
            data: {
                labels: gapSrc.labels,
                datasets: [{
                    label: "Price − 50 DMA",
                    data: gaps,
                    backgroundColor: gaps.map((value) => (Number(value) >= 0 ? "#4adbc5" : "#ff8a8a")),
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    const compareSource = window.compareChartData || {
        labels: [],
        price_data: [],
        change_data: [],
    };

    if (Array.isArray(compareSource.labels) && compareSource.labels.length) {
        buildChart("compareChart", {
            type: "bar",
            data: {
                labels: compareSource.labels,
                datasets: [
                    { label: "Price", data: compareSource.price_data, backgroundColor: "#5d3eff" },
                    { label: "Daily Change %", data: compareSource.change_data, backgroundColor: "#00c2ff" },
                ],
            },
        });
    }

    const momentumSrc = window.compareMomentumChartData || {};
    if (document.getElementById("compareMomentumChart") && Array.isArray(momentumSrc.labels) && momentumSrc.labels.length) {
        const changes = momentumSrc.changes || [];
        buildChart("compareMomentumChart", {
            type: "bar",
            data: {
                labels: momentumSrc.labels,
                datasets: [{
                    label: "Daily change %",
                    data: changes,
                    backgroundColor: changes.map((value) => (Number(value) >= 0 ? "#4adbc5" : "#ff8a8a")),
                }],
            },
            options: {
                indexAxis: "y",
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: "rgba(24, 46, 92, 0.08)" } },
                    y: { grid: { display: false } },
                },
            },
        });
    }

    const allocationCanvas = document.getElementById("allocationChart");
    if (allocationCanvas) {
        const optSrc = window.optimizerChartData || {};
        const labels = Array.isArray(optSrc.labels) && optSrc.labels.length
            ? optSrc.labels
            : ["Large Cap", "IT", "Banking", "FMCG"];
        const percents = Array.isArray(optSrc.percents) && optSrc.percents.length
            ? optSrc.percents
            : [35, 30, 20, 15];
        const palette = ["#5d3eff", "#00c2ff", "#7f8dff", "#4adbc5", "#ffb347", "#ff6b9d", "#9b8cff"];
        const colors = labels.map((_, index) => palette[index % palette.length]);
        buildChart("allocationChart", {
            type: "pie",
            data: {
                labels,
                datasets: [{
                    data: percents,
                    backgroundColor: colors,
                }],
            },
            options: {
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                const value = ctx.raw;
                                return `${ctx.label}: ${value}%`;
                            },
                        },
                    },
                },
            },
        });
        if (document.getElementById("allocationBarChart")) {
            buildChart("allocationBarChart", {
                type: "bar",
                data: {
                    labels,
                    datasets: [{
                        label: "Weight %",
                        data: percents,
                        backgroundColor: colors,
                    }],
                },
                options: {
                    indexAxis: "y",
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { max: 100, grid: { color: "rgba(24, 46, 92, 0.08)" } },
                        y: { grid: { display: false } },
                    },
                },
            });
        }
        const radarCanvas = document.getElementById("allocationRadarChart");
        const radarSrc = window.optimizerRadarData || {};
        if (
            radarCanvas &&
            Array.isArray(radarSrc.labels) &&
            radarSrc.labels.length &&
            Array.isArray(radarSrc.values) &&
            radarSrc.values.length
        ) {
            const postureLabel = radarSrc.profile_label ? `${radarSrc.profile_label} posture` : "Risk posture";
            buildChart("allocationRadarChart", {
                type: "radar",
                data: {
                    labels: radarSrc.labels,
                    datasets: [{
                        label: postureLabel,
                        data: radarSrc.values,
                        borderColor: "#2159b3",
                        backgroundColor: "rgba(33, 89, 179, 0.16)",
                        pointBackgroundColor: "#5d3eff",
                        borderWidth: 2,
                    }],
                },
                options: {
                    scales: {
                        r: {
                            min: 0,
                            max: 100,
                            ticks: { stepSize: 25 },
                            grid: { color: "rgba(24, 46, 92, 0.12)" },
                            angleLines: { color: "rgba(24, 46, 92, 0.12)" },
                        },
                    },
                    plugins: {
                        legend: { display: true, position: "bottom" },
                        tooltip: {
                            callbacks: {
                                label(ctx) {
                                    return `${ctx.dataset.label}: ${ctx.raw}`;
                                },
                            },
                        },
                    },
                },
            });
        }
    }

    const mcCanvas = document.getElementById("allocationMcChart");
    const mcSrc = window.optimizerMcChartData || {};
    const mcPaths = Array.isArray(mcSrc.paths) ? mcSrc.paths : [];
    if (mcCanvas && mcPaths.length && Array.isArray(mcSrc.labels) && mcSrc.labels.length) {
        const mcPalette = ["#5d3eff", "#00c2ff", "#4adbc5"];
        buildChart("allocationMcChart", {
            type: "line",
            data: {
                labels: mcSrc.labels,
                datasets: mcPaths.map((path, index) => ({
                    label: path.label || `Path ${index + 1}`,
                    data: path.data || [],
                    borderColor: mcPalette[index % mcPalette.length],
                    backgroundColor: "transparent",
                    tension: 0.28,
                    pointRadius: 0,
                    borderWidth: 2,
                })),
            },
            options: {
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12 } },
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                const v = ctx.raw;
                                return `${ctx.dataset.label}: ${v}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: "Step (aligned to horizon length)" },
                        grid: { color: "rgba(24, 46, 92, 0.06)" },
                    },
                    y: {
                        title: { display: true, text: "Indexed level" },
                        grid: { color: "rgba(24, 46, 92, 0.08)" },
                    },
                },
            },
        });
    }
}

function initSidebarToggle() {
    const sidebar = document.getElementById("sidebar");
    const btn = document.getElementById("sidebarToggle");
    if (!sidebar || !btn) {
        return;
    }
    btn.addEventListener("click", function () {
        sidebar.classList.toggle("open");
    });
}

const SIDEBAR_COLLAPSED_STORAGE_KEY = "finpilot_sidebar_collapsed";

function initSidebarCollapse() {
    const sidebar = document.getElementById("sidebar");
    const collapseBtn = document.getElementById("sidebarCollapseBtn");
    if (!sidebar) {
        return;
    }
    if (!collapseBtn) {
        sidebar.classList.remove("sidebar--collapsed");
        sidebar.querySelectorAll("[data-nav-tip]").forEach(function (el) {
            el.removeAttribute("title");
        });
        return;
    }

    const mqDesktop = window.matchMedia("(min-width: 901px)");

    function syncCollapsedUi() {
        const collapsed = sidebar.classList.contains("sidebar--collapsed");
        const showTips = collapsed && mqDesktop.matches;
        sidebar.querySelectorAll("[data-nav-tip]").forEach(function (el) {
            const tip = el.getAttribute("data-nav-tip");
            if (showTips && tip) {
                el.setAttribute("title", tip);
            } else {
                el.removeAttribute("title");
            }
        });

        const expanded = !collapsed;
        collapseBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
        collapseBtn.title = collapsed ? "Expand sidebar" : "Minimize sidebar";
        const labelEl = collapseBtn.querySelector(".collapse-btn-label");
        if (labelEl) {
            labelEl.textContent = collapsed ? "Expand" : "Minimize";
        }
    }

    function applyDesktopCollapsedFromStorage() {
        if (!mqDesktop.matches) {
            sidebar.classList.remove("sidebar--collapsed");
            syncCollapsedUi();
            return;
        }
        if (localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "1") {
            sidebar.classList.add("sidebar--collapsed");
        } else {
            sidebar.classList.remove("sidebar--collapsed");
        }
        syncCollapsedUi();
    }

    collapseBtn.addEventListener("click", function () {
        if (!mqDesktop.matches) {
            return;
        }
        sidebar.classList.toggle("sidebar--collapsed");
        localStorage.setItem(
            SIDEBAR_COLLAPSED_STORAGE_KEY,
            sidebar.classList.contains("sidebar--collapsed") ? "1" : "0",
        );
        syncCollapsedUi();
    });

    if (typeof mqDesktop.addEventListener === "function") {
        mqDesktop.addEventListener("change", applyDesktopCollapsedFromStorage);
    } else if (typeof mqDesktop.addListener === "function") {
        mqDesktop.addListener(applyDesktopCollapsedFromStorage);
    }

    applyDesktopCollapsedFromStorage();
}

function initGlobalSearch() {
    const input = document.getElementById("globalSearchInput");
    const suggestionsBox = document.getElementById("globalSearchSuggestions");
    if (!input || !suggestionsBox) {
        return;
    }

    let controller = null;

    function hideSuggestions() {
        suggestionsBox.classList.add("d-none");
        suggestionsBox.innerHTML = "";
    }

    async function fetchSuggestions(query) {
        if (!query || query.length < 1) {
            hideSuggestions();
            return;
        }
        if (controller) {
            controller.abort();
        }
        controller = new AbortController();
        try {
            const response = await fetch(`/api/ds/trie?prefix=${encodeURIComponent(query.toUpperCase())}`, {
                signal: controller.signal,
            });
            const data = await response.json();
            const suggestions = (data.suggestions || []).slice(0, 6);
            if (!suggestions.length) {
                hideSuggestions();
                return;
            }
            suggestionsBox.innerHTML = "";
            suggestions.forEach((symbol) => {
                const link = document.createElement("a");
                link.href = `/search?q=${encodeURIComponent(symbol)}`;
                link.textContent = symbol;
                suggestionsBox.appendChild(link);
            });
            suggestionsBox.classList.remove("d-none");
        } catch (error) {
            hideSuggestions();
        }
    }

    input.addEventListener("input", function () {
        fetchSuggestions(input.value.trim());
    });
    input.addEventListener("focus", function () {
        if (input.value.trim()) {
            fetchSuggestions(input.value.trim());
        }
    });
    document.addEventListener("click", function (event) {
        if (!suggestionsBox.contains(event.target) && event.target !== input) {
            hideSuggestions();
        }
    });
}

document.addEventListener("DOMContentLoaded", function () {
    initCharts();
    initSidebarToggle();
    initSidebarCollapse();
    initGlobalSearch();
});
