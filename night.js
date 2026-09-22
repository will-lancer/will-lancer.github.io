(() => {
  const header = document.querySelector('.site-header, .blog-toolbar');
  const menu = document.querySelector('[data-menu-toggle]');
  const closeMenu = () => {
    if (!menu || !header) return;
    header.classList.remove('nav-open');
    menu.setAttribute('aria-expanded', 'false');
    menu.textContent = 'Menu';
  };
  if (menu && header) {
    header.classList.add('has-menu');
    menu.addEventListener('click', () => {
      const open = header.classList.toggle('nav-open');
      menu.setAttribute('aria-expanded', String(open));
      menu.textContent = open ? 'Close' : 'Menu';
    });
    header.querySelectorAll('nav a').forEach(link => link.addEventListener('click', closeMenu));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && header.classList.contains('nav-open')) {
        closeMenu();
        menu.focus();
      }
    });
    document.addEventListener('click', event => {
      if (!header.contains(event.target)) closeMenu();
    });
    matchMedia('(min-width: 761px)').addEventListener('change', event => {
      if (event.matches) closeMenu();
    });
  }

  const scene = document.querySelector('.night-hero');
  if (!scene) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const life = typeof createRiverLife === 'function' ? createRiverLife(scene) : null;
  let inView = false;
  let flow = null;
  const syncMotion = () => {
    const paused = reduced.matches;
    scene.classList.toggle('scene-outside', !inView || document.hidden);
    if (!paused && inView && !flow && typeof createPaintedSky === 'function') {
      flow = createPaintedSky(scene);
    }
    flow?.setActive(!paused && inView && !document.hidden);
    life?.setActive(!paused && inView && !document.hidden);
  };
  reduced.addEventListener('change', syncMotion);
  document.addEventListener('visibilitychange', syncMotion);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      inView = entries[0].isIntersecting;
      syncMotion();
    }).observe(scene);
  } else {
    inView = true;
  }
  syncMotion();
})();
