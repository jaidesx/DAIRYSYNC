/* ================================
   DAIRYSYNC MAIN JAVASCRIPT
   Location: static/dairysync/js/main.js
================================ */

function confirmDelete(message) {
    return confirm(message || "Are you sure you want to delete this record?");
}

function autoRefreshDashboard(seconds = 30) {
    setTimeout(function () {
        window.location.reload();
    }, seconds * 1000);
}
