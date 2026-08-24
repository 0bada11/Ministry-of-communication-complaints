/* Application shell: loads the shared vocabulary once, routes between the
   three screens, and exposes the label lookups the other modules use. */

const App = (() => {
  const SCREENS = ['home', 'submit', 'admin'];
  const STAFF_NAME = 'م. سامر الحلبي'; // the signed-in officer the sidebar shows

  const api = {
    meta: null,
    STAFF_NAME,
    go,
    statusLabel,
    priorityLabel,
    typeLabel,
    nextStatus,
    refreshDashboard,
  };

  /* -------------------------------------------------------------- labels */

  function lookup(list, value) {
    const hit = (list || []).find((item) => item.value === value);
    return hit ? hit.ar : value;
  }

  function statusLabel(value) { return lookup(api.meta && api.meta.statuses, value); }
  function priorityLabel(value) { return lookup(api.meta && api.meta.priorities, value); }
  function typeLabel(value) { return lookup(api.meta && api.meta.types, value); }

  /* The next step in the workflow, or null once the complaint is closed. */
  function nextStatus(current) {
    const flow = api.meta.flow;
    const index = flow.indexOf(current);
    return index >= 0 && index + 1 < flow.length ? flow[index + 1] : null;
  }

  /* --------------------------------------------------------------- route */

  let current = null;
  // One spring reused for every screen change; retargeting it mid-flight lets
  // a fast double navigation continue from where the last one got to.
  let screenSpring = null;

  /* Deliberately restrained: a short rise and fade. Top-level sections have no
     spatial relationship to imply, so anything more directional would be
     inventing a hierarchy that is not there. */
  function revealScreen(node) {
    const paint = (t) => {
      node.style.transform = `translate3d(0, ${((1 - t) * 6).toFixed(2)}px, 0)`;
      node.style.opacity = t.toFixed(3);
    };
    if (!screenSpring) {
      screenSpring = Motion.spring({ from: 0, precision: 0.001 });
    }
    screenSpring.stop();
    screenSpring.onUpdate = paint;
    screenSpring.value = 0;
    screenSpring.velocity = 0;
    paint(0);
    screenSpring.to(1, { preset: 'ui' });
  }

  function go(screen, options = {}) {
    if (!SCREENS.includes(screen)) screen = 'home';
    const changed = screen !== current;
    current = screen;

    SCREENS.forEach((name) => {
      document.getElementById(`screen-${name}`).hidden = name !== screen;
    });
    document.querySelectorAll('.mainnav button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.nav === screen);
    });
    if (changed) revealScreen(document.getElementById(`screen-${screen}`));

    if (screen === 'submit') {
      // Start from a blank form when arriving from elsewhere, when a category
      // card names a type, or when the previous submission's receipt is up —
      // but never wipe a form the citizen is still filling in.
      const showingReceipt = !document.getElementById('receipt').hidden;
      if (changed || options.type || showingReceipt) Submit.reset();
      Submit.preselect(options.type);
    }
    if (screen === 'admin' && changed) {
      refreshDashboard();
      // Only reloads the table if the inbox tab is the one showing — the
      // dashboard tab needs nothing beyond the stats refresh above.
      Admin.onEnter();
    } else if (screen !== 'admin') {
      // The focus overlay is position:fixed, so it would otherwise hang over
      // whichever screen the user navigated to.
      Admin.closeFocus();
    }

    // Assigning the hash re-enters through hashchange, which is why that
    // listener has to compare against `current` before routing again.
    if (location.hash !== `#${screen}`) location.hash = screen;
    window.scrollTo({ top: 0 });
  }

  async function refreshDashboard() {
    try {
      const stats = await API.stats(14);
      Home.renderStats(stats);
      Admin.renderDashboard(stats);
    } catch (error) {
      Fmt.toast(error.message, true);
    }
  }

  /* ---------------------------------------------------------------- boot */

  async function start() {
    // Any element carrying data-nav navigates; saves wiring each button.
    document.body.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-nav]');
      if (trigger) go(trigger.dataset.nav);
    });
    window.addEventListener('hashchange', () => {
      const target = location.hash.slice(1) || 'home';
      if (target !== current) go(target);
    });

    try {
      api.meta = await API.meta();
    } catch (error) {
      Fmt.toast(
        'تعذّر الاتصال بالخادم. تأكد من تشغيل الواجهة الخلفية على المنفذ ٨٠٠٠.', true);
      return;
    }

    Submit.fillOptions(api.meta);
    Admin.fillFilterOptions(api.meta);
    Home.renderCategories(api.meta.types);
    Home.init();
    Submit.init();
    Admin.init();
    Chat.init();

    await refreshDashboard();
    go(location.hash.slice(1) || 'home');
  }

  document.addEventListener('DOMContentLoaded', start);
  return api;
})();
