// Small silhouettes share the painting's coordinates, including its responsive crop.
function createRiverLife(scene) {
  const painting = scene.querySelector('.painting');
  const layer = scene.querySelector('.paint-scene');
  if (!painting || !layer) return { setActive() {} };
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, parent) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    parent?.append(node);
    return node;
  };
  const svg = el('svg', { class: 'river-life', viewBox: '0 0 1536 1024', 'aria-hidden': 'true' }, layer);
  const ink = '#080e18';
  const walkers = [
    { x: 453, y: 755, span: 57, duration: 97, phase: .08, scale: .88 },
    { x: 691, y: 765, span: 68, duration: 118, phase: .19, scale: .86 },
    { x: 708, y: 766, span: 68, duration: 118, phase: .19, scale: .91 },
    { x: 977, y: 778, span: 92, duration: 144, phase: .57, scale: .97 },
    { x: 1289, y: 793, span: 63, duration: 126, phase: .29, scale: 1.03 }
  ].map((person, i) => {
    const group = el('g', { fill: ink, opacity: .88 + (i % 2) * .08 }, svg);
    const backLeg = el('path', { fill: 'none', stroke: ink, 'stroke-width': '2.1', 'stroke-linecap': 'round' }, group);
    const frontLeg = el('path', { fill: 'none', stroke: ink, 'stroke-width': '2.2', 'stroke-linecap': 'round' }, group);
    el('path', { d: 'M-2.1-14.8Q0-16 2.1-14.5L3.3-6.3Q.2-5-3-6.5Z' }, group);
    el('ellipse', { cx: .25, cy: -18, rx: 2.15, ry: 2.65 }, group);
    const arm = el('path', { fill: 'none', stroke: ink, 'stroke-width': '1.7', 'stroke-linecap': 'round' }, group);
    return { ...person, group, backLeg, frontLeg, arm };
  });
  const ducks = [
    { phase: .29, speed: 1.65, scale: .82, bob: .3 },
    { phase: .326, speed: 1.62, scale: .87, bob: 2.4 },
    { phase: .61, speed: 1.4, scale: 1.08, bob: 4.7 }
  ].map(duck => {
    const group = el('g', {}, svg);
    const wake = el('g', { fill: 'none', stroke: '#b4b59b', 'stroke-width': '.8', opacity: '.19', 'stroke-linecap': 'round' }, group);
    el('path', { d: 'M-7 1Q-15 2-25 5M-7 2Q-17 4-25 8M-11 3Q-17 5-21 6' }, wake);
    el('ellipse', { cx: -1, cy: 3, rx: 7, ry: 1.4, fill: ink, opacity: '.26' }, group);
    const body = el('g', { fill: ink }, group);
    el('path', { d: 'M-8-1Q-11-3-11-5L-5-3Q-1-6 3-4L4-8Q6-11 8-8L8-6L12-5.6L8-4Q8 0 3 1Q-4 2-8-1Z' }, body);
    return { ...duck, group, body, wake };
  });
  let active = false;
  let frame = 0;
  let last = 0;
  let time = 0;
  const travel = phase => {
    if (phase < .43) return { position: phase / .43, direction: 1, walking: true };
    if (phase < .5) return { position: 1, direction: 1, walking: false };
    if (phase < .93) return { position: 1 - (phase - .5) / .43, direction: -1, walking: true };
    return { position: 0, direction: -1, walking: false };
  };
  const draw = () => {
    walkers.forEach((person, i) => {
      const step = travel((time / person.duration + person.phase) % 1);
      const stride = step.walking ? Math.sin(time * 3.7 + i * .8) : 0;
      const x = person.x + person.span * step.position;
      const y = person.y + person.span * step.position * .048;
      const bob = step.walking ? Math.abs(stride) * .27 : 0;
      person.group.setAttribute('transform', `translate(${x.toFixed(2)} ${(y - bob).toFixed(2)}) scale(${person.scale * step.direction} ${person.scale})`);
      person.backLeg.setAttribute('d', `M-1-6L${(-1 - stride * 2).toFixed(2)}-.3`);
      person.frontLeg.setAttribute('d', `M1-6L${(1 + stride * 2).toFixed(2)}0`);
      person.arm.setAttribute('d', `M2-13Q${(3 + stride).toFixed(2)}-9 ${(2 + stride * 2).toFixed(2)}-7`);
    });
    ducks.forEach(duck => {
      const distance = (duck.phase * 1340 + time * duck.speed) % 1340;
      const x = 360 + distance;
      const y = 810 + distance * .145;
      const opacity = Math.min(1, distance / 50, (1340 - distance) / 50);
      duck.group.setAttribute('transform', `translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${duck.scale})`);
      duck.group.setAttribute('opacity', opacity.toFixed(2));
      duck.body.setAttribute('transform', `translate(0 ${(Math.sin(time * 1.2 + duck.bob) * .5).toFixed(2)})`);
      duck.wake.setAttribute('opacity', (.17 + .035 * Math.sin(time * .9 + duck.bob)).toFixed(2));
    });
  };
  const resize = () => {
    const { width, height } = scene.getBoundingClientRect();
    const scale = Math.max(width / 1536, height / 1024);
    const position = getComputedStyle(painting).objectPosition.split(' ').map(parseFloat);
    svg.style.width = `${1536 * scale}px`;
    svg.style.height = `${1024 * scale}px`;
    svg.style.left = `${(width - 1536 * scale) * position[0] / 100}px`;
    svg.style.top = `${(height - 1024 * scale) * position[1] / 100}px`;
  };
  const stop = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
  };
  const tick = now => {
    if (!active) { stop(); return; }
    // These small SVG silhouettes need only twelve updates per second.
    if (!last || now - last >= 1000 / 12) {
      if (last) time += Math.min((now - last) / 1000, .2);
      last = now;
      draw();
    }
    frame = requestAnimationFrame(tick);
  };
  new ResizeObserver(resize).observe(scene);
  resize();
  draw();
  return {
    setActive(value) {
      active = value;
      svg.dataset.motion = value ? 'moving' : 'still';
      if (value && !frame) frame = requestAnimationFrame(tick);
      else if (!value) stop();
    }
  };
}
