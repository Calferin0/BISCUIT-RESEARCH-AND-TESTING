/* Tony in 3D: a tiny hand-written WebGL viewer for one textured GLB mesh.
   No three.js: no CDN and no build step (D3), and Tony is a single mesh with a single base-colour
   texture, so a full engine would be ~600 KB to draw one tin. Supports exactly what tony.glb
   uses: float POSITION/NORMAL/TEXCOORD_0, uint16/uint32 indices, one embedded JPEG/PNG.
   Anything it can't handle leaves the PNG poster in place. */
(function () {
  "use strict";

  var stage = document.querySelector("[data-tony-stage]");
  if (!stage || !stage.dataset.model) return;
  var canvas = stage.querySelector("[data-tony-canvas]");
  var poster = stage.querySelector("[data-tony-poster]");
  var hint = stage.querySelector("[data-tony-hint]");
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function fail(msg) {
    if (hint) hint.textContent = msg;
  }

  var gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: true });
  if (!gl) { fail("3D needs WebGL, which this browser doesn't offer. Tony is still here in 2D."); return; }

  // ---- GLB parsing -------------------------------------------------------------------------
  var COMPONENTS = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };

  function parseGlb(buf) {
    var dv = new DataView(buf);
    if (dv.getUint32(0, true) !== 0x46546C67) throw new Error("not a GLB");
    var jsonLen = dv.getUint32(12, true);
    var json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen)));
    var binStart = 20 + jsonLen + 8;  // skip the BIN chunk's length + type words

    function view(i) {
      var bv = json.bufferViews[i];
      return { offset: binStart + (bv.byteOffset || 0), length: bv.byteLength };
    }
    function accessor(i) {
      var a = json.accessors[i];
      var v = view(a.bufferView);
      var off = v.offset + (a.byteOffset || 0);
      var n = a.count * COMPONENTS[a.type];
      // Slice to a fresh, aligned buffer: typed arrays need offset % element size === 0.
      if (a.componentType === 5126) return new Float32Array(buf.slice(off, off + n * 4));
      if (a.componentType === 5123) return new Uint16Array(buf.slice(off, off + n * 2));
      if (a.componentType === 5125) return new Uint32Array(buf.slice(off, off + n * 4));
      throw new Error("unsupported component type " + a.componentType);
    }

    var prim = json.meshes[0].primitives[0];
    var at = prim.attributes;
    var posAcc = json.accessors[at.POSITION];
    var mat = json.materials && json.materials[prim.material || 0];
    var texInfo = mat && mat.pbrMetallicRoughness && mat.pbrMetallicRoughness.baseColorTexture;
    var image = null;
    if (texInfo) {
      var img = json.images[json.textures[texInfo.index].source];
      var iv = view(img.bufferView);
      image = new Blob([new Uint8Array(buf, iv.offset, iv.length)], { type: img.mimeType });
    }
    return {
      positions: accessor(at.POSITION),
      normals: at.NORMAL !== undefined ? accessor(at.NORMAL) : null,
      uvs: at.TEXCOORD_0 !== undefined ? accessor(at.TEXCOORD_0) : null,
      indices: accessor(prim.indices),
      min: posAcc.min, max: posAcc.max,
      image: image,
    };
  }

  // ---- tiny matrix helpers (column-major, like GL) -------------------------------------------
  function perspective(fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
  }
  function multiply(a, b) {
    var o = new Array(16);
    for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
    return o;
  }
  function rotY(t) { var c = Math.cos(t), s = Math.sin(t); return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]; }
  function rotX(t) { var c = Math.cos(t), s = Math.sin(t); return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]; }
  function translate(x, y, z) { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]; }
  function scale(k) { return [k, 0, 0, 0, 0, k, 0, 0, 0, 0, k, 0, 0, 0, 0, 1]; }

  // ---- GL setup ----------------------------------------------------------------------------
  var VS = [
    "attribute vec3 aPos; attribute vec3 aNrm; attribute vec2 aUv;",
    "uniform mat4 uMvp; uniform mat4 uModel;",
    "varying vec3 vNrm; varying vec2 vUv;",
    "void main() { vNrm = mat3(uModel) * aNrm; vUv = aUv; gl_Position = uMvp * vec4(aPos, 1.0); }",
  ].join("\n");
  // The scan's texture already has the studio lighting baked in, so shading is gentle:
  // mostly the texture, plus a soft key light so the shape reads as it turns.
  var FS = [
    "precision mediump float;",
    "uniform sampler2D uTex; uniform float uHasTex;",
    "varying vec3 vNrm; varying vec2 vUv;",
    "void main() {",
    "  vec3 n = normalize(vNrm); if (!gl_FrontFacing) n = -n;",
    "  float key = max(dot(n, normalize(vec3(0.4, 0.6, 1.0))), 0.0);",
    "  vec3 base = mix(vec3(0.85, 0.8, 0.7), texture2D(uTex, vUv).rgb, uHasTex);",
    "  gl_FragColor = vec4(base * (0.72 + 0.38 * key), 1.0);",
    "}",
  ].join("\n");

  function shader(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  function buffer(target, data) {
    var b = gl.createBuffer();
    gl.bindBuffer(target, b);
    gl.bufferData(target, data, gl.STATIC_DRAW);
    return b;
  }

  function start(mesh, bitmap) {
    var prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);

    function attrib(name, data, size) {
      var loc = gl.getAttribLocation(prog, name);
      if (loc < 0) return;
      if (!data) { gl.disableVertexAttribArray(loc); gl.vertexAttrib3f(loc, 0, 0, 1); return; }
      buffer(gl.ARRAY_BUFFER, data);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    }
    attrib("aPos", mesh.positions, 3);
    attrib("aNrm", mesh.normals, 3);
    attrib("aUv", mesh.uvs, 2);

    var indexType = gl.UNSIGNED_SHORT;
    if (mesh.indices instanceof Uint32Array) {
      if (!gl.getExtension("OES_element_index_uint")) throw new Error("32-bit indices unsupported");
      indexType = gl.UNSIGNED_INT;
    }
    buffer(gl.ELEMENT_ARRAY_BUFFER, mesh.indices);

    gl.uniform1f(gl.getUniformLocation(prog, "uHasTex"), bitmap ? 1 : 0);
    if (bitmap) {
      var tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      // glTF UVs put (0,0) at the image's top-left, which is how WebGL uploads it by default.
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, bitmap);
      gl.generateMipmap(gl.TEXTURE_2D);  // fine: the slim texture is 1024x1024 (power of two)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    }

    var uMvp = gl.getUniformLocation(prog, "uMvp");
    var uModel = gl.getUniformLocation(prog, "uModel");
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);  // the material is double-sided
    gl.clearColor(0, 0, 0, 0);

    // Centre the scan on the origin and fit its tallest side to 1 unit.
    var cx = (mesh.min[0] + mesh.max[0]) / 2, cy = (mesh.min[1] + mesh.max[1]) / 2, cz = (mesh.min[2] + mesh.max[2]) / 2;
    var size = Math.max(mesh.max[0] - mesh.min[0], mesh.max[1] - mesh.min[1], mesh.max[2] - mesh.min[2]);
    var fit = multiply(scale(1 / size), translate(-cx, -cy, -cz));

    var FRONT = parseFloat(stage.dataset.front || "0");  // radians; which way Tony faces at rest
    var yaw = FRONT, pitch = 0.12, spin = reduceMotion ? 0 : 0.5;  // spin in rad/s
    var hop = 0, dragging = false, lastX = 0, lastY = 0, moved = 0, idleUntil = 0, last = 0, running = false;

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
    }

    function frame(now) {
      running = false;
      if (document.hidden) return;
      var dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
      last = now;
      if (!dragging && now > idleUntil) yaw += spin * dt;
      hop = Math.max(0, hop - dt * 2.2);
      var lift = Math.sin(hop * Math.PI) * 0.12;
      var squash = 1 + Math.sin(hop * Math.PI * 2) * 0.04;

      resize();
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      var model = multiply(rotX(pitch), multiply(rotY(yaw), fit));
      var world = multiply(translate(0, lift - 0.02, -2.0), multiply([1, 0, 0, 0, 0, squash, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], model));
      var proj = perspective(0.62, canvas.width / Math.max(canvas.height, 1), 0.1, 10);
      gl.uniformMatrix4fv(uMvp, false, multiply(proj, world));
      gl.uniformMatrix4fv(uModel, false, model);
      gl.drawElements(gl.TRIANGLES, mesh.indices.length, indexType, 0);

      if (spin || dragging || hop > 0) request();
    }
    function request() {
      if (running) return;
      running = true;
      requestAnimationFrame(frame);
    }

    // Drag to turn him, tap to boop (a little hop).
    canvas.addEventListener("pointerdown", function (e) {
      dragging = true; moved = 0; lastX = e.clientX; lastY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
      request();
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var dx = e.clientX - lastX, dy = e.clientY - lastY;
      moved += Math.abs(dx) + Math.abs(dy);
      lastX = e.clientX; lastY = e.clientY;
      yaw += dx * 0.012;
      pitch = Math.max(-0.6, Math.min(0.8, pitch + dy * 0.008));
      request();
    });
    function release() {
      if (!dragging) return;
      dragging = false;
      idleUntil = performance.now() + 2500;  // let them look before the spin resumes
      if (moved < 6) hop = 1;
      request();
    }
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", release);
    document.addEventListener("visibilitychange", function () { last = 0; request(); });
    window.addEventListener("resize", request);

    poster.hidden = true;
    canvas.hidden = false;
    if (hint) hint.textContent = "3D scan · drag to spin him · tap to boop";
    request();
  }

  fetch(stage.dataset.model)
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
    .then(function (buf) {
      var mesh = parseGlb(buf);
      if (!mesh.image) return start(mesh, null);
      return createImageBitmap(mesh.image).then(function (bmp) { start(mesh, bmp); });
    })
    .catch(function (err) {
      fail("Couldn't load the 3D scan, so here's the photo.");
      if (window.console) console.warn("tony3d:", err);
    });
})();
