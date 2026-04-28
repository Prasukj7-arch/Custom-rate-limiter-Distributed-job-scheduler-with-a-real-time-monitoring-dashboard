const eventSource = new EventSource("http://127.0.0.1:8000/metrics/stream");
const ctx = document.getElementById("chart").getContext("2d");

// Styling the chart datasets
const gradientJob = ctx.createLinearGradient(0, 0, 0, 400);
gradientJob.addColorStop(0, 'rgba(56, 189, 248, 0.3)');
gradientJob.addColorStop(1, 'rgba(56, 189, 248, 0)');

const chart = new Chart(ctx, {
    type: "line",
    data: {
        labels: [],
        datasets: [
            {
                label: "Jobs Executed",
                data: [],
                borderColor: "#38bdf8",
                backgroundColor: gradientJob,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointRadius: 0
            },
            {
                label: "Failures",
                data: [],
                borderColor: "#f59e0b",
                borderDash: [5, 5],
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 0
            },
            {
                label: "Queue Backlog",
                data: [],
                borderColor: "#a855f7",
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 0
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: { intersect: false, mode: 'index' },
        scales: {
            x: { grid: { display: false }, ticks: { color: "#64748b" } },
            y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#64748b" }, beginAtZero: true }
        },
        plugins: {
            legend: {
                position: 'top',
                align: 'end',
                labels: { color: "#94a3b8", usePointStyle: true, pointStyle: 'circle', font: { weight: '600' } }
            },
            tooltip: { backgroundColor: '#0f172a', padding: 12 }
        }
    }
});

const alertBox = document.getElementById("alertBox");
const alertMsg = document.getElementById("alertMessage");
const connStatus = document.getElementById("connStatus");

eventSource.onopen = () => {
    connStatus.innerHTML = '<div class="status-dot"></div> CONTROL PLANE CONNECTED';
};

eventSource.onerror = () => {
    connStatus.style.color = "#ef4444";
    connStatus.innerHTML = '<div class="status-dot" style="background:#ef4444"></div> LINK INTERRUPTED';
};

eventSource.onmessage = function (event) {
    const data = JSON.parse(event.data);

    // Update UI Counters
    document.getElementById("allowed").innerText = data.allowed.toLocaleString();
    document.getElementById("blocked").innerText = data.blocked.toLocaleString();
    document.getElementById("processed").innerText = data.processed.toLocaleString();
    document.getElementById("failed").innerText = data.failed.toLocaleString();
    document.getElementById("queue").innerText = data.queue_depth.toLocaleString();

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Update Chart
    chart.data.labels.push(time);
    chart.data.datasets[0].data.push(data.processed);
    chart.data.datasets[1].data.push(data.failed);
    chart.data.datasets[2].data.push(data.queue_depth);

    if (chart.data.labels.length > 25) {
        chart.data.labels.shift();
        chart.data.datasets.forEach(d => d.data.shift());
    }

    chart.update('none');

    // ALERT LOGIC - Contextual for rate limiter/scheduler
    if (data.failed > 5) {
        showAlert("SYSTEM ALERT: Critical Job Execution Failures", "error");
    } else if (data.queue_depth > 10) {
        showAlert("SCHEDULER: Task queue depth exceeding threshold", "warning");
    } else if (data.blocked > 100) {
        showAlert("SECURITY: High volume of rate-limited traffic", "warning");
    } else {
        hideAlert();
    }
};

function showAlert(msg, type) {
    alertBox.className = `alert active ${type}`;
    alertMsg.innerText = msg;
    document.getElementById("alertIcon").innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
}

function hideAlert() {
    alertBox.classList.remove("active");
}
