// Advect the painted sky and river along connected currents on the GPU.
function createPaintedSky(scene) {
  const canvas = scene.querySelector('.flow-canvas');
  const painting = scene.querySelector('.painting');
  if (!canvas || !painting) return { setActive() {} };
  let gl;
  let program;
  let frame = 0;
  let active = false;
  let ready = false;
  let disposed = false;
  let elapsed = 0;
  let lastDraw = 0;
  let uniform;
  let observer;
  const source = {
    vertex: `
      attribute vec2 a_position;
      varying vec2 v_uv;
      void main() {
        v_uv = vec2(a_position.x * .5 + .5, .5 - a_position.y * .5);
        gl_Position = vec4(a_position, 0., 1.);
      }`,
    fragment: `
      precision mediump float;
      varying vec2 v_uv;
      uniform sampler2D u_painting;
      uniform vec2 u_crop;
      uniform vec2 u_position;
      uniform float u_time;

      vec2 eddy(vec2 p, vec2 center, vec2 radius, float speed) {
        vec2 d = (p - center) / radius;
        return vec2(-d.y * radius.x, d.x * radius.y)
          * exp(-dot(d, d) * 1.65) * speed;
      }

      float starDisk(vec2 p, vec2 center, float radius) {
        vec2 d = (p - center) * vec2(1., .666667);
        float r = dot(d, d) / (radius * radius);
        return 1. - smoothstep(.08, 1., r);
      }

      float twinkle(vec2 p, vec2 center, float radius, float phase, float speed) {
        float pulse = .52 + .34 * sin(u_time * speed + phase)
          + .14 * sin(u_time * speed * 1.73 + phase * 2.1);
        return starDisk(p, center, radius) * pulse;
      }

      float sky(vec2 p) {
        float skyline = mix(.54, .30, smoothstep(.56, .77, p.x));
        float area = (1. - smoothstep(skyline - .11, skyline, p.y))
          * smoothstep(.08, .21, p.x);
        // Keep the painted moon and the centres of the larger stars in place.
        area *= smoothstep(.055, .13, length((p - vec2(.912, .145)) * vec2(1., .82)));
        float stars = starDisk(p, vec2(.1107, .0303), .025);
        stars = max(stars, starDisk(p, vec2(.0358, .1162), .024));
        stars = max(stars, starDisk(p, vec2(.2741, .0527), .024));
        stars = max(stars, starDisk(p, vec2(.3783, .0146), .020));
        stars = max(stars, starDisk(p, vec2(.6061, .0576), .026));
        stars = max(stars, starDisk(p, vec2(.7578, .0361), .022));
        stars = max(stars, starDisk(p, vec2(.4987, .1699), .023));
        stars = max(stars, starDisk(p, vec2(.1237, .3027), .020));
        stars = max(stars, starDisk(p, vec2(.6055, .2910), .019));
        stars = max(stars, starDisk(p, vec2(.6673, .3154), .023));
        area *= 1. - stars;
        return area;
      }

      vec2 current(vec2 p) {
        vec2 v = eddy(p, vec2(.726, .214), vec2(.18, .155), .69);
        v += eddy(p, vec2(.591, .103), vec2(.145, .105), -.35);
        v += eddy(p, vec2(.393, .122), vec2(.21, .12), .23);
        // A broad current connects the eddies across the top of the painting.
        float ribbon = exp(-pow((p.y - .15 - .035 * sin(p.x * 10.)) / .13, 2.));
        v += vec2(.013, .0045 * cos(p.x * 10.)) * ribbon;
        return v * sky(p);
      }

      vec2 upstream(vec2 p, float phase) {
        // Midpoint integration follows curved streamlines through the paint.
        vec2 v = current(p);
        return p - current(p - v * phase * .5) * phase;
      }

      float river(vec2 p) {
        // Follow the far bank and keep the bridge and foreground tree still.
        float bank = .738 + .074 * p.x;
        return smoothstep(bank + .004, bank + .025, p.y)
          * smoothstep(.135, .185, p.x);
      }

      vec2 downstream(vec2 p, float phase) {
        float depth = smoothstep(.755, 1., p.y);
        vec2 velocity = vec2(.010 + .018 * depth, .0018 + .004 * depth);
        vec2 ripple = vec2(.00065 * sin(p.y * 230. - u_time * .48),
          .00032 * sin(p.x * 95. - u_time * .39));
        return p - velocity * phase + ripple * depth;
      }

      void main() {
        vec2 p = v_uv * u_crop + (1. - u_crop) * u_position;
        float cycle = u_time / 16.;
        float phaseA = fract(cycle);
        float phaseB = fract(cycle + .5);
        float blend = smoothstep(0., 1., abs(phaseA * 2. - 1.));
        vec4 a = texture2D(u_painting, upstream(p, phaseA));
        vec4 b = texture2D(u_painting, upstream(p, phaseB));
        vec4 paint = mix(a, b, blend);
        float water = river(p);
        if (water > .001) {
          float riverPhase = fract(u_time / 24.);
          float riverBlend = smoothstep(0., 1., abs(riverPhase * 2. - 1.));
          vec4 nearWater = texture2D(u_painting, downstream(p, riverPhase));
          vec4 farWater = texture2D(u_painting, downstream(p, fract(riverPhase + .5)));
          paint = mix(paint, mix(nearWater, farWater, riverBlend), water);
        }
        // Each existing painted star brightens at its own slow, uneven cadence.
        float light = twinkle(p, vec2(.1107, .0303), .034, .6, .92);
        light += twinkle(p, vec2(.0358, .1162), .032, 2.8, 1.16);
        light += twinkle(p, vec2(.2741, .0527), .031, 4.3, 1.05);
        light += twinkle(p, vec2(.3783, .0146), .027, 1.1, 1.29);
        light += twinkle(p, vec2(.6061, .0576), .036, 3.4, .85);
        light += twinkle(p, vec2(.7578, .0361), .029, 5.8, 1.12);
        light += twinkle(p, vec2(.4987, .1699), .031, 1.9, .98);
        light += twinkle(p, vec2(.1237, .3027), .025, 4.9, 1.24);
        light += twinkle(p, vec2(.6055, .2910), .026, 2.2, 1.34);
        light += twinkle(p, vec2(.6673, .3154), .033, 6.7, .89);
        paint.rgb = 1. - (1. - paint.rgb) * (1. - vec3(1., .83, .47) * light * .46);
        gl_FragColor = paint;
      }`
  };

  const stop = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    lastDraw = 0;
  };
  const fallBack = () => {
    disposed = true;
    stop();
    observer?.disconnect();
    scene.classList.remove('flow-ready');
    canvas.dataset.status = 'still';
  };
  const compile = (type, text) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, text);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      throw new Error('Sky shader unavailable');
    }
    return shader;
  };
  const draw = () => {
    gl.uniform1f(uniform.time, elapsed);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  };
  const resize = () => {
    if (!ready || disposed) return;
    const { width, height } = scene.getBoundingClientRect();
    if (!width || !height) return;
    // Bound the work regardless of display resolution; 24 frames per second.
    const scale = Math.min(devicePixelRatio, 1.25, Math.sqrt(720000 / (width * height)));
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    gl.viewport(0, 0, canvas.width, canvas.height);
    const imageRatio = painting.naturalWidth / painting.naturalHeight;
    const viewRatio = width / height;
    gl.uniform2f(uniform.crop, Math.min(viewRatio / imageRatio, 1), Math.min(imageRatio / viewRatio, 1));
    const position = getComputedStyle(painting).objectPosition.split(' ').map(parseFloat);
    gl.uniform2f(uniform.position, position[0] / 100, position[1] / 100);
    draw();
  };
  const tick = now => {
    if (!active || disposed) { stop(); return; }
    if (!lastDraw || now - lastDraw >= 1000 / 24) {
      if (lastDraw) elapsed += Math.min((now - lastDraw) / 1000, .1);
      lastDraw = now;
      draw();
    }
    frame = requestAnimationFrame(tick);
  };
  const start = () => {
    if (active && ready && !disposed && !frame) frame = requestAnimationFrame(tick);
  };
  const init = () => {
    if (disposed) return;
    try {
      gl = canvas.getContext('webgl', {
        alpha: false, antialias: false, depth: false, stencil: false,
        powerPreference: 'low-power', preserveDrawingBuffer: false
      });
      if (!gl) { fallBack(); return; }
      const debug = gl.getExtension('WEBGL_debug_renderer_info');
      const renderer = String(gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
      canvas.dataset.renderer = renderer;
      if (/swiftshader|llvmpipe|software|softpipe/i.test(renderer)) {
        gl.getExtension('WEBGL_lose_context')?.loseContext();
        fallBack();
        return;
      }
      const vertex = compile(gl.VERTEX_SHADER, source.vertex);
      const fragment = compile(gl.FRAGMENT_SHADER, source.fragment);
      program = gl.createProgram();
      gl.attachShader(program, vertex);
      gl.attachShader(program, fragment);
      gl.linkProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Sky program unavailable');
      gl.useProgram(program);
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
      const position = gl.getAttribLocation(program, 'a_position');
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, painting);
      gl.uniform1i(gl.getUniformLocation(program, 'u_painting'), 0);
      uniform = {
        crop: gl.getUniformLocation(program, 'u_crop'),
        position: gl.getUniformLocation(program, 'u_position'),
        time: gl.getUniformLocation(program, 'u_time')
      };
      ready = true;
      resize();
      scene.classList.add('flow-ready');
      canvas.dataset.status = 'gpu';
      observer = new ResizeObserver(resize);
      observer.observe(scene);
      start();
    } catch { fallBack(); }
  };
  canvas.addEventListener('webglcontextlost', fallBack);
  if (painting.complete && painting.naturalWidth) init();
  else painting.addEventListener('load', init, { once: true });
  return {
    setActive(value) {
      active = value;
      canvas.dataset.motion = value && !disposed ? "flowing" : "paused";
      if (value) start();
      else stop();
    }
  };
}
