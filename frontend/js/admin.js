/* Admin dashboard: KPI cards, the three charts, the complaints table and the
   detail panel with its workflow actions and update log.

   Two tabs, matching how the ministry actually splits the work: "لوحة
   المؤشرات" is read-only reporting (charts and KPIs, no per-complaint
   actions); "الشكاوى الواردة" is where a complaint actually gets searched,
   filtered, advanced through its workflow, or re-routed. */

const Admin = (() => {
  const { el, ar, clear, moment, shortDate, hours, percent, signed, fileSize, toast } = Fmt;

  const PRIORITY_COLORS = { high: '#8c1c2a', medium: '#98713c', low: '#5a6a66' };
  // Badge background/foreground per status, matching the design's STATUS map.
  const STATUS_BADGE = {
    new: ['#e7eeec', '#054239'],
    assigned: ['#efe7d4', '#7d6a3c'],
    in_progress: ['#dfeae6', '#0d6a5c'],
    resolved: ['#dceee1', '#1d6b3a'],
    closed: ['#ececec', '#5a5a5a'],
  };
  const EVENT_DOTS = {
    created: '#428177',
    classified: '#428177',
    routed: '#b9a779',
    assigned: '#054239',
    status_changed: '#054239',
    priority_changed: '#8c1c2a',
    reclassified: '#988561',
    classification_suggested: '#988561',
    resolution_added: '#1d6b3a',
    attachment_added: '#428177',
    location_updated: '#428177',
    note: '#8b968f',
  };
  const PER_PAGE = 7;

  const STATUS_CHIPS = [
    { key: '', label: 'الكل' },
    { key: 'new', label: 'جديدة' },
    { key: 'assigned', label: 'محوّلة' },
    { key: 'in_progress', label: 'قيد المعالجة' },
    { key: 'resolved', label: 'تم الحل' },
    { key: 'closed', label: 'مغلقة' },
  ];

  const state = {
    tab: 'dashboard',
    status: '', type: '', department: '', priority: '',
    sort: 'created_at', order: 'desc',
    query: '', page: 1, selectedId: null,
  };
  let searchTimer = null;

  /* ---------------------------------------------------------------- KPIs */

  function renderKpis(stats) {
    const dayOverDay = stats.new_yesterday
      ? ((stats.new_today - stats.new_yesterday) / stats.new_yesterday) * 100
      : 0;
    const slaWithin = stats.sla.percent.within + stats.sla.percent.near;

    const cards = [
      {
        label: 'شكاوى جديدة اليوم',
        value: ar(stats.new_today),
        delta: stats.new_yesterday
          ? `${signed(dayOverDay)} عن أمس`
          : 'لا مقارنة متاحة',
        color: dayOverDay > 0 ? '#8c1c2a' : '#1d6b3a',
      },
      {
        label: 'قيد المعالجة',
        value: ar(stats.in_progress_count),
        delta: `ضمن المهلة ${percent(slaWithin)}`,
        color: '#5a6a66',
      },
      {
        label: 'متأخرة عن المهلة',
        value: ar(stats.overdue_count),
        delta: stats.overdue_count ? 'تحتاج تدخّل' : 'لا تأخير',
        color: stats.overdue_count ? '#8c1c2a' : '#1d6b3a',
      },
      {
        label: 'تم حلها هذا الأسبوع',
        value: ar(stats.resolved_this_week),
        delta: `من أصل ${ar(stats.total)}`,
        color: '#1d6b3a',
      },
      {
        label: 'متوسط زمن الحل',
        value: hours(stats.avg_resolution_hours),
        delta: stats.resolved_count ? `على ${ar(stats.resolved_count)} شكوى` : '—',
        color: '#1d6b3a',
      },
    ];

    const host = clear(document.getElementById('kpi-grid'));
    cards.forEach((card) =>
      host.append(el('div', { class: 'kpi' }, [
        el('span', { class: 'kpi-label', text: card.label }),
        el('span', { class: 'kpi-value', text: card.value }),
        el('span', { class: 'kpi-delta', style: `color:${card.color}`, text: card.delta }),
      ])));
  }

  /* -------------------------------------------------------------- charts */

  function renderTypeBars(stats) {
    const host = clear(document.getElementById('type-bars'));
    stats.type_breakdown.forEach((row) =>
      host.append(el('div', { class: 'bar-row' }, [
        el('span', { class: 'bar-name', title: row.label_ar, text: row.label_ar }),
        el('span', { class: 'bar-track' }, [
          el('span', {
            class: 'bar-fill',
            style: `width:${row.width}%;background:${row.color}`,
          }),
        ]),
        el('span', { class: 'bar-value', text: ar(row.count) }),
      ])));
  }

  function renderDonut(stats) {
    // Build the conic-gradient stop list from the cumulative percentages.
    let cursor = 0;
    const stops = stats.status_breakdown.map((slice) => {
      const from = cursor;
      cursor += slice.percent;
      return `${slice.color} ${from}% ${cursor}%`;
    });
    document.getElementById('donut').style.background =
      stats.total ? `conic-gradient(${stops.join(', ')})` : '#ececec';
    document.getElementById('donut-count').textContent = ar(stats.open_count);

    const legend = clear(document.getElementById('donut-legend'));
    stats.status_breakdown.forEach((slice) =>
      legend.append(el('div', { class: 'legend-item' }, [
        el('span', { class: 'legend-swatch', style: `background:${slice.color}` }),
        el('span', { class: 'legend-name', text: slice.label_ar }),
        el('span', { class: 'legend-value', text: percent(slice.percent) }),
      ])));
  }

  function renderTrend(stats) {
    const peak = Math.max(...stats.recent_days.map((d) => d.count), 1);
    const host = clear(document.getElementById('trend'));
    stats.recent_days.forEach((day, index) =>
      host.append(el('span', {
        class: 'trend-bar',
        title: `${shortDate(day.date)}: ${ar(day.count)}`,
        // A floor of 2% keeps empty days visible as a hairline.
        style: `height:${Math.max((day.count / peak) * 100, 2)}%;`
             + `background:${index === stats.recent_days.length - 1 ? '#b9a779' : '#428177'}`,
      })));

    const days = stats.recent_days;
    const axis = clear(document.getElementById('trend-axis'));
    [shortDate(days[0].date), shortDate(days[Math.floor(days.length / 2)].date), 'اليوم']
      .forEach((label) => axis.append(el('span', { text: label })));
  }

  function renderSla(stats) {
    const parts = [
      { key: 'within', label: 'ضمن المهلة', color: '#054239' },
      { key: 'near', label: 'قاربت المهلة', color: '#988561' },
      { key: 'overdue', label: 'متأخرة', color: '#8c1c2a' },
    ];
    const bar = clear(document.getElementById('sla-bar'));
    const legend = clear(document.getElementById('sla-legend'));
    parts.forEach((part) => {
      const value = stats.sla.percent[part.key];
      bar.append(el('span', { style: `width:${value}%;background:${part.color}` }));
      legend.append(el('span', { class: 'sla-legend-item' }, [
        el('i', { style: `background:${part.color}` }),
        `${part.label} ${percent(value)}`,
      ]));
    });
  }

  /* ------------------------------------------------------------- filters */

  function fillFilterOptions(meta) {
    const withAll = (id, label, items, valueKey, labelKey) => {
      const select = clear(document.getElementById(id));
      select.append(el('option', { value: '', text: label }));
      items.forEach((item) =>
        select.append(el('option', { value: item[valueKey], text: item[labelKey] })));
    };
    withAll('filter-type', 'كل التصنيفات', meta.types, 'value', 'ar');
    withAll('filter-department', 'كل الدوائر', meta.departments, 'code', 'name_ar');
    withAll('filter-priority', 'كل الأولويات', meta.priorities, 'value', 'ar');
  }

  function renderStatusChips() {
    const host = clear(document.getElementById('status-chips'));
    STATUS_CHIPS.forEach((chip) =>
      host.append(el('button', {
        type: 'button',
        class: `filter-chip${state.status === chip.key ? ' is-active' : ''}`,
        text: chip.label,
        onclick: () => {
          state.status = chip.key;
          state.page = 1;
          renderStatusChips();
          updateFilterUI();
          loadTable();
        },
      })));
  }

  function activeFilterCount() {
    return ['status', 'type', 'department', 'priority'].filter((key) => state[key]).length
      + (state.query ? 1 : 0);
  }

  function updateFilterUI() {
    const count = activeFilterCount();
    document.getElementById('filter-clear').hidden = count === 0;
    document.getElementById('filter-count').textContent = count ? ar(count) : '';
  }

  function clearFilters() {
    state.status = ''; state.type = ''; state.department = ''; state.priority = '';
    state.query = ''; state.sort = 'created_at'; state.order = 'desc'; state.page = 1;
    document.getElementById('admin-search').value = '';
    document.getElementById('filter-type').value = '';
    document.getElementById('filter-department').value = '';
    document.getElementById('filter-priority').value = '';
    document.getElementById('filter-sort').value = 'created_at:desc';
    renderStatusChips();
    updateFilterUI();
    loadTable();
  }

  /* Turns the current filter state into the query parameters the API expects. */
  function filterParams() {
    const params = {};
    if (state.status) params.status = state.status;
    if (state.type) params.type = state.type;
    if (state.department) params.department = state.department;
    if (state.priority) params.priority = state.priority;
    return params;
  }

  function listParams() {
    return {
      ...filterParams(),
      q: state.query || undefined,
      page: state.page,
      per_page: PER_PAGE,
      sort: state.sort,
      order: state.order,
    };
  }

  /* ---------------------------------------------------------------- table */

  function renderRows(page) {
    const host = clear(document.getElementById('tbl-body'));
    if (!page.items.length) {
      host.append(el('div', { class: 'tbl-empty', text: 'لا توجد شكاوى مطابقة للبحث.' }));
    }
    page.items.forEach((row) => {
      const [background, foreground] = STATUS_BADGE[row.status];
      host.append(el('button', {
        type: 'button',
        class: `tbl-row${row.id === state.selectedId ? ' is-selected' : ''}`,
        dataset: { id: row.id },
        onclick: () => select(row.id),
      }, [
        el('span', { class: 'tbl-ref', text: row.reference_no }),
        el('span', { class: 'tbl-title', title: row.title, text: row.title }),
        el('span', { class: 'tbl-citizen' }, [
          el('span', {
            class: 'tbl-citizen-name',
            title: row.citizen_name,
            text: row.citizen_name,
          }),
          el('span', { class: 'tbl-citizen-phone', text: row.citizen_phone }),
        ]),
        el('span', {
          class: 'tbl-dept',
          text: row.department ? row.department.name_ar : '—',
        }),
        el('span', {
          class: 'tbl-pri',
          style: `color:${PRIORITY_COLORS[row.priority]}`,
          text: App.priorityLabel(row.priority),
        }),
        el('span', {
          class: 'badge',
          style: `background:${background};color:${foreground}`,
          text: App.statusLabel(row.status),
        }),
      ]));
    });

    document.getElementById('tbl-count').textContent =
      `عرض ${ar(page.items.length)} من ${ar(page.total)} شكوى`;

    const pager = clear(document.getElementById('pager'));
    for (let n = 1; n <= Math.max(page.pages, 1); n += 1) {
      pager.append(el('button', {
        type: 'button',
        class: n === page.page ? 'is-active' : '',
        text: ar(n),
        onclick: () => { state.page = n; loadTable(); },
      }));
    }
  }

  async function loadTable() {
    const table = document.querySelector('.table-card');
    table.classList.add('is-loading');
    try {
      const page = await API.list(listParams());
      renderRows(page);
      // The detail panel stays on its placeholder until staff actually pick
      // a row — no complaint is "selected" just because the table loaded.
    } catch (error) {
      toast(error.message, true);
    } finally {
      table.classList.remove('is-loading');
    }
  }

  /* ---------------------------------------------------------- focus mode */

  // The row that opened the overlay, so keyboard focus can return there.
  let focusOrigin = null;

  async function select(id) {
    state.selectedId = id;
    focusOrigin = document.activeElement;
    // Highlight straight from the DOM — the old version refetched the whole
    // page just to work out which row to mark.
    document.querySelectorAll('.tbl-row').forEach((row) =>
      row.classList.toggle('is-selected', row.dataset.id === String(id)));
    try {
      renderDetail(await API.get(id));
      openFocus();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function openFocus() {
    document.getElementById('focus-overlay').hidden = false;
    // Stop the page behind the overlay from scrolling with it.
    document.body.style.overflow = 'hidden';
    document.getElementById('focus-close').focus();
  }

  function closeFocus() {
    const overlay = document.getElementById('focus-overlay');
    if (overlay.hidden) return;
    overlay.hidden = true;
    document.body.style.overflow = '';
    if (focusOrigin && document.contains(focusOrigin)) focusOrigin.focus();
    focusOrigin = null;
  }

  function eventText(event) {
    const value = (raw, kind) => {
      if (!raw) return '';
      if (kind === 'status') return App.statusLabel(raw);
      if (kind === 'priority') return App.priorityLabel(raw);
      if (kind === 'type') return App.typeLabel(raw);
      return raw;
    };
    switch (event.action) {
      case 'created': return `استلام الشكوى وإصدار الرقم المرجعي ${event.new_value}`;
      case 'classified': return `تصنيف الشكوى: ${value(event.new_value, 'type')}`;
      case 'reclassified':
        return `إعادة التصنيف إلى «${value(event.new_value, 'type')}»`;
      case 'classification_suggested':
        return `اقتراح تصنيف بديل: «${value(event.new_value, 'type')}»`;
      case 'routed': return `تحويل إلى ${event.new_value}`;
      case 'assigned': return `تعيين المسؤول: ${event.new_value}`;
      case 'status_changed':
        return `تحديث الحالة إلى «${value(event.new_value, 'status')}»`;
      case 'priority_changed':
        return `تحديث الأولوية إلى «${value(event.new_value, 'priority')}»`;
      case 'resolution_added': return 'إضافة ملخّص الحل';
      case 'attachment_added': return `إضافة مرفق: ${event.new_value}`;
      case 'location_updated': return `تحديث العنوان التفصيلي: ${event.new_value}`;
      default: return event.note || 'تحديث';
    }
  }

  function renderDetail(complaint) {
    const host = clear(document.getElementById('detail-card'));
    const [background, foreground] = STATUS_BADGE[complaint.status];
    const next = App.nextStatus(complaint.status);

    host.append(el('div', { class: 'detail-head' }, [
      el('span', { class: 'detail-ref', text: complaint.reference_no }),
      el('span', {
        class: 'badge',
        style: `background:${background};color:${foreground}`,
        text: App.statusLabel(complaint.status),
      }),
    ]));
    host.append(el('h2', { id: 'focus-heading', text: complaint.title }));
    host.append(el('p', { class: 'detail-desc', text: complaint.description }));

    // [label, value, colour, forceLtr] — phone numbers and email addresses
    // render left-to-right even inside the RTL card.
    const cells = [
      ['مقدّم الشكوى', complaint.citizen_name, null, false],
      ['رقم الموبايل', complaint.citizen_phone, null, true],
      ['التصنيف', App.typeLabel(complaint.type), null, false],
      ['المحافظة', complaint.governorate || '—', null, false],
      ['الأولوية', App.priorityLabel(complaint.priority),
       PRIORITY_COLORS[complaint.priority], false],
      ['المسؤول', complaint.assignee || '—', null, false],
    ];
    if (complaint.citizen_email) {
      cells.push(['البريد الإلكتروني', complaint.citizen_email, null, true]);
    }
    if (complaint.location_detail) {
      cells.push(['العنوان التفصيلي', complaint.location_detail, null, false]);
    }
    host.append(el('div', { class: 'detail-grid' },
      cells.map(([label, value, color, ltr]) =>
        el('div', { class: 'detail-cell' }, [
          el('div', { class: 'detail-cell-label', text: label }),
          el('div', {
            class: `detail-cell-value${ltr ? ' is-ltr' : ''}`,
            style: color ? `color:${color}` : null,
            text: value,
          }),
        ]))));

    host.append(el('div', { class: 'detail-actions' }, [
      el('button', {
        type: 'button',
        class: 'advance',
        disabled: !next,
        text: next ? `تحديث الحالة إلى «${App.statusLabel(next)}»` : 'الشكوى مغلقة',
        onclick: () => advance(complaint, next),
      }),
      el('button', {
        type: 'button',
        class: 'reroute',
        text: 'إعادة تحويل',
        onclick: () => reroute(complaint),
      }),
    ]));

    if (complaint.attachments.length) {
      host.append(el('div', { class: 'detail-attachments' },
        complaint.attachments.map((file) =>
          el('div', { class: 'detail-attachment' }, [
            el('a', { href: API.base + file.url, target: '_blank', text: file.filename }),
            el('span', { class: 'size', text: fileSize(file.size) }),
          ]))));
    }

    host.append(el('div', { class: 'timeline-title', text: 'سجل التحديثات' }));
    host.append(el('div', { class: 'timeline' },
      // Newest first, the way the design's timeline reads.
      [...complaint.events].reverse().map((event) =>
        el('div', { class: 'timeline-item' }, [
          el('div', { class: 'timeline-marker' }, [
            el('span', {
              class: 'timeline-dot',
              style: `background:${EVENT_DOTS[event.action] || '#428177'}`,
            }),
            el('span', { class: 'timeline-line' }),
          ]),
          el('div', { class: 'timeline-body' }, [
            el('span', { class: 'timeline-text', text: eventText(event) }),
            el('span', {
              class: 'timeline-meta',
              text: `${event.actor === 'system' ? 'النظام' : event.actor} · ${moment(event.created_at)}`,
            }),
            event.note && event.action !== 'note'
              ? el('span', { class: 'timeline-meta', text: event.note })
              : null,
          ]),
        ]))));
  }

  async function advance(complaint, next) {
    if (!next) return;
    const body = { status: next, actor: App.STAFF_NAME };
    if (next === 'resolved') {
      const resolution = window.prompt('ملخّص الحل (اختياري):', complaint.resolution || '');
      if (resolution) body.resolution = resolution;
    }
    try {
      renderDetail(await API.update(complaint.id, body));
      toast(`تم تحديث الحالة إلى «${App.statusLabel(next)}».`);
      await Promise.all([loadTable(), App.refreshDashboard()]);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function reroute(complaint) {
    const departments = App.meta.departments;
    const current = complaint.department ? complaint.department.name_ar : '—';
    const menu = departments.map((d, i) => `${i + 1}. ${d.name_ar}`).join('\n');
    const answer = window.prompt(
      `الدائرة الحالية: ${current}\n\nاختر رقم الدائرة الجديدة:\n${menu}`, '');
    if (!answer) return;

    const choice = departments[Number(answer.trim()) - 1];
    if (!choice) {
      toast('اختيار غير صالح.', true);
      return;
    }
    try {
      renderDetail(await API.update(complaint.id, {
        department_code: choice.code,
        actor: App.STAFF_NAME,
        note: `إعادة تحويل يدوية من ${current}`,
      }));
      toast(`تمت إعادة التحويل إلى ${choice.name_ar}.`);
      await Promise.all([loadTable(), App.refreshDashboard()]);
    } catch (error) {
      toast(error.message, true);
    }
  }

  /* ----------------------------------------------------------------- tabs */

  function setTab(tab) {
    state.tab = tab;
    closeFocus();
    document.getElementById('admin-dashboard-view').hidden = tab !== 'dashboard';
    document.getElementById('admin-inbox-view').hidden = tab !== 'inbox';
    document.querySelectorAll('[data-admin-tab]').forEach((item) =>
      item.classList.toggle('is-active', item.dataset.adminTab === tab));
    document.getElementById('admin-title').textContent =
      tab === 'inbox' ? 'الشكاوى الواردة' : 'لوحة المؤشرات';
    if (tab === 'inbox') loadTable();
  }

  /* Called each time the admin screen is (re-)entered. The dashboard tab is
     refreshed unconditionally by App.refreshDashboard(); this only needs to
     refresh the table when the inbox tab is the one currently showing. */
  function onEnter() {
    if (state.tab === 'inbox') loadTable();
  }

  /* ---------------------------------------------------------------- init */

  function renderDashboard(stats) {
    renderKpis(stats);
    renderTypeBars(stats);
    renderDonut(stats);
    renderTrend(stats);
    renderSla(stats);
    document.getElementById('admin-updated').textContent =
      `آخر تحديث للبيانات: ${moment(new Date().toISOString())}`;
  }

  function init() {
    renderStatusChips();
    updateFilterUI();

    document.getElementById('focus-close').addEventListener('click', closeFocus);
    document.getElementById('focus-overlay').addEventListener('mousedown', (event) => {
      // Backdrop only — a click that starts inside the panel must not close it.
      if (event.target.id === 'focus-overlay') closeFocus();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeFocus();
    });

    document.querySelectorAll('[data-admin-tab]').forEach((item) => {
      item.addEventListener('click', () => setTab(item.dataset.adminTab));
      item.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          setTab(item.dataset.adminTab);
        }
      });
    });

    document.getElementById('admin-search').addEventListener('input', (event) => {
      // Debounced so typing does not fire a request per keystroke.
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.query = event.target.value.trim();
        state.page = 1;
        updateFilterUI();
        loadTable();
      }, 250);
    });

    ['type', 'department', 'priority'].forEach((key) => {
      document.getElementById(`filter-${key}`).addEventListener('change', (event) => {
        state[key] = event.target.value;
        state.page = 1;
        updateFilterUI();
        loadTable();
      });
    });

    document.getElementById('filter-sort').addEventListener('change', (event) => {
      const [sort, order] = event.target.value.split(':');
      state.sort = sort;
      state.order = order;
      state.page = 1;
      loadTable();
    });

    document.getElementById('filter-clear').addEventListener('click', clearFilters);

    document.getElementById('export-csv').addEventListener('click', () => {
      window.open(API.csvUrl({ ...filterParams(), q: state.query || undefined }), '_blank');
    });
  }

  return { init, fillFilterOptions, renderDashboard, loadTable, onEnter, select, closeFocus };
})();
