import * as THREE from './vendor/three/three.module.js';

// A shallow relief traced around the painting's architecture and riverbank.
// Coordinates follow the source image, with the origin at its top left.
const CAMERA_DISTANCE = 4.2;
const skyline = [
  [0, .69], [.20, .69], [.26, .65], [.277, .65], [.283, .576],
  [.292, .61], [.30, .58], [.306, .655], [.38, .633], [.397, .602],
  [.408, .616], [.412, .576], [.418, .613], [.46, .624], [.463, .585],
  [.470, .545], [.48, .556], [.49, .548], [.493, .594], [.516, .616],
  [.532, .622], [.533, .559], [.543, .557], [.548, .615], [.603, .634],
  [.607, .581], [.614, .628], [.640, .626], [.642, .578], [.653, .58],
  [.659, .63], [.699, .629], [.701, .409], [.707, .374], [.713, .349],
  [.719, .389], [.726, .414], [.727, .470], [.743, .452], [.749, .425],
  [.754, .450], [.777, .465], [.780, .362], [.785, .348], [.792, .308],
  [.799, .349], [.803, .37], [.809, .481], [.823, .484], [.825, .433],
  [.833, .487], [.843, .463], [.849, .502], [.86, .453], [.866, .504],
  [.879, .462], [.887, .513], [.90, .488], [.91, .528], [.922, .511],
  [.926, .437], [.932, .413], [.94, .445], [.948, .538], [1, .563]
];
const willow = [
  [0, .018], [.18, .022], [.22, .041], [.29, .055], [.34, .087],
  [.40, .11], [.48, .128], [.52, .162], [.60, .197], [.69, .187],
  [.75, .155], [.87, .126], [1, .105]
];
const smooth = (lo, hi, value) => {
  const t = THREE.MathUtils.clamp((value - lo) / (hi - lo), 0, 1);
  return t * t * (3 - 2 * t);
};
const trace = (points, position) => {
  for (let i = 1; i < points.length; i++) {
    if (position <= points[i][0]) {
      const [a, b] = [points[i - 1], points[i]];
      return THREE.MathUtils.lerp(a[1], b[1], (position - a[0]) / (b[0] - a[0]));
    }
  }
  return points.at(-1)[1];
};

function makeRelief() {
  const geometry = new THREE.PlaneGeometry(3, 2, 240, 160);
  const positions = geometry.attributes.position;
  const uv = geometry.attributes.uv;
  const regions = new Float32Array(positions.count * 2);
  for (let i = 0; i < positions.count; i++) {
    const x = uv.getX(i);
    const y = 1 - uv.getY(i);
    const building = smooth(-.012, .008, y - trace(skyline, x));
    const tree = 1 - smooth(-.01, .015, x - trace(willow, y));
    const bank = .738 + .061 * x;
    const water = smooth(bank + .003, bank + .026, y) * (1 - tree);
    const nearWater = smooth(bank, 1, y);
    const skyDepth = -.18 + .075 * Math.sin(x * 8 + y * 5);
    let depth = THREE.MathUtils.lerp(skyDepth, .45, building);
    depth = THREE.MathUtils.lerp(depth, .45 + nearWater * 1.05, water);
    depth = THREE.MathUtils.lerp(depth, 1.4, tree);
    // Perspective compensation preserves the original composition at rest.
    const perspective = (CAMERA_DISTANCE - depth) / CAMERA_DISTANCE;
    positions.setXYZ(i, (x - .5) * 3 * perspective, (.5 - y) * 2 * perspective, depth);
    regions[i * 2] = (1 - building) * (1 - tree);
    regions[i * 2 + 1] = water;
  }
  geometry.setAttribute('region', new THREE.BufferAttribute(regions, 2));
  geometry.computeBoundingSphere();
  return geometry;
}

const vertexShader = `
  attribute vec2 region;
  varying vec2 v_uv;
  varying vec2 v_region;
  void main() {
    v_uv = vec2(uv.x, 1. - uv.y);
    v_region = region;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.);
  }
`;
const fragmentShader = `
  uniform sampler2D u_painting;
  uniform float u_time;
  uniform vec2 u_light;
  varying vec2 v_uv;
  varying vec2 v_region;

  vec2 eddy(vec2 p, vec2 center, vec2 radius, float speed) {
    vec2 d = (p - center) / radius;
    return vec2(-d.y * radius.x, d.x * radius.y)
      * exp(-dot(d, d) * 1.65) * speed;
  }
  float disk(vec2 p, vec2 center, float radius) {
    vec2 d = (p - center) * vec2(1., .666667);
    return 1. - smoothstep(.08, 1., dot(d, d) / (radius * radius));
  }
  float star(vec2 p, vec2 center, float radius, float phase) {
    return disk(p, center, radius) * (.5 + .5 * sin(u_time * .42 + phase));
  }
  float paintLuminance(vec3 color) { return dot(color, vec3(.2126, .7152, .0722)); }

  void main() {
    vec2 p = v_uv;
    float sky = smoothstep(.3, 1., v_region.x);
    // Leave the moon's silhouette intact as the surrounding paint flows.
    sky *= smoothstep(.066, .13, length((p - vec2(.912, .145)) * vec2(1., .82)));
    vec2 current = eddy(p, vec2(.726, .214), vec2(.18, .155), .23);
    current += eddy(p, vec2(.591, .103), vec2(.145, .105), -.12);
    current += eddy(p, vec2(.393, .122), vec2(.21, .12), .08);
    current *= sky;
    float phase = fract(u_time / 22.);
    float blend = smoothstep(0., 1., abs(phase * 2. - 1.));
    vec3 paint = mix(
      texture2D(u_painting, p - current * phase).rgb,
      texture2D(u_painting, p - current * fract(phase + .5)).rgb, blend);

    float water = v_region.y;
    if (water > .001) {
      float near = smoothstep(.76, 1., p.y);
      vec2 ripple = vec2(
        sin(p.y * 240. - u_time * .55) * .0012,
        sin(p.x * 110. + p.y * 30. - u_time * .4) * .00055
      ) * (.2 + near * .8);
      vec3 reflection = texture2D(u_painting, p + ripple).rgb;
      float glint = .985 + .035 * sin(p.y * 170. - u_time * .42);
      paint = mix(paint, reflection * glint, water);
    }
    float glow = star(p, vec2(.1107, .0303), .034, .6);
    glow += star(p, vec2(.0358, .1162), .032, 2.8);
    glow += star(p, vec2(.2741, .0527), .031, 4.3);
    glow += star(p, vec2(.3783, .0146), .027, 1.1);
    glow += star(p, vec2(.6061, .0576), .036, 3.4);
    glow += star(p, vec2(.7578, .0361), .029, 5.8);
    glow += star(p, vec2(.4987, .1699), .031, 1.9);
    glow += star(p, vec2(.1237, .3027), .025, 4.9);
    glow += star(p, vec2(.6055, .2910), .026, 2.2);
    glow += star(p, vec2(.6673, .3154), .033, 6.7);
    paint += vec3(1., .69, .25) * glow * .037 * sky;

    // A small grazing highlight picks out the existing paint ridges.
    vec2 grain = vec2(1. / 1536., 1. / 1024.);
    float ridgeX = paintLuminance(texture2D(u_painting, p + vec2(grain.x, 0.)).rgb)
      - paintLuminance(texture2D(u_painting, p - vec2(grain.x, 0.)).rgb);
    float ridgeY = paintLuminance(texture2D(u_painting, p + vec2(0., grain.y)).rgb)
      - paintLuminance(texture2D(u_painting, p - vec2(0., grain.y)).rgb);
    paint *= 1. + clamp(dot(vec2(ridgeX, ridgeY), u_light), -.12, .12) * .24;
    gl_FragColor = vec4(paint, 1.);
    #include <colorspace_fragment>
  }
`;

export function createPaintedSky(scene) {
  const canvas = scene.querySelector('.flow-canvas');
  const painting = scene.querySelector('.painting');
  if (!canvas || !painting) return { setActive() {} };
  canvas.dataset.revision = 'relief-20260922';
  let renderer, geometry, material, texture, camera, world, observer;
  let frame = 0;
  let active = false;
  let ready = false;
  let disposed = false;
  let elapsed = 0;
  let lastDraw = 0;
  let pointerX = 0;
  let pointerY = 0;
  let easedX = 0;
  let easedY = 0;
  let scroll = 0;
  let bounds;
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const resetPointer = () => { pointerX = 0; pointerY = 0; };
  const onPointer = event => {
    if (!active || !finePointer.matches || event.pointerType === 'touch') return;
    const rect = scene.getBoundingClientRect();
    pointerX = THREE.MathUtils.clamp((event.clientX - rect.left) / rect.width * 2 - 1, -1, 1);
    pointerY = THREE.MathUtils.clamp((event.clientY - rect.top) / rect.height * 2 - 1, -1, 1);
  };
  const stop = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    lastDraw = 0;
  };
  const fallBack = () => {
    if (disposed) return;
    disposed = true;
    stop();
    observer?.disconnect();
    scene.removeEventListener('pointermove', onPointer);
    scene.removeEventListener('pointerleave', resetPointer);
    canvas.removeEventListener('webglcontextlost', fallBack);
    painting.removeEventListener('load', init);
    painting.removeEventListener('error', fallBack);
    geometry?.dispose();
    material?.dispose();
    texture?.dispose();
    renderer?.dispose();
    scene.classList.remove('flow-ready');
    canvas.dataset.status = 'still';
    canvas.dataset.motion = 'paused';
  };
  const draw = (delta = 0) => {
    const easing = 1 - Math.exp(-delta * 3.2);
    easedX += (pointerX - easedX) * easing;
    easedY += (pointerY - easedY) * easing;
    const scrollTarget = bounds ? THREE.MathUtils.clamp(-scene.getBoundingClientRect().top / bounds.height, 0, 1) : 0;
    scroll += (scrollTarget - scroll) * easing;
    const driftX = Math.sin(elapsed * .14) * .028;
    const driftY = Math.sin(elapsed * .11) * .011;
    camera.position.set(easedX * .105 + driftX, -easedY * .05 + driftY - scroll * .045, CAMERA_DISTANCE);
    camera.lookAt(0, 0, .25);
    material.uniforms.u_time.value = elapsed;
    material.uniforms.u_light.value.set(.65 + easedX * .2, -.45 - easedY * .15);
    renderer.render(world, camera);
  };
  const resize = () => {
    if (!ready || disposed) return;
    bounds = scene.getBoundingClientRect();
    const { width, height } = bounds;
    if (!width || !height) return;
    // One draw call, under one megapixel, at 24 fps on a hardware GPU.
    const resolution = Math.min(devicePixelRatio, 1.5, Math.sqrt(900000 / (width * height)));
    renderer.setPixelRatio(1);
    renderer.setSize(Math.round(width * resolution), Math.round(height * resolution), false);
    const cover = Math.max(width / 1536, height / 1024) * 1.065;
    const fullWidth = 1536 * cover;
    const fullHeight = 1024 * cover;
    const position = getComputedStyle(painting).objectPosition.split(' ').map(parseFloat);
    camera.setViewOffset(fullWidth, fullHeight, (fullWidth - width) * position[0] / 100,
      (fullHeight - height) * position[1] / 100, width, height);
    draw();
  };
  const tick = now => {
    if (!active || disposed) { stop(); return; }
    if (!lastDraw || now - lastDraw >= 1000 / 24) {
      const delta = lastDraw ? Math.min((now - lastDraw) / 1000, .12) : 0;
      elapsed += delta;
      lastDraw = now;
      draw(delta);
    }
    frame = requestAnimationFrame(tick);
  };
  const start = () => {
    if (active && ready && !disposed && !frame) frame = requestAnimationFrame(tick);
  };
  function init() {
    if (disposed || ready) return;
    try {
      const context = canvas.getContext('webgl2', {
        alpha: false, antialias: false, depth: true, stencil: false,
        powerPreference: 'low-power', preserveDrawingBuffer: false
      });
      if (!context) { fallBack(); return; }
      const debug = context.getExtension('WEBGL_debug_renderer_info');
      const gpu = String(context.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : context.RENDERER));
      canvas.dataset.renderer = gpu;
      if (!debug || /swiftshader|llvmpipe|software|softpipe/i.test(gpu)) {
        fallBack();
        context.getExtension('WEBGL_lose_context')?.loseContext();
        return;
      }
      renderer = new THREE.WebGLRenderer({ canvas, context });
      renderer.setClearColor(0x102d50, 1);
      renderer.debug.onShaderError = (gl, program, vertex, fragment) => {
        throw new Error(gl.getShaderInfoLog(fragment) || gl.getShaderInfoLog(vertex) || gl.getProgramInfoLog(program));
      };
      world = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(THREE.MathUtils.radToDeg(2 * Math.atan(1 / CAMERA_DISTANCE)), 1.5, .1, 15);
      camera.position.z = CAMERA_DISTANCE;
      texture = new THREE.Texture(painting);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.flipY = false;
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.generateMipmaps = false;
      texture.needsUpdate = true;
      geometry = makeRelief();
      material = new THREE.ShaderMaterial({
        uniforms: {
          u_painting: { value: texture },
          u_time: { value: 0 },
          u_light: { value: new THREE.Vector2(.65, -.45) }
        },
        vertexShader, fragmentShader, toneMapped: false
      });
      world.add(new THREE.Mesh(geometry, material));
      ready = true;
      resize();
      canvas.dataset.engine = `three-r${THREE.REVISION}`;
      canvas.dataset.triangles = String(renderer.info.render.triangles);
      canvas.dataset.status = 'gpu';
      scene.classList.toggle('flow-ready', !reduced.matches);
      observer = new ResizeObserver(resize);
      observer.observe(scene);
      scene.addEventListener('pointermove', onPointer, { passive: true });
      scene.addEventListener('pointerleave', resetPointer);
      start();
    } catch (error) {
      canvas.dataset.error = error.message;
      console.warn('Painting renderer unavailable:', error);
      fallBack();
    }
  }
  canvas.addEventListener('webglcontextlost', fallBack);
  if (painting.complete && painting.naturalWidth) init();
  else {
    painting.addEventListener('load', init, { once: true });
    painting.addEventListener('error', fallBack, { once: true });
  }
  return {
    setActive(value) {
      active = value && !disposed;
      canvas.dataset.motion = active ? 'flowing' : 'paused';
      if (ready && !disposed) scene.classList.toggle('flow-ready', !reduced.matches);
      if (active) start();
      else { stop(); resetPointer(); }
    }
  };
}
