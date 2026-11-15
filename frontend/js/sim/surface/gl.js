// Pomocnicze funkcje WebGL2 trybu Powierzchnia (odpowiednik GL33.create_program z geografia.py).

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`Shader compile error (${type === gl.VERTEX_SHADER ? 'VS' : 'FS'}):\n${log}`);
  }
  return sh;
}

/**
 * Kompiluje i linkuje program; zwraca lokalizacje aktywnych uniformów (`u`) i atrybutów (`a`).
 * Błąd kompilacji lub linkowania wyrzuca wyjątek z logiem sterownika.
 * @returns {{program: WebGLProgram, u: Record<string, WebGLUniformLocation>, a: Record<string, number>}}
 */
export function createProgram(gl, vsSrc, fsSrc) {
  const vs = compile(gl, gl.VERTEX_SHADER, vsSrc);
  const fs = compile(gl, gl.FRAGMENT_SHADER, fsSrc);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gl.isContextLost()) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Program link error:\n${log}`);
  }
  const u = {};
  const nu = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS) ?? 0;
  for (let i = 0; i < nu; i++) {
    const info = gl.getActiveUniform(program, i);
    const name = info.name.replace(/\[0\]$/, '');
    u[name] = gl.getUniformLocation(program, info.name);
  }
  const a = {};
  const na = gl.getProgramParameter(program, gl.ACTIVE_ATTRIBUTES) ?? 0;
  for (let i = 0; i < na; i++) {
    const info = gl.getActiveAttrib(program, i);
    a[info.name] = gl.getAttribLocation(program, info.name);
  }
  return { program, u, a };
}
