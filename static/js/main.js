/* ============================================================
   TRICOFFEE INVENTORY MANAGEMENT SYSTEM — main.js
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initToasts();
  initDeleteModal();
});

/* ── Sidebar ─────────────────────────────────────────────────── */
function initSidebar() {
  const toggle  = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  if (!toggle || !sidebar || !overlay) return;

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    overlay.classList.toggle('open');
  });
  overlay.addEventListener('click', () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
  });
}

/* ── Toast auto-dismiss ──────────────────────────────────────── */
function initToasts() {
  document.querySelectorAll('.toast-msg').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .4s, transform .4s';
      el.style.opacity    = '0';
      el.style.transform  = 'translateX(100%)';
      setTimeout(() => el.remove(), 420);
    }, 4500);
  });
}

/* ── Delete confirm modal ────────────────────────────────────── */
function initDeleteModal() {
  // handled via confirmDelete() called inline
}

function confirmDelete(url, message) {
  const modal   = document.getElementById('deleteModal');
  const msgEl   = document.getElementById('deleteModalMsg');
  const formEl  = document.getElementById('deleteModalForm');
  if (!modal) return;
  msgEl.innerHTML = message || 'Are you sure? This cannot be undone.';
  formEl.action   = url;
  new bootstrap.Modal(modal).show();
}

/* ── Dashboard / Report Charts ───────────────────────────────── */
/**
 * @param {object}  statusData   { in_stock, low_stock, out_of_stock }
 * @param {object|null} categoryData { labels, ok, low, out }
 * @param {object|null} trendData    { labels, stock_in, stock_out, transfers }
 * @param {string}  [statusChartId='statusChart']
 */
function initDashboardCharts(statusData, categoryData, trendData, statusChartId) {
  const COFFEE  = '#5C3D2E';
  const CREAM   = '#FFF8E7';
  const GREEN   = '#27AE60';
  const ORANGE  = '#E67E22';
  const RED     = '#E74C3C';
  const BLUE    = '#2980B9';
  const defaultFont = { family: "'DM Sans', sans-serif", size: 11 };

  Chart.defaults.font = defaultFont;

  // ── Status Donut ──
  const statusCtx = document.getElementById(statusChartId || 'statusChart');
  if (statusCtx && statusData) {
    new Chart(statusCtx, {
      type: 'doughnut',
      data: {
        labels: ['In Stock', 'Low Stock', 'Out of Stock'],
        datasets: [{
          data: [statusData.in_stock, statusData.low_stock, statusData.out_of_stock],
          backgroundColor: [GREEN, ORANGE, RED],
          borderWidth: 0,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              padding: 16,
              usePointStyle: true,
              pointStyleWidth: 9,
              color: '#555',
            }
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.label}: ${ctx.parsed} items`
            }
          }
        }
      }
    });
  }

  // ── Category Stacked Bar ──
  const catCtx = document.getElementById('categoryChart');
  if (catCtx && categoryData) {
    new Chart(catCtx, {
      type: 'bar',
      data: {
        labels: categoryData.labels,
        datasets: [
          { label: 'In Stock',     data: categoryData.ok,  backgroundColor: 'rgba(39,174,96,.8)',  borderRadius: 3 },
          { label: 'Low Stock',    data: categoryData.low, backgroundColor: 'rgba(230,126,34,.8)', borderRadius: 3 },
          { label: 'Out of Stock', data: categoryData.out, backgroundColor: 'rgba(231,76,60,.8)',  borderRadius: 3 },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, pointStyleWidth: 9, color: '#555', padding: 16 }
          }
        },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: '#888' } },
          y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1, color: '#888' }, grid: { color: 'rgba(0,0,0,.04)' } }
        }
      }
    });
  }

  // ── 7-Day Trend Line ──
  const trendCtx = document.getElementById('trendChart');
  if (trendCtx && trendData) {
    new Chart(trendCtx, {
      type: 'line',
      data: {
        labels: trendData.labels,
        datasets: [
          {
            label: 'Stock In (Supplier)',
            data: trendData.stock_in,
            borderColor: GREEN,
            backgroundColor: 'rgba(39,174,96,.08)',
            tension: .4, fill: true, pointRadius: 3,
          },
          {
            label: 'Stock Out (Used)',
            data: trendData.stock_out,
            borderColor: RED,
            backgroundColor: 'rgba(231,76,60,.08)',
            tension: .4, fill: true, pointRadius: 3,
          },
          {
            label: 'Transfers to Area',
            data: trendData.transfers,
            borderColor: BLUE,
            backgroundColor: 'rgba(41,128,185,.08)',
            tension: .4, fill: true, pointRadius: 3,
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, pointStyleWidth: 9, color: '#555', padding: 16 }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#888' } },
          y: { beginAtZero: true,        ticks: { color: '#888' }, grid: { color: 'rgba(0,0,0,.04)' } }
        }
      }
    });
  }
}
