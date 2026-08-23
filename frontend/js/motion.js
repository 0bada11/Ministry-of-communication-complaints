/* Motion primitives: springs, velocity tracking, momentum projection.

   The project has no bundler, so this is a small hand-written spring solver
   rather than a dependency. It uses Apple's two-parameter model instead of the
   physics triplet:

     damping  — overshoot. 1.0 settles without bouncing; below 1.0 oscillates.
     response — how quickly the value reaches the target, in seconds. It is
                NOT a duration: a spring has no fixed end, its settle time
                emerges from the parameters.

   Everything a person can touch animates through a spring, because a spring
   retargets from its *current* value and velocity. That is what lets a moving
   element be grabbed and reversed mid-flight without a visible jump. */

const Motion = (() => {
  // Clamp dt so a backgrounded tab returning after seconds cannot blow up the
  // integrator with one enormous step.
  const MAX_FRAME = 1 / 30;
  // Fixed sub-step keeps the integration stable on any refresh rate, including
  // 120Hz displays and machines that drop frames.
  const SUBSTEP = 1 / 240;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const reducedTransparency = window.matchMedia('(prefers-reduced-transparency: reduce)');

  /* House presets, from Apple's published values. Bounce is reserved for
     motion the user's own gesture set going — a menu that merely appeared has
     no momentum to express, so it gets `ui`. */
  const PRESETS = {
    ui: { damping: 1.0, response: 0.35 },      // default: graceful, no overshoot
    move: { damping: 1.0, response: 0.4 },     // repositioning something
    sheet: { damping: 0.8, response: 0.3 },    // drawer released from a drag
    flick: { damping: 0.8, response: 0.4 },    // thrown with momentum
  };

  /* Every spring currently running. Needed because requestAnimationFrame is
     paused in a background tab: anything mid-flight would freeze, and a caller
     waiting on onRest — the sheet waiting to finish closing — would hang
     forever. See the visibilitychange handler at the bottom. */
  const running = new Set();

  class Spring {
    constructor(options = {}) {
      const preset = PRESETS[options.preset] || PRESETS.ui;
      this.value = options.from ?? 0;
      this.target = options.to ?? this.value;
      this.velocity = options.velocity ?? 0;
      this.damping = options.damping ?? preset.damping;
      this.response = options.response ?? preset.response;
      this.precision = options.precision ?? 0.01;
      this.onUpdate = options.onUpdate || (() => {});
      this.onRest = options.onRest || (() => {});
      this.frame = null;
      this.lastTime = 0;
    }

    /* Retarget WITHOUT resetting: the spring keeps its live value and its live
       velocity. This is the whole point — a gesture that reverses carries its
       momentum into the new direction instead of hitting a brick wall. */
    to(target, options = {}) {
      this.target = target;
      if (options.damping !== undefined) this.damping = options.damping;
      if (options.response !== undefined) this.response = options.response;
      if (options.preset) {
        this.damping = PRESETS[options.preset].damping;
        this.response = PRESETS[options.preset].response;
      }
      // Velocity handoff: a gesture's release speed becomes the spring's
      // starting speed, so there is no seam between dragging and animating.
      if (options.velocity !== undefined) this.velocity = options.velocity;
      this.start();
      return this;
    }

    /* Jump to a value with no animation — used while a finger is driving the
       value directly, where any smoothing would break 1:1 tracking. */
    set(value, velocity = 0) {
      this.stop();
      this.value = value;
      this.velocity = velocity;
      this.onUpdate(this.value);
      return this;
    }

    start() {
      // Reduced motion still gets the state change, just without the travel.
      // A hidden tab gets the same treatment: rAF will not run, and animating
      // something nobody can see is pointless anyway.
      if (reducedMotion.matches || document.hidden) return this.finish();

      if (this.frame !== null) return this; // already running; new target is enough
      running.add(this);
      this.lastTime = performance.now();
      const tick = (now) => {
        const dt = Math.min((now - this.lastTime) / 1000, MAX_FRAME);
        this.lastTime = now;
        if (this.step(dt)) {
          this.frame = requestAnimationFrame(tick);
        } else {
          this.frame = null;
          running.delete(this);
          this.onRest();
        }
      };
      this.frame = requestAnimationFrame(tick);
      return this;
    }

    /* Land on the target immediately, firing the same callbacks a natural
       settle would. Anything sequenced off onRest still runs. */
    finish() {
      this.stop();
      this.value = this.target;
      this.velocity = 0;
      this.onUpdate(this.value);
      this.onRest();
      return this;
    }

    /* Semi-implicit Euler over the damped-harmonic equation. Apple's response
       maps to the natural frequency as ω₀ = 2π / response. */
    step(dt) {
      const omega = (2 * Math.PI) / this.response;
      let remaining = dt;
      while (remaining > 0) {
        const h = Math.min(remaining, SUBSTEP);
        const accel = -2 * this.damping * omega * this.velocity
                    - omega * omega * (this.value - this.target);
        this.velocity += accel * h;
        this.value += this.velocity * h;
        remaining -= h;
      }
      const settled = Math.abs(this.target - this.value) < this.precision
                   && Math.abs(this.velocity) < this.precision;
      if (settled) {
        this.value = this.target;
        this.velocity = 0;
      }
      this.onUpdate(this.value);
      return !settled;
    }

    stop() {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null;
      running.delete(this);
      return this;
    }
  }

  /* Release velocity taken from one final pointer delta is noisy. Averaging
     over a short trailing window gives the speed the hand actually had. */
  class VelocityTracker {
    constructor(windowMs = 100) {
      this.windowMs = windowMs;
      this.samples = [];
    }

    add(value) {
      const time = performance.now();
      this.samples.push({ value, time });
      while (this.samples.length > 2 && time - this.samples[0].time > this.windowMs) {
        this.samples.shift();
      }
    }

    /* Units per second, in whatever unit was pushed in. */
    get() {
      if (this.samples.length < 2) return 0;
      const first = this.samples[0];
      const last = this.samples[this.samples.length - 1];
      const seconds = (last.time - first.time) / 1000;
      return seconds > 0 ? (last.value - first.value) / seconds : 0;
    }

    reset() {
      this.samples = [];
    }
  }

  /* Where a flick would coast to rest, given its release velocity — the same
     exponential-decay model scrolling uses. Snapping to the nearest target
     from the *release point* ignores the throw; snapping to the nearest target
     from the *projected* point is what makes a flick feel like a throw. */
  function project(velocity, decelerationRate = 0.998) {
    return (velocity / 1000) * decelerationRate / (1 - decelerationRate);
  }

  /* Progressive resistance past a boundary. A hard stop reads as frozen; real
     things slow down before they stop. */
  function rubberband(overshoot, dimension, constant = 0.55) {
    if (!dimension) return overshoot;
    return (overshoot * dimension * constant)
         / (dimension + constant * Math.abs(overshoot));
  }

  /* Backgrounding the tab stops rAF dead. Settle every live spring so no
     transition is left half-finished and no onRest continuation is lost. */
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) return;
    [...running].forEach((spring) => spring.finish());
  });

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const lerp = (from, to, t) => from + (to - from) * t;

  return {
    Spring,
    VelocityTracker,
    PRESETS,
    project,
    rubberband,
    clamp,
    lerp,
    spring: (options) => new Spring(options),
    get reducedMotion() { return reducedMotion.matches; },
    get reducedTransparency() { return reducedTransparency.matches; },
  };
})();
