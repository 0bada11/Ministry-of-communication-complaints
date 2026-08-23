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

  /* ------------------------------------------------------ chart motion */

  /* Charts are torn down and rebuilt on every refresh, so the animation state
     cannot live on the elements. One long-lived spring per series does the
     job: it starts at 0 (so the first paint is an entrance) and is retargeted
     afterwards, carrying its own velocity. That means a refresh eases from
     whatever is currently on screen instead of replaying the entrance, and a
     refresh landing mid-flight has nothing to jump from. */
  const chartSprings = new Map();

  function animateValue(key, to, apply, options = {}) {
    let spring = chartSprings.get(key);
    if (!spring) {
      spring = Motion.spring({
        from: options.from ?? 0,
        precision: options.precision ?? 0.001,
      });
      chartSprings.set(key, spring);
    }
    // Rewire the output to the freshly created element, then paint once so it
    // appears at the live value rather than flashing at zero.
    spring.onUpdate = apply;
    apply(spring.value);
    spring.to(to, { preset: options.preset || 'ui' });
  }

  /* ---------------------------------------------------------------- KPIs */

  function renderKpis(stats) {
    const dayOverDay = stats.new_yesterday
      ? ((stats.new_today - stats.new_yesterday) / stats.new_yesterday) * 100
      : 0;
    const slaWithin = stats.sla.percent.within + stats.sla.percent.near;

    // `count` is the number the figure animates towards; `format` turns the
    // in-between values into the text actually shown.
    const cards = [
      {
        label: 'شكاوى جديدة اليوم',
        count: stats.new_today,
        format: (n) => ar(Math.round(n)),
        delta: stats.new_yesterday
          ? `${signed(dayOverDay)} عن أمس`
          : 'لا مقارنة متاحة',
        color: dayOverDay > 0 ? '#8c1c2a' : '#1d6b3a',
      },
      {
        label: 'قيد المعالجة',
        count: stats.in_progress_count,
        format: (n) => ar(Math.round(n)),
        delta: `ضمن المهلة ${percent(slaWithin)}`,
        color: '#5a6a66',
      },
      {
        label: 'متأخرة عن المهلة',
        count: stats.overdue_count,
        format: (n) => ar(Math.round(n)),
        delta: stats.overdue_count ? 'تحتاج تدخّل' : 'لا تأخير',
        color: stats.overdue_count ? '#8c1c2a' : '#1d6b3a',
      },
      {
        label: 'تم حلها هذا الأسبوع',
        count: stats.resolved_this_week,
        format: (n) => ar(Math.round(n)),
        delta: `من أصل ${ar(stats.total)}`,
        color: '#1d6b3a',
      },
      {
        label: 'متوسط زمن الحل',
        count: stats.avg_resolution_hours ?? 0,
        format: (n) => (stats.avg_resolution_hours === null ? '—' : hours(n)),
        delta: stats.resolved_count ? `على ${ar(stats.resolved_count)} شكوى` : '—',
        color: '#1d6b3a',
      },
    ];

    const host = clear(document.getElementById('kpi-grid'));
    cards.forEach((card) => {
      const figure = el('span', { class: 'kpi-value' });
      host.append(el('div', { class: 'kpi' }, [
        el('span', { class: 'kpi-label', text: card.label }),
        figure,
        el('span', { class: 'kpi-delta', style: `color:${card.color}`, text: card.delta }),
      ]));
      // Counting up reads as the figure being tallied rather than asserted,
      // and on a refresh it walks from the old number to the new one.
      animateValue(`kpi:${card.label}`, card.count, (n) => {
        figure.textContent = card.format(n);
      }, { preset: 'move', precision: 0.01 });
    });
  }

  /* -------------------------------------------------------------- charts */

  function renderTypeBars(stats) {
    const host = clear(document.getElementById('type-bars'));
    stats.type_breakdown.forEach((row, index) => {
      // The fill spans the track and is scaled down to the real figure, so the
      // animation is a compositor-only transform rather than a width relayout.
      const fill = el('span', {
        class: 'bar-fill',
        style: `width:100%;background:${row.color};transform:scaleX(0)`,
      });
      const value = el('span', { class: 'bar-value' });
      host.append(el('div', { class: 'bar-row' }, [
        el('span', { class: 'bar-name', title: row.label_ar, text: row.label_ar }),
        el('span', { class: 'bar-track' }, [fill]),
        value,
      ]));

      animateValue(`bar:${row.type}`, row.width / 100, (t) => {
        fill.style.transform = `scaleX(${Math.max(t, 0).toFixed(4)})`;
      }, { preset: 'ui' });

      // The figure counts alongside its own bar, so the two read as one thing.
      animateValue(`bar-count:${row.type}`, row.count, (n) => {
        value.textContent = ar(Math.round(n));
      }, { preset: 'move', precision: 0.01 });
    });
  }

  function renderDonut(stats) {
    // Build the conic-gradient stop list from the cumulative percentages.
    let cursor = 0;
    const stops = stats.status_breakdown.map((slice) => {
      const from = cursor;
      cursor += slice.percent;
      return `${slice.color} ${from}% ${cursor}%`;
    });
    const donut = document.getElementById('donut');
    donut.style.background =
      stats.total ? `conic-gradient(${stops.join(', ')})` : '#ececec';

    // A conic gradient cannot be interpolated, so the ring arrives as a
    // material instead: it scales up once, then stays put on later refreshes.
    animateValue('donut', 1, (t) => {
      donut.style.transform = `scale(${Motion.lerp(0.86, 1, t).toFixed(4)})`;
      donut.style.opacity = t.toFixed(3);
    }, { preset: 'ui' });

    const centre = document.getElementById('donut-count');
    animateValue('donut-count', stats.open_count, (n) => {
      centre.textContent = ar(Math.round(n));
    }, { preset: 'move', precision: 0.01 });

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
    stats.recent_days.forEach((day, index) => {
      // Full-height bar scaled down to its real value: same compositor-only
      // trick as the category bars, and it interpolates cleanly on refresh.
      const bar = el('span', {
        class: 'trend-bar',
        title: `${shortDate(day.date)}: ${ar(day.count)}`,
        style: `height:100%;transform:scaleY(0);`
             + `background:${index === stats.recent_days.length - 1 ? '#b9a779' : '#428177'}`,
      });
      host.append(bar);

      // A floor keeps empty days visible as a hairline rather than nothing.
      const fraction = Math.max(day.count / peak, 0.02);
      animateValue(`trend:${day.date}`, fraction, (t) => {
        bar.style.transform = `scaleY(${Math.max(t, 0).toFixed(4)})`;
      }, { preset: 'ui' });
    });

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

    // The segments have to keep real widths to lay out side by side, so the
    // whole bar wipes in as one piece rather than each segment scaling.
    bar.style.transformOrigin = 'right center';
    animateValue('sla-bar', 1, (t) => {
      bar.style.transform = `scaleX(${Math.max(t, 0).toFixed(4)})`;
    }, { preset: 'ui' });
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

  /* Two springs drive the sheet, and every visual property is derived from
     them in one place. `openness` runs 0→1 as the sheet arrives; `drag` is the
     live pixel offset while a finger is on it. Keeping them separate means a
     half-open sheet can be grabbed mid-flight — the drag simply adds to
     whatever the open spring is currently reading. */
  let openness = 0;
  let dragOffset = 0;
  let closing = false;

  const opennessSpring = Motion.spring({
    from: 0,
    precision: 0.001,
    onUpdate: (value) => { openness = value; paintFocus(); },
    onRest: () => {
      // Only actually hide once the sheet has finished leaving.
      if (closing) finishClose();
    },
  });

  const dragSpring = Motion.spring({
    from: 0,
    onUpdate: (value) => { dragOffset = value; paintFocus(); },
  });

  // Measured when a drag begins and when the sheet opens, never per frame —
  // reading offsetHeight inside the paint loop would force a layout on every
  // single frame of the gesture.
  let panelHeight = 600;

  function focusEls() {
    return {
      overlay: document.getElementById('focus-overlay'),
      panel: document.querySelector('.focus-panel'),
    };
  }

  function measurePanel() {
    const { panel } = focusEls();
    if (panel && panel.offsetHeight) panelHeight = panel.offsetHeight;
    return panelHeight;
  }

  /* The single place that turns spring values into pixels. Both springs and
     the drag handler funnel through here, so the scrim and the sheet can never
     disagree about where the sheet is. */
  function paintFocus() {
    const { overlay, panel } = focusEls();
    if (!panel) return;

    // Enter along the same path it exits: down and slightly small.
    const enterOffset = (1 - openness) * 26;
    const y = enterOffset + dragOffset;
    const scale = Motion.lerp(0.97, 1, openness);

    // The scrim thins out as the sheet is pulled away, so the page behind
    // comes back gradually rather than all at once on release.
    const pulled = Motion.clamp(dragOffset / panelHeight, 0, 1);
    const presence = openness * (1 - pulled * 0.9);

    panel.style.transform = `translate3d(0, ${y.toFixed(2)}px, 0) scale(${scale.toFixed(4)})`;
    panel.style.opacity = openness.toFixed(3);
    overlay.style.backgroundColor = `rgba(0, 38, 35, ${(0.55 * presence).toFixed(3)})`;
    // Blur and scale rise together so the surface reads as a material
    // arriving, not a rectangle fading in.
    overlay.style.backdropFilter = Motion.reducedTransparency
      ? 'none'
      : `blur(${(6 * presence).toFixed(2)}px)`;
  }

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
    const { overlay } = focusEls();
    const wasClosing = closing;
    closing = false;
    overlay.hidden = false;
    // Stop the page behind the overlay from scrolling with it.
    document.body.style.overflow = 'hidden';
    measurePanel();

    if (wasClosing && dragOffset !== 0) {
      // Reopened while it was still leaving: bring it back from where it
      // actually is, rather than snapping it home and animating again.
      dragSpring.to(0, { preset: 'ui' });
    } else {
      dragSpring.set(0);
    }
    paintFocus();
    // No gesture preceded this, so no overshoot: a sheet that bounces when it
    // was merely clicked open reads as decoration.
    opennessSpring.to(1, { preset: 'ui' });
    document.getElementById('focus-close').focus();
  }

  /* `velocity` lets a flick carry its speed straight into the exit, so there
     is no seam between the finger letting go and the sheet leaving. */
  function closeFocus(velocity = 0) {
    const { overlay } = focusEls();
    if (overlay.hidden || closing) return;
    closing = true;

    if (dragOffset > 0 || velocity > 0) {
      // Dismissed by a downward drag — keep going the way the hand was going.
      dragSpring.to(panelHeight + 80, { preset: 'sheet', velocity });
    }
    opennessSpring.to(0, { preset: 'ui' });
  }

  function finishClose() {
    const { overlay, panel } = focusEls();
    overlay.hidden = true;
    document.body.style.overflow = '';
    closing = false;
    // Zero the spring itself, not just the mirrored value — otherwise the next
    // open would animate back from wherever the dismissal left it.
    dragSpring.set(0);
    if (panel) panel.classList.remove('is-dragging');
    if (focusOrigin && document.contains(focusOrigin)) focusOrigin.focus();
    focusOrigin = null;
  }

  /* ------------------------------------------------- drag-to-dismiss */

  // Fraction of the sheet's height the projected landing point must pass for
  // the gesture to count as a dismissal rather than a nudge.
  const DISMISS_FRACTION = 0.35;
  const DRAG_THRESHOLD = 8; // px of travel before we commit to a direction

  function initFocusGesture() {
    const overlay = document.getElementById('focus-overlay');
    const panel = document.querySelector('.focus-panel');
    const tracker = new Motion.VelocityTracker();

    let pointerId = null;
    let startY = 0;
    let dragging = false;
    let abandoned = false;

    panel.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 && event.pointerType === 'mouse') return;
      // Controls and text selection keep their normal behaviour.
      if (event.target.closest('button, a, input, select, textarea')) return;
      // Only take over at the top of the scroll: below that, a downward drag
      // is a scroll and belongs to the browser.
      if (overlay.scrollTop > 0) return;

      pointerId = event.pointerId;
      startY = event.clientY;
      dragging = false;
      abandoned = false;
      measurePanel();
      tracker.reset();
      tracker.add(0);
    });

    panel.addEventListener('pointermove', (event) => {
      if (pointerId !== event.pointerId || abandoned) return;
      const delta = event.clientY - startY;

      if (!dragging) {
        // Hysteresis: wait for real intent before hijacking the pointer.
        if (Math.abs(delta) < DRAG_THRESHOLD) return;
        if (delta < 0) { abandoned = true; return; } // upward — let it scroll
        dragging = true;
        panel.setPointerCapture(pointerId);
        panel.classList.add('is-dragging');
        dragSpring.stop();
      }

      // 1:1 downward, progressive resistance upward — the sheet is already
      // home, so pulling further up should feel like it is held by something.
      const offset = delta >= 0
        ? delta
        : Motion.rubberband(delta, panelHeight);

      tracker.add(offset);
      dragOffset = offset;
      paintFocus();
      event.preventDefault();
    });

    const release = (event) => {
      if (pointerId !== event.pointerId) return;
      const wasDragging = dragging;
      pointerId = null;
      dragging = false;
      abandoned = false;
      panel.classList.remove('is-dragging');
      if (!wasDragging) return;

      const velocity = tracker.get();
      // Decide from where the throw is *heading*, not where the finger
      // happened to stop — that is what makes a short flick still dismiss.
      const projected = dragOffset + Motion.project(velocity);

      if (projected > panelHeight * DISMISS_FRACTION) {
        closeFocus(velocity);
      } else {
        // Snapping back is momentum-driven, so here the bounce is earned.
        dragSpring.value = dragOffset;
        dragSpring.to(0, { preset: 'sheet', velocity });
      }
    };

    panel.addEventListener('pointerup', release);
    panel.addEventListener('pointercancel', release);
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

    initFocusGesture();
    document.getElementById('focus-close').addEventListener('click', () => closeFocus());
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
