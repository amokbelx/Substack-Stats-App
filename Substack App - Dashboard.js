const lastPull = DATA.current_pull || DATA.generated_at;
document.getElementById('updated-at').textContent = DATA.previous_pull
  ? `Last data pull: ${lastPull}  ·  Previous pull: ${DATA.previous_pull}`
  : `Last data pull: ${lastPull} (first pull recorded — run again later to see a previous date here)`;

document.getElementById('refreshBtn').addEventListener('click', () => {
  window.location.reload();
});

// ==================== CONTROL PANEL (only works when served by local_server.py) ====================
const API_BASE = window.location.origin.startsWith('http://localhost') || window.location.origin.startsWith('http://127.0.0.1')
  ? window.location.origin
  : null;

let statusPollTimer = null;

function cpSetButtonsDisabled(disabled) {
  document.querySelectorAll('.cp-btn').forEach(b => { b.disabled = disabled; });
}

function cpPollStatus() {
  fetch(`${API_BASE}/api/status`)
    .then(r => r.json())
    .then(data => {
      const statusEl = document.getElementById('controlPanelStatus');
      const logEl = document.getElementById('controlPanelLog');
      if (data.running) {
        statusEl.textContent = `Running: ${data.mode || 'pull'}…`;
        statusEl.className = 'control-panel-status running';
        cpSetButtonsDisabled(true);
      } else {
        const wasRunning = statusEl.dataset.wasRunning === 'true';
        statusEl.textContent = wasRunning
          ? 'Done — click "Refresh" above to see the new data.'
          : 'Idle.';
        statusEl.className = wasRunning ? 'control-panel-status done' : 'control-panel-status';
        cpSetButtonsDisabled(false);
        if (wasRunning && statusPollTimer) {
          clearInterval(statusPollTimer);
          statusPollTimer = null;
        }
      }
      statusEl.dataset.wasRunning = String(data.running);
      if (data.log && data.log.length > 0) {
        logEl.style.display = 'block';
        logEl.textContent = data.log.join(String.fromCharCode(10));
        logEl.scrollTop = logEl.scrollHeight;
      }
    })
    .catch(() => { /* server went away mid-poll — just stop trying */
      if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null; }
    });
}

function cpStartPull(mode, days) {
  const statusEl = document.getElementById('controlPanelStatus');
  statusEl.textContent = 'Starting…';
  statusEl.className = 'control-panel-status running';
  cpSetButtonsDisabled(true);

  fetch(`${API_BASE}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, days }),
  })
    .then(r => r.json())
    .then(result => {
      if (!result.started) {
        statusEl.textContent = result.message || 'Could not start.';
        statusEl.className = 'control-panel-status';
        cpSetButtonsDisabled(false);
        return;
      }
      if (statusPollTimer) clearInterval(statusPollTimer);
      statusPollTimer = setInterval(cpPollStatus, 1500);
      cpPollStatus();
    })
    .catch(() => {
      statusEl.textContent = 'Could not reach the local server.';
      statusEl.className = 'control-panel-status';
      cpSetButtonsDisabled(false);
    });
}

if (API_BASE) {
  fetch(`${API_BASE}/api/status`)
    .then(r => r.json())
    .then(() => {
      document.getElementById('controlPanel').style.display = 'block';
      document.querySelectorAll('.cp-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const mode = btn.dataset.mode;
          const days = btn.dataset.days ? parseInt(btn.dataset.days, 10) : undefined;
          cpStartPull(mode, days);
        });
      });
      cpPollStatus();
    })
    .catch(() => {
      document.getElementById('controlPanelOffline').style.display = 'block';
    });
} else {
  document.getElementById('controlPanelOffline').style.display = 'block';
}

// ==================== CONTENT STRATEGY PROMPT GENERATOR ====================
function generateStrategyPrompt() {
  const NL = String.fromCharCode(10);
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 30);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  const recentPosts = DATA.posts_table.filter(p => p.date >= cutoffStr);
  const recentNotes = DATA.notes_table.filter(n => n.date >= cutoffStr);

  const topPosts = [...recentPosts].sort((a, b) => b.views - a.views).slice(0, 5);
  const topNotes = [...recentNotes].sort((a, b) => b.reactions - a.reactions).slice(0, 5);

  const typeCounts = {};
  recentNotes.forEach(n => { typeCounts[n.type] = (typeCounts[n.type] || 0) + 1; });
  const typeSummary = Object.entries(typeCounts).map(([t, c]) => `${t}: ${c}`).join(', ') || 'no notes in this period';

  const lines = [];
  lines.push('I write a Substack newsletter. Below is my real performance data from the last 30 days. Before answering, please ask me to briefly describe my newsletter\'s topic and voice if you don\'t already know it from this conversation — then use that context together with the data below.');
  lines.push('');
  lines.push(`Here's my real performance data from the last 30 days (since ${cutoffStr}):`);
  lines.push('');
  lines.push('TOP POSTS BY VIEWS:');
  if (topPosts.length === 0) {
    lines.push('(No posts published in this period)');
  } else {
    topPosts.forEach((p, i) => {
      lines.push(`${i + 1}. "${p.title}" — ${p.views} views, ${p.opens} opens, ${p.likes} likes`);
    });
  }
  lines.push('');
  lines.push('TOP NOTES BY REACTIONS:');
  if (topNotes.length === 0) {
    lines.push('(No notes posted in this period)');
  } else {
    topNotes.forEach((n, i) => {
      lines.push(`${i + 1}. [${n.type}] "${n.body}" — ${n.reactions} reactions`);
    });
  }
  lines.push('');
  lines.push(`NOTES BY TYPE (last 30 days): ${typeSummary}`);
  lines.push('');
  lines.push('Based on this real data, please:');
  lines.push("1. Identify 2-3 patterns in what's actually resonating — be specific, cite the numbers.");
  lines.push("2. Suggest 3-5 concrete post or note ideas for the next 2-3 weeks, grounded in what's working.");
  lines.push('3. Give me 3-5 reflective prompts or questions I could sit with to surface a real story-driven post — a specific situation with a decision point — not abstract topics.');

  return lines.join(NL);
}

document.getElementById('strategyBtn').addEventListener('click', async () => {
  const statusEl = document.getElementById('strategyStatus');
  const prompt = generateStrategyPrompt();
  try {
    await navigator.clipboard.writeText(prompt);
    statusEl.textContent = 'Copied! Paste into a new Claude conversation.';
    statusEl.className = 'control-panel-status done';
  } catch (e) {
    statusEl.textContent = 'Could not copy to clipboard — check the browser console for the prompt text.';
    statusEl.className = 'control-panel-status';
    console.log(prompt);
  }
});

const CHART_COLORS = { teal: '#2F4A47', tealSoft: 'rgba(47,74,71,0.15)', amber: '#C98B3B', amberSoft: 'rgba(201,139,59,0.15)' };
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color = '#4B564F';

// --- Trend chart helper (need 2+ runs to be meaningful) ---
function renderTrend(cardId, canvasId, labels, datasets, title, emptyMsg) {
  const card = document.getElementById(cardId);
  if (labels.length < 2) {
    card.innerHTML = `<p class="no-trend">${emptyMsg}</p>`;
    return;
  }
  new Chart(document.getElementById(canvasId), {
    type: 'line',
    data: { labels: labels.map(l => l.slice(0, 16)), datasets },
    options: {
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: title, font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
    }
  });
}

// --- Sortable, filterable table helper ---
const MONTH_NAMES = ['January','February','March','April','May','June','July',
                      'August','September','October','November','December'];

// ==================== DETAIL MODAL (click a post/note row to drill down) ====================
let modalChartInstance = null;

function closeModal() {
  document.getElementById('detailModal').classList.remove('open');
  if (modalChartInstance) { modalChartInstance.destroy(); modalChartInstance = null; }
}

document.getElementById('modalClose').addEventListener('click', closeModal);
document.getElementById('detailModal').addEventListener('click', (e) => {
  if (e.target.id === 'detailModal') closeModal(); // click outside the card closes it
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

function openDetailModal(title, historyRows, datasetDefs, trafficCategories) {
  document.getElementById('modalTitle').textContent = title;
  const subtitleEl = document.getElementById('modalSubtitle');

  if (!historyRows || historyRows.length === 0) {
    subtitleEl.textContent = 'No history recorded for this yet.';
    document.getElementById('modalChart').style.display = 'none';
  } else {
    document.getElementById('modalChart').style.display = 'block';
    subtitleEl.textContent = historyRows.length === 1
      ? 'Only one snapshot so far — run the pull script again later to start building a real trend.'
      : `${historyRows.length} snapshots recorded.`;

    if (modalChartInstance) modalChartInstance.destroy();
    modalChartInstance = new Chart(document.getElementById('modalChart'), {
      type: 'line',
      data: {
        labels: historyRows.map(r => r.run_timestamp.slice(0, 16)),
        datasets: datasetDefs.map(d => ({
          label: d.label,
          data: historyRows.map(r => r[d.key] || 0),
          borderColor: d.color,
          backgroundColor: d.colorSoft,
          fill: false,
          tension: 0.25,
        })),
      },
      options: {
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } },
        plugins: { legend: { display: datasetDefs.length > 1 } },
      },
    });
  }

  const trafficSection = document.getElementById('modalTrafficSection');
  if (trafficCategories && Object.keys(trafficCategories).length > 0) {
    trafficSection.style.display = 'block';
    const entries = Object.entries(trafficCategories).sort((a, b) => b[1] - a[1]);
    const tbody = document.querySelector('#modalTrafficTable tbody');
    tbody.innerHTML = entries.map(([source, views]) =>
      `<tr><td>${source}</td><td class="num">${views}</td></tr>`
    ).join('');
  } else {
    trafficSection.style.display = 'none';
  }

  document.getElementById('detailModal').classList.add('open');
}

function openPostDetail(postId, title) {
  const history = DATA.post_history[postId] || [];
  const traffic = DATA.post_traffic_by_id[postId];
  openDetailModal(title || `Post ${postId}`, history, [
    { key: 'views', label: 'Views', color: CHART_COLORS.teal, colorSoft: CHART_COLORS.tealSoft },
    { key: 'opens', label: 'Opens', color: CHART_COLORS.amber, colorSoft: CHART_COLORS.amberSoft },
  ], traffic);
}

function openNoteDetail(noteId, bodyPreview) {
  const history = DATA.note_history[noteId] || [];
  openDetailModal(bodyPreview || `Note ${noteId}`, history, [
    { key: 'reactions', label: 'Reactions', color: CHART_COLORS.amber, colorSoft: CHART_COLORS.amberSoft },
    { key: 'impressions', label: 'Impressions', color: CHART_COLORS.teal, colorSoft: CHART_COLORS.tealSoft },
  ], null);
}

function makeTable(tableId, filterId, rows, columns, groupByMonthKey, idKey, labelKey, onRowClick, monthTabsId, linkKey) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  let sortKey = null, sortDir = 1;
  let filterText = '';
  let activeYear = null;     // null = "All years"
  let activeMonthNum = null; // null = "All months" (within activeYear, if set)
  const collapsedMonths = new Set();

  function monthLabel(yyyymm) {
    const parts = yyyymm.split('-');
    if (parts.length !== 2) return 'Unknown date';
    const monthName = MONTH_NAMES[parseInt(parts[1], 10) - 1] || parts[1];
    return `${monthName} ${parts[0]}`;
  }

  function escapeAttr(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  }

  function renderRow(r) {
    const idAttr = idKey ? ` data-id="${escapeAttr(r[idKey])}"` : '';
    const labelAttr = labelKey ? ` data-label="${escapeAttr(r[labelKey])}"` : '';
    return `<tr${idAttr}${labelAttr}>` + columns.map((c, i) => {
      const val = r[c];
      const isNum = typeof val === 'number';
      let cellContent = val;
      // Link icon goes in the first column (the title/label column),
      // only if this row actually has a URL. Placed before the text.
      if (i === 0 && linkKey && r[linkKey]) {
        const linkIconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>';
        cellContent = `<a href="${escapeAttr(r[linkKey])}" target="_blank" rel="noopener" class="row-link-icon" title="Open on Substack">${linkIconSvg}</a>${val}`;
      }
      return `<td class="${isNum ? 'num' : ''}">${cellContent}</td>`;
    }).join('') + '</tr>';
  }

  function render() {
    let data = rows.filter(r => JSON.stringify(r).toLowerCase().includes(filterText.toLowerCase()));

    if (activeYear) {
      data = data.filter(r => (r[groupByMonthKey] || '').slice(0, 4) === activeYear);
      if (activeMonthNum) {
        data = data.filter(r => (r[groupByMonthKey] || '').slice(5, 7) === activeMonthNum);
      }
    }

    if (sortKey) {
      data = [...data].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
        return String(av).localeCompare(String(bv)) * sortDir;
      });
    }

    // Group into collapsible month sections whenever more than one month
    // could be showing — i.e. everything except the "specific year AND
    // specific month" case, which is already a single flat month. Sorting
    // by anything besides the date field also breaks out of grouping,
    // since the row order no longer makes chronological sense.
    const singleMonthSelected = activeYear && activeMonthNum;
    const shouldGroup = !singleMonthSelected && groupByMonthKey && (!sortKey || sortKey === groupByMonthKey);

    if (!shouldGroup) {
      tbody.innerHTML = data.map(renderRow).join('');
      return;
    }

    const groups = {};
    const order = [];
    data.forEach(r => {
      const key = (r[groupByMonthKey] || '').slice(0, 7) || 'unknown';
      if (!groups[key]) { groups[key] = []; order.push(key); }
      groups[key].push(r);
    });
    order.sort((a, b) => b.localeCompare(a)); // newest month first

    let html = '';
    order.forEach(key => {
      const groupRows = groups[key];
      const collapsed = collapsedMonths.has(key);
      html += `<tr class="month-header" data-month="${key}">
        <td colspan="${columns.length}">
          <span class="month-toggle">${collapsed ? '▶' : '▼'}</span>
          ${monthLabel(key)} <span class="month-count">(${groupRows.length})</span>
        </td>
      </tr>`;
      if (!collapsed) {
        html += groupRows.map(renderRow).join('');
      }
    });
    tbody.innerHTML = html;

    tbody.querySelectorAll('.month-header').forEach(row => {
      row.addEventListener('click', () => {
        const key = row.dataset.month;
        if (collapsedMonths.has(key)) collapsedMonths.delete(key); else collapsedMonths.add(key);
        render();
      });
    });
  }

  document.querySelectorAll(`#${tableId} th`).forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      sortDir = (sortKey === key) ? -sortDir : 1;
      sortKey = key;
      document.querySelectorAll(`#${tableId} th .arrow`).forEach(a => a.remove());
      th.innerHTML += `<span class="arrow">${sortDir === 1 ? '▲' : '▼'}</span>`;
      render();
    });
  });

  document.getElementById(filterId).addEventListener('input', (e) => {
    filterText = e.target.value;
    render();
  });

  // Row-click drill-down — attached once to the tbody itself (event
  // delegation), so it keeps working across re-renders even though
  // render() replaces all the actual <tr> elements each time.
  if (onRowClick) {
    tbody.addEventListener('click', (e) => {
      if (e.target.closest('.row-link-icon')) return; // let the Substack link navigate normally
      const tr = e.target.closest('tr');
      if (!tr || tr.classList.contains('month-header')) return;
      const id = tr.dataset.id;
      if (id !== undefined && id !== '' && id !== 'undefined') {
        onRowClick(id, tr.dataset.label || '');
      }
    });
  }

  // Optional expand-all / collapse-all buttons, if present for this table
  const expandBtn = document.getElementById(`${tableId}ExpandAll`);
  const collapseBtn = document.getElementById(`${tableId}CollapseAll`);
  if (expandBtn) expandBtn.addEventListener('click', () => { collapsedMonths.clear(); render(); });
  if (collapseBtn) collapseBtn.addEventListener('click', () => {
    rows.forEach(r => collapsedMonths.add((r[groupByMonthKey] || '').slice(0, 7) || 'unknown'));
    render();
  });

  // Year/Month dropdown filter — options are built strictly from dates
  // actually present in the data, so there's no way to select a year or
  // month with zero entries, past or future.
  if (monthTabsId && groupByMonthKey) {
    const tabsContainer = document.getElementById(monthTabsId);
    if (tabsContainer) {
      const yearToMonths = {};
      rows.forEach(r => {
        const full = (r[groupByMonthKey] || '').slice(0, 7);
        if (!full || full.length !== 7) return;
        const year = full.slice(0, 4);
        const monthNum = full.slice(5, 7);
        if (!yearToMonths[year]) yearToMonths[year] = new Set();
        yearToMonths[year].add(monthNum);
      });
      const years = Object.keys(yearToMonths).sort((a, b) => b.localeCompare(a)); // newest first

      function renderFilterUI() {
        const yearOptions = ['<option value="">All</option>'].concat(
          years.map(y => `<option value="${y}"${activeYear === y ? ' selected' : ''}>${y}</option>`)
        ).join('');

        let monthOptions = '<option value="">All</option>';
        if (activeYear && yearToMonths[activeYear]) {
          const monthsForYear = [...yearToMonths[activeYear]].sort((a, b) => b.localeCompare(a));
          monthOptions += monthsForYear.map(m => {
            const label = MONTH_NAMES[parseInt(m, 10) - 1] || m;
            return `<option value="${m}"${activeMonthNum === m ? ' selected' : ''}>${label}</option>`;
          }).join('');
        }

        tabsContainer.innerHTML = `
          <div class="month-filter-row">
            <label class="filter-label">Year
              <select class="year-select">${yearOptions}</select>
            </label>
            <label class="filter-label">Month
              <select class="month-select"${activeYear ? '' : ' disabled'}>${monthOptions}</select>
            </label>
          </div>
        `;

        tabsContainer.querySelector('.year-select').addEventListener('change', (e) => {
          activeYear = e.target.value || null;
          activeMonthNum = null; // reset month whenever the year changes
          renderFilterUI();
          render();
        });
        tabsContainer.querySelector('.month-select').addEventListener('change', (e) => {
          activeMonthNum = e.target.value || null;
          render();
        });
      }
      renderFilterUI();
    }
  }

  render();
}

// ==================== POSTS TAB (built immediately — visible by default) ====================
document.getElementById('posts-kpi-row').innerHTML = [
  [DATA.kpis.total_posts, 'Posts'],
  [DATA.kpis.total_views.toLocaleString(), 'Total views'],
  [DATA.kpis.avg_open_rate + '%', 'Avg open rate'],
  [DATA.kpis.total_own_opens.toLocaleString(), 'Your own opens'],
].map(([val, label]) =>
  `<div class="kpi"><div class="kpi-value">${val}</div><div class="kpi-label">${label}</div></div>`
).join('');

new Chart(document.getElementById('topPostsChart'), {
  type: 'bar',
  data: {
    labels: DATA.top_posts_chart.labels,
    datasets: [{ label: 'Views', data: DATA.top_posts_chart.views, backgroundColor: CHART_COLORS.teal, borderRadius: 3, maxBarThickness: 22 }]
  },
  options: {
    indexAxis: 'y',
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, title: { display: true, text: 'Top 10 posts by views', font: { size: 13, weight: '600' } } },
    scales: { x: { grid: { color: '#E6EAE4' } }, y: { grid: { display: false } } }
  }
});

new Chart(document.getElementById('topPostsOpensChart'), {
  type: 'bar',
  data: {
    labels: DATA.top_posts_opens_chart.labels,
    datasets: [{ label: 'Opens', data: DATA.top_posts_opens_chart.opens, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 22 }]
  },
  options: {
    indexAxis: 'y',
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, title: { display: true, text: 'Top 10 posts by opens', font: { size: 13, weight: '600' } } },
    scales: { x: { grid: { color: '#E6EAE4' } }, y: { grid: { display: false } } }
  }
});

const overallTrafficLabels = DATA.overall_traffic_chart.labels;
const overallTrafficViews = DATA.overall_traffic_chart.views;
if (overallTrafficLabels.length === 0) {
  document.querySelector('#overallTrafficTable').outerHTML =
    '<p class="no-trend">No traffic-source data found yet — run a real pull to check whether this endpoint works for your account.</p>';
} else {
  const totalViews = overallTrafficViews.reduce((sum, v) => sum + v, 0);
  const tbody = document.querySelector('#overallTrafficTable tbody');
  tbody.innerHTML = overallTrafficLabels.map((label, i) => {
    const views = overallTrafficViews[i];
    const pct = totalViews > 0 ? ((views / totalViews) * 100).toFixed(1) : '0.0';
    return `<tr><td>${label}</td><td class="num">${views}</td><td class="num">${pct}%</td></tr>`;
  }).join('');
}

const postsActivityCard = document.getElementById('postsViewsByMonthChart').closest('.chart-card');
if (DATA.posts_activity_by_month.labels.length === 0) {
  postsActivityCard.innerHTML = '<p class="no-trend">No dated posts found.</p>';
} else {
  new Chart(document.getElementById('postsViewsByMonthChart'), {
    type: 'bar',
    data: {
      labels: DATA.posts_activity_by_month.labels,
      datasets: [{ label: 'Views', data: DATA.posts_activity_by_month.views, backgroundColor: CHART_COLORS.teal, borderRadius: 3, maxBarThickness: 40 }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'Views by month published', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
    }
  });

  new Chart(document.getElementById('postsOpensByMonthChart'), {
    type: 'bar',
    data: {
      labels: DATA.posts_activity_by_month.labels,
      datasets: [{ label: 'Opens', data: DATA.posts_activity_by_month.opens, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 40 }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'Opens by month published', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
    }
  });
}

makeTable('postsTable', 'postsFilter', DATA.posts_table,
  ['title', 'date', 'views', 'opens', 'open_rate', 'your_own_opens', 'likes', 'comments', 'restacks'],
  'date', 'post_id', 'title', (id, label) => openPostDetail(id, label), 'postsMonthTabs', 'url');

// ==================== NOTES TAB (built lazily — first time the tab is opened) ====================
// Chart.js can't correctly size a chart drawn into a hidden (display:none)
// canvas, so notes charts are built the first time you actually click the
// Notes tab rather than immediately on page load.
let notesTabBuilt = false;
function buildNotesTab() {
  if (notesTabBuilt) return;
  notesTabBuilt = true;

  document.getElementById('notes-kpi-row').innerHTML = [
    [DATA.kpis.total_notes, 'Notes'],
    [DATA.kpis.total_impressions.toLocaleString(), 'Total impressions'],
    [DATA.kpis.total_reactions.toLocaleString(), 'Total reactions'],
    [DATA.kpis.avg_reactions, 'Avg reactions / note'],
  ].map(([val, label]) =>
    `<div class="kpi"><div class="kpi-value">${val}</div><div class="kpi-label">${label}</div></div>`
  ).join('');

  new Chart(document.getElementById('topNotesChart'), {
    type: 'bar',
    data: {
      labels: DATA.top_notes_chart.labels,
      datasets: [{ label: 'Reactions', data: DATA.top_notes_chart.reactions, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 22 }]
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'Top 10 notes by reactions', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { color: '#E6EAE4' } }, y: { grid: { display: false } } }
    }
  });

  new Chart(document.getElementById('topNotesImpressionsChart'), {
    type: 'bar',
    data: {
      labels: DATA.top_notes_impressions_chart.labels,
      datasets: [{ label: 'Impressions', data: DATA.top_notes_impressions_chart.impressions, backgroundColor: CHART_COLORS.teal, borderRadius: 3, maxBarThickness: 22 }]
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'Top 10 notes by impressions', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { color: '#E6EAE4' } }, y: { grid: { display: false } } }
    }
  });

  const activityCard = document.getElementById('notesReactionsByMonthChart').closest('.chart-card');
  if (DATA.notes_activity_by_month.labels.length === 0) {
    activityCard.innerHTML = '<p class="no-trend">No dated notes found.</p>';
  } else {
    new Chart(document.getElementById('notesReactionsByMonthChart'), {
      type: 'bar',
      data: {
        labels: DATA.notes_activity_by_month.labels,
        datasets: [{ label: 'Reactions', data: DATA.notes_activity_by_month.reactions, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 40 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, title: { display: true, text: 'Reactions by month posted', font: { size: 13, weight: '600' } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
      }
    });

    new Chart(document.getElementById('notesImpressionsByMonthChart'), {
      type: 'bar',
      data: {
        labels: DATA.notes_activity_by_month.labels,
        datasets: [{ label: 'Impressions', data: DATA.notes_activity_by_month.impressions, backgroundColor: CHART_COLORS.teal, borderRadius: 3, maxBarThickness: 40 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, title: { display: true, text: 'Impressions by month posted', font: { size: 13, weight: '600' } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
      }
    });
  }

  new Chart(document.getElementById('notesByTypeCountChart'), {
    type: 'bar',
    data: {
      labels: DATA.notes_by_type.labels,
      datasets: [{ label: 'Notes', data: DATA.notes_by_type.counts, backgroundColor: CHART_COLORS.teal, borderRadius: 3, maxBarThickness: 40 }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'How many of each type', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
    }
  });

  new Chart(document.getElementById('notesByTypeReactionsChart'), {
    type: 'bar',
    data: {
      labels: DATA.notes_by_type.labels,
      datasets: [{ label: 'Avg reactions', data: DATA.notes_by_type.avg_reactions, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 40 }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: 'Average reactions per note, by type', font: { size: 13, weight: '600' } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
    }
  });

  makeTable('notesTable', 'notesFilter', DATA.notes_table,
    ['date', 'body', 'type', 'impressions', 'reactions', 'restacks', 'replies'], 'date',
    'note_id', 'body', (id, label) => openNoteDetail(id, label), 'notesMonthTabs');
}

// ==================== SUBSCRIBERS TAB (built lazily) ====================
let subscribersTabBuilt = false;
function buildSubscribersTab() {
  if (subscribersTabBuilt) return;
  subscribersTabBuilt = true;

  document.getElementById('subscribers-kpi-row').innerHTML = [
    [DATA.kpis.total_subscribers.toLocaleString(), 'Total subscribers'],
    [DATA.kpis.founding_count, 'Founding'],
    [DATA.kpis.paid_count, 'Paid'],
    [DATA.kpis.comp_count, 'Comp'],
    [DATA.kpis.gift_count, 'Gift'],
    [DATA.kpis.avg_activity, 'Avg activity rating'],
  ].map(([val, label]) =>
    `<div class="kpi"><div class="kpi-value">${val}</div><div class="kpi-label">${label}</div></div>`
  ).join('');

  const growthCard = document.getElementById('subscriberCumulativeChart').closest('.chart-card');
  if (DATA.subscriber_growth.labels.length === 0) {
    growthCard.innerHTML = '<p class="no-trend">No signup dates found in the subscriber data.</p>';
  } else {
    new Chart(document.getElementById('subscriberCumulativeChart'), {
      type: 'line',
      data: {
        labels: DATA.subscriber_growth.labels,
        datasets: [{ label: 'Cumulative subscribers', data: DATA.subscriber_growth.cumulative,
                     borderColor: CHART_COLORS.teal, backgroundColor: CHART_COLORS.tealSoft, fill: true, tension: 0.25 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { title: { display: true, text: 'Cumulative subscribers by month', font: { size: 13, weight: '600' } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
      }
    });

    new Chart(document.getElementById('subscriberNewChart'), {
      type: 'bar',
      data: {
        labels: DATA.subscriber_growth.labels,
        datasets: [{ label: 'New subscribers', data: DATA.subscriber_growth.new, backgroundColor: CHART_COLORS.amber, borderRadius: 3, maxBarThickness: 40 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, title: { display: true, text: 'New subscribers by month', font: { size: 13, weight: '600' } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#E6EAE4' } } }
      }
    });
  }

  makeTable('subscribersTable', 'subscribersFilter', DATA.subscribers_table,
    ['date', 'name', 'email', 'type', 'interval', 'activity_rating', 'revenue'], 'date',
    null, null, null, 'subscribersMonthTabs');
}

// ==================== LOG TAB (built lazily) ====================
let logTabBuilt = false;
function buildLogTab() {
  if (logTabBuilt) return;
  logTabBuilt = true;

  const log = DATA.pull_log_table;
  const totalPulls = log.length;
  const mostRecent = totalPulls > 0 ? log[0].timestamp : '—';
  const firstPull = totalPulls > 0 ? log[log.length - 1].timestamp : '—';

  document.getElementById('log-kpi-row').innerHTML = [
    [totalPulls, 'Total pulls recorded'],
    [mostRecent, 'Most recent pull'],
    [firstPull, 'First pull recorded'],
  ].map(([val, label]) =>
    `<div class="kpi"><div class="kpi-value" style="font-size:20px;">${val}</div><div class="kpi-label">${label}</div></div>`
  ).join('');

  makeTable('logTable', 'logFilter', log,
    ['timestamp', 'posts', 'notes', 'subscribers'], 'date',
    null, null, null, 'logMonthTabs');
}

// ==================== COMMENTS TAB (built lazily) ====================
let commentsTabBuilt = false;
function buildCommentsTab() {
  if (commentsTabBuilt) return;
  commentsTabBuilt = true;

  const comments = DATA.comments_table;
  const totalComments = comments.length;
  const uniquePosts = new Set(comments.map(c => c.post_title)).size;
  const totalReactions = comments.reduce((sum, c) => sum + (c.reactions || 0), 0);
  const avgReactions = totalComments > 0 ? (totalReactions / totalComments).toFixed(1) : '0';

  document.getElementById('comments-kpi-row').innerHTML = [
    [totalComments, 'Total comments'],
    [uniquePosts, 'Posts with comments'],
    [avgReactions, 'Avg reactions / comment'],
  ].map(([val, label]) =>
    `<div class="kpi"><div class="kpi-value" style="font-size:20px;">${val}</div><div class="kpi-label">${label}</div></div>`
  ).join('');

  makeTable('commentsTable', 'commentsFilter', comments,
    ['post_title', 'date', 'commenter_name', 'body', 'reactions', 'replies'], 'date',
    null, 'post_title', null, 'commentsMonthTabs', 'url');
}

// ==================== SCHEDULE TAB ====================
const SCHEDULE_MAX_CHARS = 3000;
let scheduleState = {
  notes: [],
  settings: { dry_run: true, daily_max: 10 },
  scheduler_running: false,
  auth_blocked: false,
  warning: '',
  max_text_length: SCHEDULE_MAX_CHARS,
  viewYear: null,
  viewMonth: null, // 0-indexed
  pollTimer: null,
};
let scheduleListenersBound = false;

function localTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (e) {
    return 'UTC';
  }
}

function ensureScheduleTab() {
  const nav = document.querySelector('.tab-nav');
  if (!nav) return;
  if (!nav.querySelector('[data-tab="schedule"]')) {
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = 'schedule';
    btn.textContent = 'Schedule';
    const logBtn = nav.querySelector('[data-tab="log"]');
    if (logBtn) nav.insertBefore(btn, logBtn);
    else nav.appendChild(btn);
  }
  if (!document.getElementById('tab-schedule')) {
    const panel = document.createElement('div');
    panel.className = 'tab-panel';
    panel.id = 'tab-schedule';
    panel.innerHTML = '<div id="scheduleRoot"></div>';
    const main = document.querySelector('main');
    if (main) main.appendChild(panel);
  }
  if (!document.getElementById('scheduleFormOverlay')) {
    const overlay = document.createElement('div');
    overlay.className = 'schedule-form-overlay';
    overlay.id = 'scheduleFormOverlay';
    overlay.innerHTML = `
      <div class="schedule-form" role="dialog" aria-modal="true" aria-labelledby="scheduleFormTitle">
        <h3 id="scheduleFormTitle">Schedule a Note</h3>
        <label for="scheduleText">Note text</label>
        <textarea id="scheduleText" maxlength="${SCHEDULE_MAX_CHARS}" placeholder="Write your Note…"></textarea>
        <div class="schedule-charcount" id="scheduleCharCount">0 / ${SCHEDULE_MAX_CHARS}</div>
        <div class="schedule-form-row">
          <div>
            <label for="scheduleDate">Date</label>
            <input type="date" id="scheduleDate">
          </div>
          <div>
            <label for="scheduleTime">Time</label>
            <input type="time" id="scheduleTime">
          </div>
        </div>
        <label for="scheduleTz">Timezone</label>
        <input type="text" id="scheduleTz" placeholder="America/New_York">
        <p class="no-trend" style="padding:8px 0 0;margin:0;">Uses your computer's local timezone by default. Change only if you know the IANA name (e.g. Europe/London).</p>
        <input type="hidden" id="scheduleEditId" value="">
        <div class="schedule-form-actions">
          <button type="button" class="text-btn" id="scheduleFormCancel">Cancel</button>
          <button type="button" class="cp-btn" id="scheduleFormSave">Save</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
  }
}

function scheduleEscape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function scheduleStatusLabel(note) {
  if (note.status === 'posted' && note.dry_run_post) return 'posted (dry run)';
  return note.status || 'unknown';
}

function scheduleFormatWhen(iso, tz) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      timeZone: tz || undefined,
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch (e) {
    return iso;
  }
}

function scheduleYmdInTz(iso, tz) {
  try {
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz || localTimezone(),
      year: 'numeric', month: '2-digit', day: '2-digit',
    });
    return fmt.format(new Date(iso)); // YYYY-MM-DD
  } catch (e) {
    return (iso || '').slice(0, 10);
  }
}

function scheduleBuildLocalIso(dateStr, timeStr, tzName) {
  // Build a timezone-aware ISO string for the chosen local wall time.
  // We compute the offset for that timezone at that approximate UTC instant.
  const [y, m, d] = dateStr.split('-').map(Number);
  const [hh, mm] = (timeStr || '09:00').split(':').map(Number);
  const probe = new Date(Date.UTC(y, m - 1, d, hh, mm, 0));
  let offsetMin = 0;
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tzName,
      timeZoneName: 'shortOffset',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(probe);
    const tzPart = parts.find(p => p.type === 'timeZoneName');
    const match = tzPart && tzPart.value.match(/GMT([+-])(\d{1,2})(?::?(\d{2}))?/);
    if (match) {
      const sign = match[1] === '-' ? -1 : 1;
      offsetMin = sign * (parseInt(match[2], 10) * 60 + parseInt(match[3] || '0', 10));
    } else {
      // Fallback: difference between locale strings
      const asUTC = new Date(probe.toLocaleString('en-US', { timeZone: 'UTC' }));
      const asTZ = new Date(probe.toLocaleString('en-US', { timeZone: tzName }));
      offsetMin = Math.round((asTZ - asUTC) / 60000);
    }
  } catch (e) {
    offsetMin = -new Date().getTimezoneOffset();
  }
  // Wall time in tz = UTC + offset => UTC = wall - offset
  const utcMs = Date.UTC(y, m - 1, d, hh, mm, 0) - offsetMin * 60000;
  const dt = new Date(utcMs);
  const sign = offsetMin >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMin);
  const oh = String(Math.floor(abs / 60)).padStart(2, '0');
  const om = String(abs % 60).padStart(2, '0');
  const isoLocal = `${dateStr}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00${sign}${oh}:${om}`;
  // Prefer the constructed offset form; validate
  void dt;
  return isoLocal;
}

async function scheduleFetch() {
  if (!API_BASE) throw new Error('Schedule needs the local server (Start Server.bat).');
  const r = await fetch(`${API_BASE}/api/schedule`);
  if (!r.ok) throw new Error('Could not load schedule');
  return r.json();
}

async function scheduleApi(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(`${API_BASE}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.ok === false) {
    throw new Error(data.error || `Request failed (${r.status})`);
  }
  return data;
}

function scheduleOpenForm(prefill) {
  ensureScheduleTab();
  const overlay = document.getElementById('scheduleFormOverlay');
  const title = document.getElementById('scheduleFormTitle');
  const textEl = document.getElementById('scheduleText');
  const dateEl = document.getElementById('scheduleDate');
  const timeEl = document.getElementById('scheduleTime');
  const tzEl = document.getElementById('scheduleTz');
  const idEl = document.getElementById('scheduleEditId');
  const tz = (prefill && prefill.timezone) || localTimezone();
  tzEl.value = tz;
  idEl.value = (prefill && prefill.id) || '';
  title.textContent = prefill && prefill.id ? 'Edit scheduled Note' : 'Schedule a Note';
  textEl.value = (prefill && prefill.text) || '';
  if (prefill && prefill.scheduled_at) {
    const ymd = scheduleYmdInTz(prefill.scheduled_at, tz);
    dateEl.value = ymd;
    try {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      }).formatToParts(new Date(prefill.scheduled_at));
      const hh = parts.find(p => p.type === 'hour')?.value || '09';
      const mm = parts.find(p => p.type === 'minute')?.value || '00';
      timeEl.value = `${hh}:${mm}`;
    } catch (e) {
      timeEl.value = '09:00';
    }
  } else {
    const base = prefill && prefill.dateYmd
      ? new Date(prefill.dateYmd + 'T12:00:00')
      : new Date();
    if (!(prefill && prefill.dateYmd)) base.setMinutes(base.getMinutes() + 30);
    const y = base.getFullYear();
    const m = String(base.getMonth() + 1).padStart(2, '0');
    const d = String(base.getDate()).padStart(2, '0');
    dateEl.value = prefill && prefill.dateYmd ? prefill.dateYmd : `${y}-${m}-${d}`;
    timeEl.value = prefill && prefill.dateYmd
      ? '09:00'
      : `${String(base.getHours()).padStart(2, '0')}:${String(base.getMinutes()).padStart(2, '0')}`;
  }
  scheduleUpdateCharCount();
  overlay.classList.add('open');
  textEl.focus();
}

function scheduleCloseForm() {
  const overlay = document.getElementById('scheduleFormOverlay');
  if (overlay) overlay.classList.remove('open');
}

function scheduleUpdateCharCount() {
  const textEl = document.getElementById('scheduleText');
  const countEl = document.getElementById('scheduleCharCount');
  if (!textEl || !countEl) return;
  const n = textEl.value.length;
  const max = scheduleState.max_text_length || SCHEDULE_MAX_CHARS;
  countEl.textContent = `${n} / ${max}`;
  countEl.classList.toggle('over', n > max);
}

async function scheduleSaveForm() {
  const text = document.getElementById('scheduleText').value;
  const dateStr = document.getElementById('scheduleDate').value;
  const timeStr = document.getElementById('scheduleTime').value;
  const tz = document.getElementById('scheduleTz').value.trim() || localTimezone();
  const editId = document.getElementById('scheduleEditId').value;
  if (!text.trim()) {
    alert('Please write some Note text.');
    return;
  }
  if (!dateStr || !timeStr) {
    alert('Please choose a date and time.');
    return;
  }
  const scheduled_at = scheduleBuildLocalIso(dateStr, timeStr, tz);
  try {
    if (editId) {
      await scheduleApi('PATCH', `/api/schedule/${editId}`, {
        text, scheduled_at, timezone: tz, status: 'scheduled',
      });
    } else {
      await scheduleApi('POST', '/api/schedule', {
        text, scheduled_at, timezone: tz, status: 'scheduled',
      });
    }
    scheduleCloseForm();
    await refreshScheduleTab();
  } catch (e) {
    alert(e.message || 'Could not save Note');
  }
}

function renderScheduleCalendar(rootNotes) {
  const now = new Date();
  if (scheduleState.viewYear == null) {
    scheduleState.viewYear = now.getFullYear();
    scheduleState.viewMonth = now.getMonth();
  }
  const y = scheduleState.viewYear;
  const m = scheduleState.viewMonth;
  const monthName = new Date(y, m, 1).toLocaleString(undefined, { month: 'long', year: 'numeric' });
  const firstDow = new Date(y, m, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const todayYmd = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

  const byDay = {};
  rootNotes.forEach(n => {
    if (['cancelled'].includes(n.status)) return;
    const ymd = scheduleYmdInTz(n.scheduled_at, n.timezone || localTimezone());
    if (!byDay[ymd]) byDay[ymd] = [];
    byDay[ymd].push(n);
  });

  const dows = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    .map(d => `<div class="schedule-cal-dow">${d}</div>`).join('');

  let cells = '';
  for (let i = 0; i < firstDow; i++) {
    cells += `<button type="button" class="schedule-cal-cell muted" disabled></button>`;
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const ymd = `${y}-${String(m + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const notes = byDay[ymd] || [];
    const dots = notes.slice(0, 6).map(n =>
      `<span class="schedule-dot ${scheduleEscape(n.status)}" title="${scheduleEscape(scheduleStatusLabel(n))}"></span>`
    ).join('');
    const cls = ['schedule-cal-cell'];
    if (ymd === todayYmd) cls.push('today');
    cells += `<button type="button" class="${cls.join(' ')}" data-cal-date="${ymd}">
      <div class="schedule-cal-daynum">${day}</div>
      <div class="schedule-cal-dots">${dots}</div>
    </button>`;
  }

  return `
    <div class="schedule-cal-header">
      <button type="button" class="text-btn" id="scheduleCalPrev">← Prev</button>
      <h2>${scheduleEscape(monthName)}</h2>
      <button type="button" class="text-btn" id="scheduleCalNext">Next →</button>
    </div>
    <div class="schedule-cal-grid">${dows}${cells}</div>`;
}

function renderScheduleList(notes) {
  // Show actionable notes + dry-run posts; hide cancelled and real posted.
  const actionable = notes
    .filter(n =>
      ['draft', 'scheduled', 'posting', 'failed', 'missed'].includes(n.status)
      || (n.status === 'posted' && n.dry_run_post)
    )
    .slice()
    .sort((a, b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at)));

  if (!actionable.length) {
    return `<p class="no-trend">No upcoming Notes yet. Click a day on the calendar (or “New Note”) to schedule one.</p>`;
  }

  return `<div class="schedule-list">${actionable.map(n => {
    const canEdit = ['draft', 'scheduled', 'failed', 'missed'].includes(n.status);
    const canPost = ['draft', 'scheduled', 'failed', 'missed'].includes(n.status);
    const canCancel = ['draft', 'scheduled', 'failed', 'missed'].includes(n.status);
    const err = n.last_error
      ? `<p class="schedule-item-error">${scheduleEscape(n.last_error)}</p>`
      : '';
    return `<article class="schedule-item" data-note-id="${scheduleEscape(n.id)}">
      <div class="schedule-item-top">
        <span class="status-pill ${scheduleEscape(n.status)}">${scheduleEscape(scheduleStatusLabel(n))}</span>
        <span class="schedule-item-meta">${scheduleEscape(scheduleFormatWhen(n.scheduled_at, n.timezone))} · ${scheduleEscape(n.timezone || '')}</span>
      </div>
      <p class="schedule-item-text">${scheduleEscape(n.text)}</p>
      ${err}
      <div class="schedule-item-actions">
        ${canEdit ? `<button type="button" class="text-btn" data-action="edit">Edit / Reschedule</button>` : ''}
        ${canPost ? `<button type="button" class="text-btn" data-action="post-now">Post now</button>` : ''}
        ${canCancel ? `<button type="button" class="text-btn" data-action="cancel">Cancel</button>` : ''}
        <button type="button" class="text-btn" data-action="delete">Delete</button>
      </div>
    </article>`;
  }).join('')}</div>`;
}

function renderScheduleTab() {
  ensureScheduleTab();
  const root = document.getElementById('scheduleRoot');
  if (!root) return;

  if (!API_BASE) {
    root.innerHTML = `
      <div class="schedule-banner warn">
        <strong>Local server required.</strong> Double-click
        <em>Substack App - Start Server.bat</em> and open
        <code>http://localhost:8765/dashboard.html</code> so scheduling and
        auto-posting can run.
      </div>`;
    return;
  }

  const running = scheduleState.scheduler_running;
  const dry = scheduleState.settings && scheduleState.settings.dry_run;
  const auth = scheduleState.auth_blocked;
  const banners = [];
  banners.push(`<div class="schedule-banner ${running ? 'ok' : 'warn'}">
    <strong>Scheduler: ${running ? 'running' : 'not running'}.</strong>
    ${scheduleEscape(scheduleState.warning || 'Notes only auto-post while the server window is open and your computer is awake.')}
  </div>`);
  if (dry) {
    banners.push(`<div class="schedule-banner warn">
      <strong>Dry run is ON</strong> (recommended until you're ready).
      The scheduler will mark due Notes as posted without sending them to Substack,
      and will log “would have posted” in the server window.
    </div>`);
  } else {
    banners.push(`<div class="schedule-banner danger">
      <strong>Dry run is OFF.</strong> Due Notes will be sent to Substack for real
      (once posting is configured). Keep the server window open.
    </div>`);
  }
  if (auth) {
    banners.push(`<div class="schedule-banner danger" id="scheduleAuthBanner">
      <strong>Cookie problem — posting paused.</strong>
      Re-save <code>.substack_cookie.txt</code> with the Chrome extension, then click
      “Clear auth warning” below.
    </div>`);
  }

  root.innerHTML = `
    ${banners.join('')}
    <div class="schedule-toolbar">
      <div class="schedule-toolbar-left">
        <button type="button" class="cp-btn" id="scheduleNewBtn">New Note</button>
        <button type="button" class="text-btn" id="scheduleRefreshBtn">Refresh</button>
        ${auth ? `<button type="button" class="text-btn" id="scheduleClearAuthBtn">Clear auth warning</button>` : ''}
      </div>
      <div class="schedule-toolbar-right">
        <label class="schedule-toggle">
          <input type="checkbox" id="scheduleDryRunToggle" ${dry ? 'checked' : ''}>
          Dry run (no real posts)
        </label>
        <label class="schedule-toggle">
          Daily max
          <input type="number" id="scheduleDailyMax" min="1" max="100" value="${scheduleEscape(scheduleState.settings.daily_max || 10)}" style="width:64px;">
        </label>
      </div>
    </div>
    <div class="schedule-layout">
      <section>
        <h2 style="font-family:'Fraunces',serif;font-size:20px;margin:0 0 8px;">Calendar</h2>
        <p class="no-trend" style="padding:0 0 12px;">Click a day to schedule a Note for that date.</p>
        <div id="scheduleCalendar">${renderScheduleCalendar(scheduleState.notes)}</div>
      </section>
      <section>
        <h2 style="font-family:'Fraunces',serif;font-size:20px;margin:0 0 8px;">Upcoming &amp; needs attention</h2>
        <p class="no-trend" style="padding:0 0 12px;">Edit, reschedule, cancel, or post immediately.</p>
        <div id="scheduleList">${renderScheduleList(scheduleState.notes)}</div>
      </section>
    </div>`;

  bindScheduleDom();
}

function bindScheduleDom() {
  const prev = document.getElementById('scheduleCalPrev');
  const next = document.getElementById('scheduleCalNext');
  if (prev) prev.onclick = () => {
    scheduleState.viewMonth -= 1;
    if (scheduleState.viewMonth < 0) { scheduleState.viewMonth = 11; scheduleState.viewYear -= 1; }
    renderScheduleTab();
  };
  if (next) next.onclick = () => {
    scheduleState.viewMonth += 1;
    if (scheduleState.viewMonth > 11) { scheduleState.viewMonth = 0; scheduleState.viewYear += 1; }
    renderScheduleTab();
  };
  document.querySelectorAll('[data-cal-date]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      scheduleOpenForm({ dateYmd: btn.dataset.calDate });
    });
  });
  const newBtn = document.getElementById('scheduleNewBtn');
  if (newBtn) {
    newBtn.addEventListener('click', (e) => {
      e.preventDefault();
      scheduleOpenForm({});
    });
  }
  const refreshBtn = document.getElementById('scheduleRefreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', (e) => {
      e.preventDefault();
      refreshScheduleTab();
    });
  }
  const dry = document.getElementById('scheduleDryRunToggle');
  if (dry) dry.addEventListener('change', async () => {
    try {
      await scheduleApi('POST', '/api/schedule/settings', { dry_run: dry.checked });
      await refreshScheduleTab();
    } catch (e) { alert(e.message); }
  });
  const daily = document.getElementById('scheduleDailyMax');
  if (daily) daily.addEventListener('change', async () => {
    try {
      await scheduleApi('POST', '/api/schedule/settings', { daily_max: parseInt(daily.value, 10) });
      await refreshScheduleTab();
    } catch (e) { alert(e.message); }
  });
  const clearAuth = document.getElementById('scheduleClearAuthBtn');
  if (clearAuth) clearAuth.addEventListener('click', async (e) => {
    e.preventDefault();
    try {
      await scheduleApi('POST', '/api/schedule/settings', { clear_auth_blocked: true });
      await refreshScheduleTab();
    } catch (e2) { alert(e2.message); }
  });
  document.querySelectorAll('.schedule-item').forEach(item => {
    const id = item.dataset.noteId;
    item.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const action = btn.dataset.action;
        const note = scheduleState.notes.find(n => n.id === id);
        try {
          if (action === 'edit') {
            scheduleOpenForm(note);
          } else if (action === 'cancel') {
            if (!confirm('Cancel this scheduled Note?')) return;
            await scheduleApi('POST', `/api/schedule/${id}/cancel`, {});
            await refreshScheduleTab();
          } else if (action === 'delete') {
            if (!confirm('Delete this Note from your schedule? This cannot be undone.')) return;
            await scheduleApi('POST', `/api/schedule/${id}/delete`, {});
            await refreshScheduleTab();
          } else if (action === 'post-now') {
            const dryRun = scheduleState.settings && scheduleState.settings.dry_run;
            const msg = dryRun
              ? 'Post now in DRY RUN mode? Nothing will be sent to Substack; it will be marked posted (dry run).'
              : 'Post this Note to Substack NOW? This cannot be undone from this app.';
            if (!confirm(msg)) return;
            await scheduleApi('POST', `/api/schedule/${id}/post-now`, {});
            await refreshScheduleTab();
          }
        } catch (err) {
          alert(err.message || 'Action failed');
          await refreshScheduleTab();
        }
      });
    });
  });
}

function bindScheduleFormOnce() {
  if (scheduleListenersBound) return;
  scheduleListenersBound = true;
  ensureScheduleTab();
  const textEl = document.getElementById('scheduleText');
  if (textEl) textEl.addEventListener('input', scheduleUpdateCharCount);
  const cancel = document.getElementById('scheduleFormCancel');
  if (cancel) cancel.addEventListener('click', scheduleCloseForm);
  const save = document.getElementById('scheduleFormSave');
  if (save) save.addEventListener('click', scheduleSaveForm);
  const overlay = document.getElementById('scheduleFormOverlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) scheduleCloseForm();
    });
  }
}

async function refreshScheduleTab() {
  if (!API_BASE) {
    renderScheduleTab();
    return;
  }
  try {
    const data = await scheduleFetch();
    scheduleState.notes = data.notes || [];
    scheduleState.settings = data.settings || { dry_run: true, daily_max: 10 };
    scheduleState.scheduler_running = !!data.scheduler_running;
    scheduleState.auth_blocked = !!data.auth_blocked;
    scheduleState.warning = data.warning || '';
    scheduleState.max_text_length = data.max_text_length || SCHEDULE_MAX_CHARS;
    renderScheduleTab();
  } catch (e) {
    const root = document.getElementById('scheduleRoot');
    if (root) {
      root.innerHTML = `<div class="schedule-banner danger"><strong>Could not load schedule.</strong> ${scheduleEscape(e.message)} Make sure Start Server.bat is running.</div>`;
    }
  }
}

function buildScheduleTab() {
  ensureScheduleTab();
  bindScheduleFormOnce();
  refreshScheduleTab();
  if (API_BASE && !scheduleState.pollTimer) {
    scheduleState.pollTimer = setInterval(() => {
      const panel = document.getElementById('tab-schedule');
      if (panel && panel.classList.contains('active')) refreshScheduleTab();
    }, 10000);
  }
}

ensureScheduleTab();
bindScheduleFormOnce();

// ==================== TAB SWITCHING ====================
function activateDashboardTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
  if (tab === 'notes') buildNotesTab();
  if (tab === 'subscribers') buildSubscribersTab();
  if (tab === 'log') buildLogTab();
  if (tab === 'comments') buildCommentsTab();
  if (tab === 'schedule') buildScheduleTab();
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => activateDashboardTab(btn.dataset.tab));
});

// Deep-link: ?tab=schedule or #schedule opens the Schedule tab on load.
(function openTabFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get('tab');
    const fromHash = (window.location.hash || '').replace(/^#/, '');
    const tab = fromQuery || fromHash;
    if (tab && document.querySelector(`.tab-btn[data-tab="${tab}"]`)) {
      activateDashboardTab(tab);
    }
  } catch (e) { /* ignore */ }
})();
