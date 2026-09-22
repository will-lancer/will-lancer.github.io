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
  const toggle = document.querySelector('[data-motion-toggle]');
  if (!scene || !toggle) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let userPaused = false;
  let inView = false;
  let flow = null;
  try { userPaused = localStorage.getItem('night-sky-paused') === 'true'; } catch {}
  const syncMotion = () => {
    const paused = userPaused || reduced.matches;
    scene.classList.toggle('motion-paused', paused);
    scene.classList.toggle('scene-outside', !inView || document.hidden);
    if (!paused && inView && !flow && typeof createPaintedSky === 'function') {
      flow = createPaintedSky(scene);
    }
    flow?.setActive(!paused && inView && !document.hidden);
    toggle.hidden = reduced.matches;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.setAttribute('aria-label', paused ? 'Resume sky animation' : 'Pause sky animation');
    toggle.querySelector('[data-motion-label]').textContent = paused ? 'Resume sky' : 'Pause sky';
  };
  toggle.addEventListener('click', () => {
    userPaused = !userPaused;
    try { localStorage.setItem('night-sky-paused', String(userPaused)); } catch {}
    syncMotion();
  });
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
