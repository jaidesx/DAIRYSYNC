/* ================================
   DAIRYSYNC REAL-TIME MONITORING
   Location: static/dairysync/js/realtime.js

   Features:
     1. AJAX live dashboard stat cards (every 15s)
     2. Live alerts table update
     3. Browser Notification API for new alerts
     4. Temperature history chart (Chart.js line chart)
     5. Live fridge status indicators
     6. Connection status indicator
================================ */

(function () {
    'use strict';

    /* ── Config ─────────────────────────────────────────────── */
    const POLL_INTERVAL    = 15000;   // 15 seconds
    const STATS_URL        = '/api/v1/dashboard-stats/';
    const ALERT_COUNT_URL  = '/api/v1/alert-count/';
    const HISTORY_BASE_URL = '/api/v1/fridges/';

    let lastAlertId        = 0;
    let pollTimer          = null;
    let historyChart       = null;
    let isPolling          = false;


    /* ══════════════════════════════════════════════════════════
       1. LIVE DASHBOARD STATS — AJAX POLL
    ══════════════════════════════════════════════════════════ */

    async function fetchDashboardStats() {
        try {
            const res  = await fetch(STATS_URL, { credentials: 'same-origin' });
            if (!res.ok) throw new Error('Stats fetch failed');
            const data = await res.json();

            updateStatCards(data.stats);
            updateAlertsTable(data.recent_alerts);
            updateFridgeIndicators(data.fridges);
            checkForNewAlerts(data.stats.active_alerts, data.recent_alerts);
            setConnectionStatus(true);

        } catch (err) {
            console.warn('[DAIRYSYNC] Stats poll failed:', err);
            setConnectionStatus(false);
        }
    }

    function updateStatCards(stats) {
        const map = {
            'stat-total-fridges':   stats.total_fridges,
            'stat-online-fridges':  stats.online_fridges,
            'stat-offline-fridges': stats.offline_fridges,
            'stat-faulty-fridges':  stats.faulty_fridges,
            'stat-total-products':  stats.total_products,
            'stat-active-alerts':   stats.active_alerts,
            'stat-pending-orders':  stats.pending_orders,
        };

        Object.entries(map).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (!el) return;

            const current = parseInt(el.textContent);
            if (current !== value) {
                el.textContent = value;

                // Flash animation on change
                el.classList.remove('stat-flash');
                void el.offsetWidth; // force reflow
                el.classList.add('stat-flash');
            }
        });

        // Update alert badge in sidebar
        const badge = document.querySelector('.alert-badge');
        if (badge) {
            badge.textContent = stats.active_alerts;
            badge.style.display = stats.active_alerts > 0 ? 'inline-block' : 'none';
        }

        // Update card color classes based on value
        const alertCard = document.querySelector('[data-stat="active-alerts"]');
        if (alertCard) {
            alertCard.classList.toggle('card-danger', stats.active_alerts > 0);
        }

        const offlineCard = document.querySelector('[data-stat="offline-fridges"]');
        if (offlineCard) {
            offlineCard.classList.toggle('card-danger', stats.offline_fridges > 0);
        }
    }

    function updateAlertsTable(alerts) {
        const tbody = document.getElementById('recent-alerts-tbody');
        if (!tbody) return;

        if (alerts.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="empty-row">No active alerts — all systems normal</td>
                </tr>`;
            return;
        }

        const typeMap = {
            'high_temperature': '<span class="type-badge type-red">High Temp</span>',
            'low_stock':        '<span class="type-badge type-amber">Low Stock</span>',
            'door_open':        '<span class="type-badge type-blue">Door Open</span>',
            'power_fault':      '<span class="type-badge type-amber">Power Fault</span>',
        };

        tbody.innerHTML = alerts.map(alert => `
            <tr>
                <td><span class="code-tag">${alert.fridge__fridge_code}</span></td>
                <td>${typeMap[alert.alert_type] || `<span class="type-badge type-gray">${alert.alert_type}</span>`}</td>
                <td>${alert.message}</td>
                <td class="muted-text">${alert.created_at}</td>
            </tr>
        `).join('');
    }

    function updateFridgeIndicators(fridges) {
        fridges.forEach(fridge => {
            // Update status dot if present in page
            const dot = document.querySelector(`[data-fridge-status="${fridge.id}"]`);
            if (dot) {
                dot.className = fridge.status === 'online'
                    ? 'status-online'
                    : fridge.status === 'faulty'
                        ? 'status-warn'
                        : 'status-offline';
                dot.textContent = `● ${fridge.status.charAt(0).toUpperCase() + fridge.status.slice(1)}`;
            }

            // Update temperature display
            const tempEl = document.querySelector(`[data-fridge-temp="${fridge.id}"]`);
            if (tempEl) {
                tempEl.textContent = `${fridge.temperature} °C`;
            }
        });
    }


    /* ══════════════════════════════════════════════════════════
       2. BROWSER NOTIFICATIONS FOR NEW ALERTS
    ══════════════════════════════════════════════════════════ */

    function checkForNewAlerts(activeCount, alerts) {
        if (alerts.length === 0) return;

        const latestId = alerts[0].id;

        // First poll — just record the latest ID, don't notify
        if (lastAlertId === 0) {
            lastAlertId = latestId;
            return;
        }

        // New alert detected
        if (latestId > lastAlertId) {
            const newAlert = alerts[0];
            lastAlertId = latestId;

            // Toast notification (always)
            if (window.Toast) {
                const typeToast = {
                    high_temperature: () => Toast.error('High Temperature Alert', `${newAlert.fridge__fridge_code}: ${newAlert.message}`),
                    low_stock:        () => Toast.warning('Low Stock Alert',        `${newAlert.fridge__fridge_code}: ${newAlert.message}`),
                    door_open:        () => Toast.warning('Door Open Alert',        `${newAlert.fridge__fridge_code}: ${newAlert.message}`),
                    power_fault:      () => Toast.error('Power Fault Alert',       `${newAlert.fridge__fridge_code}: ${newAlert.message}`),
                };
                const toastFn = typeToast[newAlert.alert_type];
                if (toastFn) toastFn();
                else Toast.info('New Alert', newAlert.message);
            }

            // Browser push notification (if permission granted)
            sendBrowserNotification(
                `DAIRYSYNC Alert — ${newAlert.fridge__fridge_code}`,
                newAlert.message
            );
        }
    }

    function sendBrowserNotification(title, body) {
        if (!('Notification' in window)) return;

        if (Notification.permission === 'granted') {
            new Notification(title, {
                body,
                icon:  '/static/dairysync/images/synclogo.png',
                badge: '/static/dairysync/images/synclogo.png',
                tag:   'dairysync-alert',  // replaces previous notification with same tag
            });
        }
    }

    function requestNotificationPermission() {
        if (!('Notification' in window)) return;

        if (Notification.permission === 'default') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted' && window.Toast) {
                    Toast.success('Notifications enabled', 'You will be alerted when new issues are detected.');
                }
            });
        }
    }


    /* ══════════════════════════════════════════════════════════
       3. TEMPERATURE HISTORY CHART
    ══════════════════════════════════════════════════════════ */

    async function loadTemperatureHistory(fridgeId) {
        const canvas = document.getElementById('tempHistoryChart');
        if (!canvas) return;

        try {
            const res  = await fetch(`${HISTORY_BASE_URL}${fridgeId}/history/`, {
                credentials: 'same-origin'
            });
            if (!res.ok) throw new Error('History fetch failed');
            const data = await res.json();

            renderHistoryChart(canvas, data);

        } catch (err) {
            console.warn('[DAIRYSYNC] Temperature history fetch failed:', err);
        }
    }

    function renderHistoryChart(canvas, data) {
        const labels = data.readings.map(r => r.time);
        const temps  = data.readings.map(r => r.temperature);
        const humid  = data.readings.map(r => r.humidity);

        // Destroy old chart if it exists
        if (historyChart) {
            historyChart.destroy();
        }

        historyChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label:           'Temperature (°C)',
                        data:            temps,
                        borderColor:     '#2563eb',
                        backgroundColor: 'rgba(37,99,235,0.08)',
                        borderWidth:     2,
                        pointRadius:     3,
                        pointBackgroundColor: '#2563eb',
                        tension:         0.4,
                        fill:            true,
                        yAxisID:         'y',
                    },
                    {
                        label:           'Humidity (%)',
                        data:            humid,
                        borderColor:     '#0891b2',
                        backgroundColor: 'rgba(8,145,178,0.06)',
                        borderWidth:     2,
                        pointRadius:     3,
                        pointBackgroundColor: '#0891b2',
                        tension:         0.4,
                        fill:            false,
                        borderDash:      [4, 4],
                        yAxisID:         'y1',
                    },
                ],
            },
            options: {
                responsive:          true,
                maintainAspectRatio: false,
                interaction: {
                    mode:      'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        display:  true,
                        position: 'top',
                        labels: {
                            font:      { size: 12 },
                            color:     '#6b7280',
                            boxWidth:  12,
                            padding:   16,
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const unit = ctx.datasetIndex === 0 ? '°C' : '%';
                                return ` ${ctx.dataset.label}: ${ctx.raw}${unit}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid:  { display: false },
                        ticks: { color: '#9ca3af', font: { size: 11 } },
                    },
                    y: {
                        type:     'linear',
                        position: 'left',
                        title:    { display: true, text: '°C', color: '#6b7280' },
                        grid:     { color: 'rgba(0,0,0,0.05)' },
                        ticks:    { color: '#9ca3af', font: { size: 11 } },
                    },
                    y1: {
                        type:     'linear',
                        position: 'right',
                        title:    { display: true, text: '%', color: '#6b7280' },
                        grid:     { drawOnChartArea: false },
                        ticks:    { color: '#9ca3af', font: { size: 11 } },
                    },
                },
            },
        });

        // Update chart every poll cycle
        document.addEventListener('dairysync:stats-updated', async () => {
            const res  = await fetch(`${HISTORY_BASE_URL}${canvas.dataset.fridgeId}/history/`, {
                credentials: 'same-origin'
            });
            const data = await res.json();
            historyChart.data.labels                    = data.readings.map(r => r.time);
            historyChart.data.datasets[0].data          = data.readings.map(r => r.temperature);
            historyChart.data.datasets[1].data          = data.readings.map(r => r.humidity);
            historyChart.update('active');
        });
    }


    /* ══════════════════════════════════════════════════════════
       4. CONNECTION STATUS INDICATOR
    ══════════════════════════════════════════════════════════ */

    function setConnectionStatus(online) {
        const dot   = document.querySelector('.live-dot');
        const badge = document.querySelector('.live-badge');

        if (!dot || !badge) return;

        if (online) {
            dot.style.background   = '#16a34a';
            badge.style.background = '#dcfce7';
            badge.style.color      = '#166534';
            badge.childNodes[1]
                && (badge.childNodes[1].textContent = ' Live');
        } else {
            dot.style.background   = '#dc2626';
            badge.style.background = '#fee2e2';
            badge.style.color      = '#991b1b';
            badge.childNodes[1]
                && (badge.childNodes[1].textContent = ' Reconnecting...');
        }
    }


    /* ══════════════════════════════════════════════════════════
       5. POLLING LIFECYCLE
    ══════════════════════════════════════════════════════════ */

    function startPolling() {
        if (isPolling) return;
        isPolling = true;

        // Immediate first fetch
        fetchDashboardStats();

        // Then every 15 seconds
        pollTimer = setInterval(fetchDashboardStats, POLL_INTERVAL);
    }

    function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        isPolling = false;
    }

    // Pause when tab hidden, resume when visible (saves server load)
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopPolling();
        } else {
            startPolling();
            fetchDashboardStats(); // immediate refresh when tab becomes active
        }
    });


    /* ══════════════════════════════════════════════════════════
       6. INIT
    ══════════════════════════════════════════════════════════ */

    document.addEventListener('DOMContentLoaded', () => {

        // Only run on dashboard page
        const isDashboard = document.getElementById('stat-total-fridges');
        if (!isDashboard) return;

        // Request notification permission
        requestNotificationPermission();

        // Start live polling (replaces window.location.reload)
        startPolling();

        // Load temperature history chart if canvas exists
        const historyCanvas = document.getElementById('tempHistoryChart');
        if (historyCanvas) {
            const fridgeId = historyCanvas.dataset.fridgeId;
            if (fridgeId) loadTemperatureHistory(fridgeId);
        }

        // Notification permission button (if present)
        const notifBtn = document.getElementById('enable-notifications-btn');
        if (notifBtn) {
            notifBtn.addEventListener('click', requestNotificationPermission);
        }

    });

})();
