// Shared convergence → daylight figure.
// One SVG definition + a render(progress) controller, reused on the home page
// (pinned scrub) and the essay page (convergence-only, scrubbed inline).
//
// progress map:
//   0 .. 0.68  lines draw left→right and squeeze together at x=200
//   ~0.62+     coral tension flares only as they actually touch
//   0.74 .. 1  one line breaks away and the daylight gap opens

export const clamp = (t: number) => Math.max(0, Math.min(1, t));
export const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function figureSVG(uid: string) {
  return `<svg viewBox="0 0 320 200" fill="none">
    <style>
      .pk { fill:none; stroke:var(--fig-line, var(--ink)); }
      .dl-plateau { stroke:var(--fig-line, var(--ink)); }
      .dl-arrow, .dl-marker { stroke:var(--mint); }
      .dl-band { fill:var(--mint); }
      .tension-core { fill:var(--coral); }
      .dim-measure { stroke:var(--fig-measure, var(--mint-ink)); }
      .dim-guide { stroke:var(--fig-faint, var(--border-faint)); }
      .dl-label { font-family:var(--font-mono); font-size:9px; letter-spacing:0.18em; fill:var(--fig-measure, var(--mint-ink)); }
    </style>
    <defs>
      <marker id="dlm-${uid}" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto">
        <path class="dl-marker" d="M1,1 L7,5 L1,9" fill="none" stroke-width="1.8"/>
      </marker>
      <radialGradient id="flare-${uid}" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stop-color="var(--coral)" stop-opacity="0.55"/>
        <stop offset="1" stop-color="var(--coral)" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <rect class="dl-band" x="200" y="50" width="100" height="70" opacity="0"/>
    <path class="pk" d="M14,54  C90,54  150,120 200,120" stroke-width="1.4" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    <path class="pk" d="M14,87  C90,87  150,120 200,120" stroke-width="1.4" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    <path class="pk" d="M14,120 C90,120 150,120 200,120" stroke-width="1.4" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    <path class="pk" d="M14,153 C90,153 150,120 200,120" stroke-width="1.4" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    <path class="pk" d="M14,186 C90,186 150,120 200,120" stroke-width="1.4" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
    <g class="dl-tension" opacity="0">
      <circle cx="200" cy="120" r="17" fill="url(#flare-${uid})"/>
      <circle class="tension-core" cx="200" cy="120" r="4.5"/>
    </g>
    <line class="dl-plateau" x1="200" y1="120" x2="200" y2="120" stroke-width="1.4" opacity="0"/>
    <line class="dl-arrow" x1="200" y1="120" x2="200" y2="120" stroke-width="2.6" opacity="0" marker-end="url(#dlm-${uid})"/>
    <g class="dl-dim" opacity="0">
      <line class="dim-measure" x1="300" y1="50" x2="300" y2="120" stroke-width="1"/>
      <path class="dim-measure" d="M296,55 L300,50 L304,55" stroke-width="1"/>
      <path class="dim-measure" d="M296,115 L300,120 L304,115" stroke-width="1"/>
      <line class="dim-guide" x1="288" y1="50" x2="304" y2="50" stroke-width="1" stroke-dasharray="3 3"/>
      <line class="dim-guide" x1="288" y1="120" x2="304" y2="120" stroke-width="1" stroke-dasharray="3 3"/>
      <text class="dl-label" x="292" y="85" text-anchor="middle" transform="rotate(-90 292 85)">DAYLIGHT</text>
    </g>
  </svg>`;
}

// build a figure inside a mount element and return its render(progress) fn
export function mountFigure(mount: Element, uid: string) {
  mount.innerHTML = figureSVG(uid);
  const pk = Array.from(mount.querySelectorAll('.pk')) as SVGPathElement[];
  const band = mount.querySelector('.dl-band') as SVGElement;
  const plat = mount.querySelector('.dl-plateau') as SVGElement;
  const arr = mount.querySelector('.dl-arrow') as SVGElement;
  const dim = mount.querySelector('.dl-dim') as SVGElement;
  const tension = mount.querySelector('.dl-tension') as SVGElement;
  return function render(p: number) {
    const conv = ease(clamp(p / 0.68));          // lines draw + squeeze together
    const day = ease(clamp((p - 0.74) / 0.25));  // hold, then break into daylight
    for (let i = 0; i < pk.length; i++) pk[i].setAttribute('stroke-dashoffset', (1 - conv).toFixed(3));
    const touch = clamp((conv - 0.82) / 0.18);   // coral only as they actually touch
    tension.setAttribute('opacity', (touch * (1 - day)).toFixed(3));
    plat.setAttribute('x2', (200 + 86 * day).toFixed(1));
    plat.setAttribute('opacity', day.toFixed(3));
    arr.setAttribute('x2', (200 + 86 * day).toFixed(1));
    arr.setAttribute('y2', (120 - 70 * day).toFixed(1));
    arr.setAttribute('opacity', clamp(day * 1.4).toFixed(3));
    band.setAttribute('opacity', (0.16 * day).toFixed(3));
    dim.setAttribute('opacity', clamp((day - 0.35) / 0.65).toFixed(3));
  };
}

// play a render fn from a→b over the given duration, once
export function playOnce(render: (p: number) => void, a: number, b: number, dur = 1500) {
  const t0 = performance.now();
  function step(now: number) {
    const t = clamp((now - t0) / dur);
    render(a + (b - a) * t);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// fire cb once, the first time el scrolls into view
export function onEnter(el: Element, cb: () => void) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { io.disconnect(); cb(); } });
  }, { threshold: 0.45 });
  io.observe(el);
}
