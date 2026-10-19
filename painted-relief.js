import * as THREE from './vendor/three/three.module.js';

// A relief traced around the painting's architecture, riverbank, swirls, and stars.
// Coordinates follow the source image, with the origin at its top left.
const CAMERA_DISTANCE = 4.2;
// Mirrored paint continues past every edge, so the moving camera never reaches a border.
const MARGIN = .07;
const ASPECT = 1024 / 1536;
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
// Centre, halo radius in image widths, and twinkle phase of each painted star.
const stars = [
  [.1106, .0330, .034, .6], [.0349, .1168, .032, 2.8], [.2716, .0540, .031, 4.3],
  [.3790, .0143, .027, 1.1], [.6058, .0570, .036, 3.4], [.7565, .0375, .029, 5.8],
  [.4965, .1715, .031, 1.9], [.1222, .3025, .025, 4.9], [.6030, .2930, .026, 2.2],
  [.6663, .3300, .030, 6.7], [.9808, .2755, .028, 3.9]
];
const moon = [.905, .142];
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
const bump = (x, y, cx, cy, radius) => {
  const dx = x - cx;
  const dy = (y - cy) * ASPECT;
  return Math.exp(-(dx * dx + dy * dy) / (radius * radius));
};
// Distance to the roofline, positive below it. Measuring in two dimensions keeps
// the transition as wide beside a spire as it is above a roof.
const skylineDistance = (x, y) => {
  let nearest = Infinity;
  for (let i = 1; i < skyline.length; i++) {
    const [ax, ay] = skyline[i - 1];
    const [bx, by] = skyline[i];
    if (x < Math.min(ax, bx) - .04 || x > Math.max(ax, bx) + .04) continue;
    const ex = bx - ax;
    const ey = (by - ay) * ASPECT;
    const px = x - ax;
    const py = (y - ay) * ASPECT;
    const t = THREE.MathUtils.clamp((px * ex + py * ey) / (ex * ex + ey * ey), 0, 1);
    nearest = Math.min(nearest, Math.hypot(px - ex * t, py - ey * t));
  }
  return y > trace(skyline, x) ? nearest : -nearest;
};

function makeRelief() {
  const span = 1 + MARGIN * 2;
  const geometry = new THREE.PlaneGeometry(3 * span, 2 * span, 320, 220);
  const positions = geometry.attributes.position;
  const uv = geometry.attributes.uv;
  const regions = new Float32Array(positions.count * 2);
  for (let i = 0; i < positions.count; i++) {
    const u = uv.getX(i) * span - MARGIN;
    const v = uv.getY(i) * span - MARGIN;
    uv.setXY(i, u, v);
    const x = THREE.MathUtils.clamp(u, 0, 1);
    const y = THREE.MathUtils.clamp(1 - v, 0, 1);
    const roof = skylineDistance(x, y);
    const building = smooth(-.026, .004, roof);
    const tree = 1 - smooth(-.008, .05, x - trace(willow, y));
    const bank = .738 + .061 * x;
    const water = smooth(bank + .003, bank + .026, y) * (1 - tree);
    const nearWater = smooth(bank, 1, y);
    // The sky sits far back, its two great swirls sink into funnels, and the
    // moon and stars hang a little in front of it.
    let skyDepth = -.5 + .1 * Math.sin(x * 7 + y * 4.5)
      - .32 * bump(x, y, .726, .213, .11)
      - .22 * bump(x, y, .864, .36, .075)
      + .3 * bump(x, y, moon[0], moon[1], .065);
    for (const [sx, sy, radius] of stars) skyDepth += .3 * bump(x, y, sx, sy, radius);
    // Low sky stays just behind the rooftops and recedes towards the top, so the
    // pinnacles never tear away from the sky around them.
    skyDepth = THREE.MathUtils.lerp(.3, skyDepth, smooth(.01, .3, -roof));
    let depth = THREE.MathUtils.lerp(skyDepth, .45, building);
    depth = THREE.MathUtils.lerp(depth, .45 + nearWater * 1.25, water);
    depth = THREE.MathUtils.lerp(depth, 1.25, tree);
    // Perspective compensation preserves the original composition at rest.
    const perspective = (CAMERA_DISTANCE - depth) / CAMERA_DISTANCE;
    positions.setXYZ(i, (u - .5) * 3 * perspective, (v - .5) * 2 * perspective, depth);
    regions[i * 2] = (1 - building) * (1 - tree);
    regions[i * 2 + 1] = water;
  }
  geometry.setAttribute('region', new THREE.BufferAttribute(regions, 2));
  geometry.computeBoundingSphere();
  return geometry;
}

// Three box passes in each direction approximate a Gaussian halo.
function blur(source, width, height, radius) {
  let from = source.slice();
  let to = new Float32Array(source.length);
  const pass = (lines, length, stride, step) => {
    for (let line = 0; line < lines; line++) {
      const start = line * stride;
      for (let c = 0; c < 3; c++) {
        let sum = 0;
        for (let k = -radius; k <= radius; k++) {
          sum += from[start + THREE.MathUtils.clamp(k, 0, length - 1) * step + c];
        }
        for (let i = 0; i < length; i++) {
          to[start + i * step + c] = sum / (radius * 2 + 1);
          sum += from[start + Math.min(i + radius + 1, length - 1) * step + c]
            - from[start + Math.max(i - radius, 0) * step + c];
        }
      }
    }
    [from, to] = [to, from];
  };
  for (let i = 0; i < 3; i++) {
    pass(height, width, width * 3, 3);
    pass(width, height, 3, width * 3);
  }
  return from;
}

// The painting's lamps, stars, and moon, softly blurred into a halo of light.
function makeGlow(painting) {
  const width = 384;
  const height = 256;
  const data = new Uint8Array(width * height * 4);
  try {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(painting, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    const light = new Float32Array(width * height * 3);
    for (let i = 0, j = 0; i < pixels.length; i += 4, j += 3) {
      const [r, g, b] = [pixels[i] / 255, pixels[i + 1] / 255, pixels[i + 2] / 255];
      const weight = smooth(.48, .86, .2126 * r + .7152 * g + .0722 * b)
        * (.3 + .7 * smooth(0, .3, (r + g) / 2 - b));
      light[j] = r * weight;
      light[j + 1] = g * weight;
      light[j + 2] = b * weight;
    }
    const near = blur(light, width, height, 3);
    const wide = blur(light, width, height, 9);
    for (let i = 0, j = 0; j < light.length; i += 4, j += 3) {
      for (let c = 0; c < 3; c++) data[i + c] = Math.min(255, (near[j + c] * .55 + wide[j + c] * .7) * 255);
      data[i + 3] = 255;
    }
  } catch (error) {
    console.warn('The painting is drawing without its glow:', error);
  }
  const texture = new THREE.DataTexture(data, width, height);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.MirroredRepeatWrapping;
  texture.minFilter = texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
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
  #define STAR_COUNT ${stars.length}
  uniform sampler2D u_painting;
  uniform sampler2D u_glow;
  uniform float u_time;
  uniform vec3 u_light;
  uniform vec4 u_stars[STAR_COUNT];
  varying vec2 v_uv;
  varying vec2 v_region;

  const vec2 ASPECT = vec2(1., ${ASPECT});
  const vec2 MOON = vec2(${moon.join(', ')});
  const vec2 TEXEL = vec2(1. / 1536., 1. / 1024.);

  float luma(vec3 color) { return dot(color, vec3(.2126, .7152, .0722)); }
  mat2 turn(float angle) { float c = cos(angle), s = sin(angle); return mat2(c, s, -s, c); }
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3. - 2. * f);
    return mix(mix(hash(i), hash(i + vec2(1., 0.)), f.x),
      mix(hash(i + vec2(0., 1.)), hash(i + 1.), f.x), f.y);
  }
  vec2 eddy(vec2 p, vec2 center, vec2 radius, float speed) {
    vec2 d = (p - center) / radius;
    return vec2(-d.y * radius.x, d.x * radius.y)
      * exp(-dot(d, d) * 1.65) * speed;
  }
  // Three unrelated rhythms, so no two stars ever flare together for long.
  float twinkle(float phase) {
    float wave = sin(u_time * 1.7 + phase) * .45
      + sin(u_time * 3.1 + phase * 2.3) * .3
      + sin(u_time * .61 + phase * 4.1) * .25;
    return smoothstep(-.55, .85, wave);
  }
  float shoulder(float x) { return x < .82 ? x : 1. - .18 * exp((.82 - x) / .18); }

  // Brightness doubles as paint height, so the brush ridges catch the light like wet oil.
  vec3 impasto(vec2 uv) {
    vec3 color = texture2D(u_painting, uv).rgb;
    vec2 slope = vec2(
      luma(texture2D(u_painting, uv + vec2(TEXEL.x, 0.)).rgb) - luma(texture2D(u_painting, uv - vec2(TEXEL.x, 0.)).rgb),
      luma(texture2D(u_painting, uv + vec2(0., TEXEL.y)).rgb) - luma(texture2D(u_painting, uv - vec2(0., TEXEL.y)).rgb));
    vec3 normal = normalize(vec3(-slope * 4., 1.));
    vec3 halfway = normalize(u_light + vec3(0., 0., 1.));
    float diffuse = clamp(dot(normal, u_light) - u_light.z, -.4, .4);
    float sheen = max(pow(max(dot(normal, halfway), 0.), 48.) - pow(halfway.z, 48.), 0.);
    return color * (1. + diffuse * .5) + vec3(1., .94, .82) * sheen * .08;
  }

  void main() {
    vec2 p = v_uv;
    float sky = smoothstep(.3, 1., v_region.x);
    float water = v_region.y;

    // Each star swells, turns its halo, and sends out rings of light on its own rhythm.
    vec2 warp = vec2(0.);
    float starLight = 0.;
    float starPulse = 0.;
    float calm = 1.;
    for (int i = 0; i < STAR_COUNT; i++) {
      vec4 star = u_stars[i];
      vec2 q = (p - star.xy) * ASPECT;
      float r = length(q) / star.z;
      float shine = twinkle(star.w);
      float reach = 1. - smoothstep(.45, 1.7, r);
      vec2 drawn = turn(sin(u_time * .4 + star.w) * .2 * reach) * q * (1. - .15 * shine * reach);
      warp += (drawn - q) / ASPECT;
      float ring = pow(.5 + .5 * sin(r * 8. - u_time * 2.1 + star.w), 3.)
        * smoothstep(.3, .8, r) * (1. - smoothstep(.9, 2.1, r));
      starLight += exp(-r * r * 5.) * (.04 + .3 * shine)
        + exp(-r * r * .9) * .05 * shine
        + ring * .035 * (.4 + .6 * shine);
      starPulse += exp(-r * r * .7) * shine;
      calm *= smoothstep(.5, 1.5, r);
    }
    // The moon keeps its shape while the rings around it sway.
    vec2 mq = (p - MOON) * ASPECT;
    float mr = length(mq);
    float halo = smoothstep(.05, .075, mr) * (1. - smoothstep(.12, .19, mr));
    warp += (turn(sin(u_time * .21) * .1 * halo) * mq - mq) / ASPECT;
    float moonGlow = exp(-mr * mr * 160.) * (.05 + .035 * sin(u_time * .35));
    calm *= smoothstep(.05, .1, mr);

    vec2 base = p + warp;
    if (water > .001) {
      float near = smoothstep(.74, 1., p.y);
      base += vec2(
        sin(p.y * 240. - u_time * 1.1) * .0022 + sin(p.y * 90. + p.x * 24. - u_time * .7) * .0012,
        sin(p.x * 110. + p.y * 30. - u_time * .8) * .0008
      ) * (.25 + near * .9) * water;
    }
    float flowing = sky * calm;
    vec3 paint;
    if (flowing > .001) {
      vec2 current = eddy(p, vec2(.726, .213), vec2(.17, .15), .3);
      current += eddy(p, vec2(.592, .1), vec2(.14, .1), -.18);
      current += eddy(p, vec2(.393, .122), vec2(.2, .115), .13);
      current += eddy(p, vec2(.864, .36), vec2(.085, .115), .28);
      current += vec2(.016, .004 * sin(p.x * 11.)) * smoothstep(.17, .3, p.y) * (1. - smoothstep(.45, .62, p.y));
      current *= flowing;
      // Each patch of sky crosses between its two flow layers at its own moment.
      float phase = fract(u_time / 11. + noise(p * 3.) * .8);
      paint = mix(impasto(base - current * phase), impasto(base - current * fract(phase + .5)),
        smoothstep(0., 1., abs(phase * 2. - 1.)));
    } else {
      paint = impasto(base);
    }

    if (water > .001) {
      float gold = smoothstep(.05, .3, paint.r - paint.b) * smoothstep(.08, .35, luma(paint));
      float shimmer = sin(p.y * 170. - u_time * 1.3 + sin(p.x * 37. + u_time * .5) * 2.);
      paint *= 1. + water * gold * (.1 + .22 * shimmer);
    }
    float lamps = (1. - sky) * (1. - water)
      * smoothstep(.06, .3, paint.r - paint.b) * smoothstep(.12, .4, luma(paint));
    float flicker = noise(p * vec2(56., 38.) + u_time * .9) * noise(p * vec2(43., 61.) - u_time * .7 + 7.);
    paint *= 1. + lamps * (flicker * .3 - .04);

    vec3 glow = texture2D(u_glow, base).rgb;
    paint += glow * (.32 + starPulse * .9 + lamps * flicker * .6);
    paint += vec3(1., .76, .4) * (starLight + moonGlow) * sky;
    gl_FragColor = vec4(shoulder(paint.r), shoulder(paint.g), shoulder(paint.b), 1.);
    #include <colorspace_fragment>
  }
`;

export function createPaintedSky(scene) {
  const canvas = scene.querySelector('.flow-canvas');
  const painting = scene.querySelector('.painting');
  if (!canvas || !painting) return { setActive() {} };
  canvas.dataset.revision = 'relief-20261019';
  let renderer, geometry, material, texture, glow, camera, world, observer;
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
  let tilt = null;
  let bounds;
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const resetPointer = () => { pointerX = 0; pointerY = 0; };
  // Listening on the window keeps the painting responsive beneath the header.
  const onPointer = event => {
    if (!active || !finePointer.matches || event.pointerType === 'touch') return;
    const rect = scene.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) { resetPointer(); return; }
    pointerX = x * 2 - 1;
    pointerY = y * 2 - 1;
  };
  // Phones without a cursor look around the painting by tilting.
  const onTilt = event => {
    if (!active || finePointer.matches || event.gamma === null || event.beta === null) return;
    const angle = screen.orientation?.angle ?? 0;
    const [x, y] = angle === 90 ? [event.beta, -event.gamma]
      : angle === 270 ? [-event.beta, event.gamma]
      : [event.gamma, event.beta];
    tilt ??= [x, y];
    // The resting angle follows slowly, so a new grip on the phone re-centres the view.
    tilt[0] += (x - tilt[0]) * .004;
    tilt[1] += (y - tilt[1]) * .004;
    pointerX = THREE.MathUtils.clamp((x - tilt[0]) / 20, -1, 1);
    pointerY = THREE.MathUtils.clamp((y - tilt[1]) / 20, -1, 1);
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
    window.removeEventListener('pointermove', onPointer);
    document.documentElement.removeEventListener('pointerleave', resetPointer);
    window.removeEventListener('deviceorientation', onTilt);
    canvas.removeEventListener('webglcontextlost', fallBack);
    painting.removeEventListener('load', init);
    painting.removeEventListener('error', fallBack);
    geometry?.dispose();
    material?.dispose();
    texture?.dispose();
    glow?.dispose();
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
    // The idle drift grows in from rest, so the first frame matches the still image.
    const settle = smooth(0, 4, elapsed);
    const driftX = Math.sin(elapsed * .21) * .075 * settle;
    const driftY = Math.sin(elapsed * .16 + 1.3) * .032 * settle;
    camera.position.set(
      easedX * .26 + driftX,
      -easedY * .12 + driftY - scroll * .08,
      CAMERA_DISTANCE - scroll * .5);
    camera.lookAt(0, 0, .25);
    material.uniforms.u_time.value = elapsed;
    material.uniforms.u_light.value.set(.55 + easedX * .45, -.45 + easedY * .4, .7).normalize();
    renderer.render(world, camera);
  };
  const resize = () => {
    if (!ready || disposed) return;
    bounds = scene.getBoundingClientRect();
    const { width, height } = bounds;
    if (!width || !height) return;
    // One draw call, under one megapixel, at 30 fps on a hardware GPU.
    const resolution = Math.min(devicePixelRatio, 1.5, Math.sqrt(900000 / (width * height)));
    renderer.setPixelRatio(1);
    renderer.setSize(Math.round(width * resolution), Math.round(height * resolution), false);
    const cover = Math.max(width / 1536, height / 1024);
    const fullWidth = 1536 * cover;
    const fullHeight = 1024 * cover;
    const position = getComputedStyle(painting).objectPosition.split(' ').map(parseFloat);
    camera.setViewOffset(fullWidth, fullHeight, (fullWidth - width) * position[0] / 100,
      (fullHeight - height) * position[1] / 100, width, height);
    draw();
  };
  const tick = now => {
    if (!active || disposed) { stop(); return; }
    if (!lastDraw || now - lastDraw >= 1000 / 30) {
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
      texture.wrapS = texture.wrapT = THREE.MirroredRepeatWrapping;
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.generateMipmaps = false;
      texture.needsUpdate = true;
      glow = makeGlow(painting);
      geometry = makeRelief();
      material = new THREE.ShaderMaterial({
        uniforms: {
          u_painting: { value: texture },
          u_glow: { value: glow },
          u_time: { value: 0 },
          u_light: { value: new THREE.Vector3(.55, -.45, .7).normalize() },
          u_stars: { value: stars.map(star => new THREE.Vector4(...star)) }
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
      window.addEventListener('pointermove', onPointer, { passive: true });
      document.documentElement.addEventListener('pointerleave', resetPointer);
      window.addEventListener('deviceorientation', onTilt, { passive: true });
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
