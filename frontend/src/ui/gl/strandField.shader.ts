export const vertexShader = /* glsl */ `
  attribute vec2 position;
  varying vec2 vUv;

  void main() {
    vUv = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
  }
`;

export const fragmentShader = /* glsl */ `
  precision highp float;

  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uRes;
  uniform float uTension; // 0.0 calm -> 1.0 alarm
  uniform vec3 uCalm;     // rgb [0.3, 0.55, 1.0]
  uniform vec3 uAlarm;    // rgb [1.0, 0.27, 0.22]
  uniform float uPulse;   // 0.0 -> 1.0 expanding ring
  uniform vec2 uPulseOrigin;
  uniform vec2 uPointer;  // normalized coords
  uniform float uSeed;
  uniform float uReduced; // 1.0 if reduced motion

  // Simple pseudo-random hash
  float hash(vec2 p) {
    return fract(sin(dot(p + uSeed, vec2(127.1, 311.7))) * 43758.5453123);
  }

  // 2D Value Noise
  float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);

    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));

    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  // Fractional Brownian Motion with 3 octaves
  float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.5));
    for (int i = 0; i < 3; i++) {
      v += a * vnoise(p);
      p = rot * p * 2.0 + vec2(100.0);
      a *= 0.5;
    }
    return v;
  }

  void main() {
    vec2 uv = vUv;
    float aspect = uRes.x / max(1.0, uRes.y);

    // Parallax displacement from pointer (disabled if reduced motion)
    vec2 pointerOffset = (uReduced > 0.5) ? vec2(0.0) : (uPointer - 0.5) * 0.02;
    vec2 p = uv + pointerOffset;
    p.x *= aspect;

    float t = (uReduced > 0.5) ? 0.0 : uTime * 0.08;

    // Domain warp: tension increases distortion
    float warpAmp = 0.15 + uTension * 0.45;
    vec2 q = vec2(
      fbm(p * 1.5 + vec2(t * 0.3, t * 0.2)),
      fbm(p * 1.5 + vec2(t * 0.2, -t * 0.3))
    );

    float f = fbm(p * 2.0 + warpAmp * q + vec2(0.0, t * 0.5));

    // ~48 flowing horizontal strands
    float lineDensity = 48.0 + uTension * 16.0;
    float strandVal = sin(p.y * lineDensity + f * 12.0);
    float strandLine = smoothstep(0.92, 0.99, strandVal);

    // Base color interpolation between calm and alarm
    vec3 strandColor = mix(uCalm, uAlarm, clamp(uTension * 1.2, 0.0, 1.0));

    // Alpha intensity: dim bone accents (8% to 16%)
    float alpha = strandLine * (0.07 + uTension * 0.12);

    // Expandable shockwave pulse (green ring from seam)
    if (uPulse > 0.0 && uPulse < 1.0) {
      vec2 pulseCoord = (uv - uPulseOrigin);
      pulseCoord.x *= aspect;
      float dist = length(pulseCoord);
      float ringRadius = uPulse * 1.2;
      float ringWidth = 0.03 * (1.0 - uPulse);
      float ring = smoothstep(ringWidth, 0.0, abs(dist - ringRadius));
      vec3 greenPulse = vec3(0.24, 0.86, 0.52);
      strandColor = mix(strandColor, greenPulse, ring * 0.7);
      alpha += ring * 0.3 * (1.0 - uPulse);
    }

    // Edge vignette
    vec2 vigCoord = uv * (1.0 - uv);
    float vignette = clamp(vigCoord.x * vigCoord.y * 20.0, 0.0, 1.0);
    alpha *= vignette;

    // Ink-950 base (#0A0908)
    vec3 baseBg = vec3(0.039, 0.035, 0.031);
    vec3 finalColor = mix(baseBg, strandColor, alpha);

    gl_FragColor = vec4(finalColor, 1.0);
  }
`;
