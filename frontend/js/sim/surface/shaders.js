// Shadery trybu Powierzchnia: LunarTerrain3D._TERRAIN_VS/FS i _HORIZON_VS/FS z geografia.py
// przepisane dosłownie do GLSL ES 3.00. Jedyne zmiany (odchylenia 1-4 z planu):
//   1. nagłówek `#version 300 es` + kwalifikatory precyzji;
//   2. DEM z tekstury-okna R32F: texture(u_tex_dem, …) → demTexel (VS, środki tekseli w
//      sample_dem_catmull) i demLinear (FS, ręczna interpolacja dwuliniowa, REPEAT/CLAMP_TO_EDGE);
//      zawijanie w demTexel bez % na liczbach ujemnych (niezdefiniowane w GLSL ES 3.00);
//   3. UV albedo przez albedoUV(uv) (globalne UV → UV tekstury-okna; pełny pierścień bez mod);
//   4. u_offset_px/u_viewport w horizon VS (WebGL ignoruje lineWidth > 1).
// Wspólny blok okna (demTexel/demLinear/albedoUV) jest wklejony po uniformach VS i FS terenu.
//
// Niebo: GPURenderer._STAR_VS/FS, _GRID_VS/FS, _QUAD_VS, _SUN_FS i _EARTH_FS (geografia.py:527-834)
// dosłownie, zmieniony tylko nagłówek (jak w 1.). _HUD_FS pomijamy: HUD rysuje canvas 2D (odchylenie 5).
// gl_FragCoord w WebGL ma początek w lewym dolnym rogu jak w GL, więc py = u_ch - gl_FragCoord.y - 0.5 zostaje.

// geografia.py:1223-1340
export const TERRAIN_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    const float PI = 3.14159265358979323846;
    const float TWO_PI = 6.28318530717958647692;
    const float R_MOON = 1737.4;

    in vec2 in_uv;
    in float in_is_skirt;

    in vec4 in_lat_lon;   // (lat0_rad, lat1_rad, lon0_rad, lon1_rad)
    in float in_skirt_km;

    uniform sampler2D u_tex_dem;
    uniform vec2 u_dem_size;

    uniform float u_obs_lat;
    uniform float u_obs_lon;
    uniform float u_obs_elev;
    uniform float u_sin_obs_lat;
    uniform float u_cos_obs_lat;

    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;
    uniform float u_near;
    uniform float u_far;
    // --- okno z kafli (odchylenie 1/2): DEM przez texelFetch, albedo przez albedoUV ---
    uniform vec2 u_dem_origin, u_dem_win; uniform int u_dem_full;      // okno DEM w tekselach globalnych
    uniform vec2 u_alb_origin, u_alb_win, u_alb_size;
    float demTexel(ivec2 g) {                                             // = GL REPEAT (S), CLAMP_TO_EDGE (T)
      int W = int(u_dem_size.x), H = int(u_dem_size.y);
      // % tylko na nieujemnych argumentach: w GLSL ES 3.00 (§5.9) wynik dla ujemnych jest niezdefiniowany
      // (Mesa/Intel liczy go jak dla unsigned: -1 % 5760 = 255). g.x >= -2, gx i origin.x w [0, W).
      int gx = (g.x + W) % W, gy = clamp(g.y, 0, H - 1);
      int lx = u_dem_full == 1 ? gx : clamp((gx - int(u_dem_origin.x) + W) % W, 0, int(u_dem_win.x) - 1);
      int ly = clamp(gy - int(u_dem_origin.y), 0, int(u_dem_win.y) - 1);
      return texelFetch(u_tex_dem, ivec2(lx, ly), 0).r;
    }
    float demLinear(vec2 uv) {                                            // = texture() z LINEAR
      vec2 t = uv * u_dem_size - 0.5; vec2 i = floor(t); vec2 f = t - i; ivec2 b = ivec2(i);
      return mix(mix(demTexel(b), demTexel(b + ivec2(1,0)), f.x),
                 mix(demTexel(b + ivec2(0,1)), demTexel(b + ivec2(1,1)), f.x), f.y);
    }
    vec2 albedoUV(vec2 uv) {
      // mod tylko dla okna częściowego; przy pełnym pierścieniu okno = tekstura globalna (S = REPEAT),
      // a skok mod przy lon = ±180° psułby pochodne (wybór mipmapy) wzdłuż południka
      float x = uv.x * u_alb_size.x - u_alb_origin.x;
      return vec2((u_alb_win.x < u_alb_size.x ? mod(x, u_alb_size.x) : x) / u_alb_win.x,
                  (uv.y * u_alb_size.y - u_alb_origin.y) / u_alb_win.y);
    }

    out vec2 v_lat_lon;
    out vec3 v_pos_enu;
    out vec3 v_u_pt;
    out vec3 v_north_pt;
    out vec3 v_east_pt;
    out vec3 v_u_body;
    out vec3 v_north_body;
    out vec3 v_east_body;

    float sample_dem_catmull(vec2 uv) {
        vec2 texel = uv * u_dem_size - 0.5;
        vec2 f = fract(texel);
        vec2 i = floor(texel) + 0.5;
        vec2 inv_sz = 1.0 / u_dem_size;

        vec2 f2 = f * f;
        vec2 f3 = f2 * f;
        vec2 w0 = -0.5 * f + f2 - 0.5 * f3;
        vec2 w1 = 1.0 - 2.5 * f2 + 1.5 * f3;
        vec2 w2 = 0.5 * f + 2.0 * f2 - 1.5 * f3;
        vec2 w3 = -0.5 * f2 + 0.5 * f3;

        float h = 0.0;
        for (int r = -1; r <= 2; ++r) {
            float wy = (r == -1) ? w0.y : ((r == 0) ? w1.y : ((r == 1) ? w2.y : w3.y));
            // vy (T = CLAMP_TO_EDGE) liczy teraz demTexel; linia zostaje jak w oryginale
            float vy = clamp((i.y + float(r)) * inv_sz.y, 0.5 * inv_sz.y, 1.0 - 0.5 * inv_sz.y);
            float h_row =
                demTexel(ivec2(floor(texel)) + ivec2(-1, r)) * w0.x +
                demTexel(ivec2(floor(texel)) + ivec2(0, r)) * w1.x +
                demTexel(ivec2(floor(texel)) + ivec2(1, r)) * w2.x +
                demTexel(ivec2(floor(texel)) + ivec2(2, r)) * w3.x;
            h += h_row * wy;
        }
        return h;
    }

    void main() {
        float lat = mix(in_lat_lon.x, in_lat_lon.y, in_uv.y);
        float lon = mix(in_lat_lon.z, in_lat_lon.w, in_uv.x);

        vec2 uv_global = vec2((lon + PI) / TWO_PI, (PI * 0.5 - lat) / PI);
        float h = sample_dem_catmull(uv_global) - in_is_skirt * in_skirt_km;

        float dlat = lat - u_obs_lat;
        float dlon = lon - u_obs_lon;
        float cos_lat = cos(lat);
        float sin_lat = sin(lat);
        float cos_lon = cos(lon);
        float sin_lon = sin(lon);
        float sin_dlat = sin(dlat);
        float sin_dlon = sin(dlon);
        float sin_half_dlat = sin(0.5 * dlat);
        float sin_half_dlon = sin(0.5 * dlon);

        float du_north = sin_dlat + 2.0 * cos_lat * u_sin_obs_lat * (sin_half_dlon * sin_half_dlon);
        float du_east  = cos_lat * sin_dlon;
        float du_up    = -2.0 * (sin_half_dlat * sin_half_dlat)
                         - 2.0 * cos_lat * u_cos_obs_lat * (sin_half_dlon * sin_half_dlon);

        float r_pt = R_MOON + h;
        vec3 rel_enu = r_pt * vec3(du_north, du_east, du_up) + vec3(0.0, 0.0, h - u_obs_elev);

        vec3 u_pt = normalize(vec3(du_north, du_east, 1.0 + du_up));
        vec3 east_pt = normalize(vec3(-u_sin_obs_lat * sin_dlon, cos(dlon), u_cos_obs_lat * sin_dlon));
        vec3 north_pt = cross(u_pt, east_pt);

        vec3 u_body = vec3(cos_lat * cos_lon, cos_lat * sin_lon, sin_lat);
        vec3 east_body = vec3(-sin_lon, cos_lon, 0.0);
        vec3 north_body = vec3(-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat);

        float zc = dot(rel_enu, u_fwd);
        float xc = dot(rel_enu, u_right);
        float yc = dot(rel_enu, u_cam_up);

        float x_ndc = xc / u_tan_x;
        float y_ndc = yc / u_tan_y;
        float z_log = 2.0 * (log2(max(1e-7, zc / u_near)) / log2(u_far / u_near)) - 1.0;
        gl_Position = vec4(x_ndc, y_ndc, z_log * zc, zc);

        v_lat_lon = vec2(lat, lon);
        v_pos_enu = rel_enu;
        v_u_pt = u_pt;
        v_north_pt = north_pt;
        v_east_pt = east_pt;
        v_u_body = u_body;
        v_north_body = north_body;
        v_east_body = east_body;
    }
`;

// geografia.py:1342-1462
export const TERRAIN_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    const float PI = 3.14159265358979323846;
    const float TWO_PI = 6.28318530717958647692;
    const float R_MOON = 1737.4;

    in vec2 v_lat_lon;
    in vec3 v_pos_enu;
    in vec3 v_u_pt;
    in vec3 v_north_pt;
    in vec3 v_east_pt;
    in vec3 v_u_body;
    in vec3 v_north_body;
    in vec3 v_east_body;

    uniform sampler2D u_tex_dem;
    uniform sampler2D u_tex_albedo;
    uniform vec2 u_dem_size;
    uniform int u_albedo_raw_u8;
    uniform float u_albedo_scale;

    uniform vec3 u_sun_enu;
    uniform vec3 u_earth_enu;
    uniform float u_sun_effective_vis;
    uniform float u_earthshine;
    uniform vec3 u_tint;
    uniform vec3 u_wire_add;
    // --- okno z kafli (odchylenie 1/2): DEM przez texelFetch, albedo przez albedoUV ---
    uniform vec2 u_dem_origin, u_dem_win; uniform int u_dem_full;      // okno DEM w tekselach globalnych
    uniform vec2 u_alb_origin, u_alb_win, u_alb_size;
    float demTexel(ivec2 g) {                                             // = GL REPEAT (S), CLAMP_TO_EDGE (T)
      int W = int(u_dem_size.x), H = int(u_dem_size.y);
      // % tylko na nieujemnych argumentach: w GLSL ES 3.00 (§5.9) wynik dla ujemnych jest niezdefiniowany
      // (Mesa/Intel liczy go jak dla unsigned: -1 % 5760 = 255). g.x >= -2, gx i origin.x w [0, W).
      int gx = (g.x + W) % W, gy = clamp(g.y, 0, H - 1);
      int lx = u_dem_full == 1 ? gx : clamp((gx - int(u_dem_origin.x) + W) % W, 0, int(u_dem_win.x) - 1);
      int ly = clamp(gy - int(u_dem_origin.y), 0, int(u_dem_win.y) - 1);
      return texelFetch(u_tex_dem, ivec2(lx, ly), 0).r;
    }
    float demLinear(vec2 uv) {                                            // = texture() z LINEAR
      vec2 t = uv * u_dem_size - 0.5; vec2 i = floor(t); vec2 f = t - i; ivec2 b = ivec2(i);
      return mix(mix(demTexel(b), demTexel(b + ivec2(1,0)), f.x),
                 mix(demTexel(b + ivec2(0,1)), demTexel(b + ivec2(1,1)), f.x), f.y);
    }
    vec2 albedoUV(vec2 uv) {
      // mod tylko dla okna częściowego; przy pełnym pierścieniu okno = tekstura globalna (S = REPEAT),
      // a skok mod przy lon = ±180° psułby pochodne (wybór mipmapy) wzdłuż południka
      float x = uv.x * u_alb_size.x - u_alb_origin.x;
      return vec2((u_alb_win.x < u_alb_size.x ? mod(x, u_alb_size.x) : x) / u_alb_win.x,
                  (uv.y * u_alb_size.y - u_alb_origin.y) / u_alb_win.y);
    }

    out vec4 out_color;

    vec2 smooth_dem_uv(vec2 uv) {
        vec2 texel = uv * u_dem_size - 0.5;
        vec2 i = floor(texel);
        vec2 f = fract(texel);
        f = f * f * (3.0 - 2.0 * f);
        return (i + f + 0.5) / u_dem_size;
    }

    vec2 body_to_uv(vec3 p) {
        float lat_p = asin(clamp(p.z, -1.0, 1.0));
        float lon_p = atan(p.y, p.x);
        return vec2((lon_p + PI) / TWO_PI, clamp((PI * 0.5 - lat_p) / PI, 0.0, 1.0));
    }

    float hash31(vec3 p) {
        p = fract(p * 0.1031);
        p += dot(p, p.yzx + 33.33);
        return fract((p.x + p.y) * p.z);
    }

    float value_noise3(vec3 x) {
        vec3 i = floor(x);
        vec3 f = fract(x);
        f = f * f * (3.0 - 2.0 * f);
        return mix(
            mix(mix(hash31(i + vec3(0,0,0)), hash31(i + vec3(1,0,0)), f.x),
                mix(hash31(i + vec3(0,1,0)), hash31(i + vec3(1,1,0)), f.x), f.y),
            mix(mix(hash31(i + vec3(0,0,1)), hash31(i + vec3(1,0,1)), f.x),
                mix(hash31(i + vec3(0,1,1)), hash31(i + vec3(1,1,1)), f.x), f.y),
            f.z
        );
    }

    void main() {
        float lat = v_lat_lon.x;
        float lon = v_lat_lon.y;
        vec2 uv_alb = vec2((lon + PI) / TWO_PI, clamp((PI * 0.5 - lat) / PI, 0.0, 1.0));

        // 1. Native albedo texture sampling + calibrated regolith brightness
        vec3 tex_alb = texture(u_tex_albedo, albedoUV(uv_alb)).rgb;
        vec3 albedo = (u_albedo_raw_u8 == 1)
            ? (0.042 + 0.195 * pow(tex_alb, vec3(1.20)))
            : (tex_alb * u_albedo_scale * 0.86);

        // 2. Procedural micro-detail regolith grain at close range (fades with distance)
        vec3 u_b = normalize(v_u_body);
        float dist_km = length(v_pos_enu);
        float detail_fade = smoothstep(35.0, 0.15, dist_km);
        if (detail_fade > 0.001) {
            float n1 = value_noise3(u_b * 4500.0) - 0.5;   // ~2.4 km scale
            float n2 = value_noise3(u_b * 28000.0) - 0.5;  // ~390 m scale
            float n3 = value_noise3(u_b * 160000.0) - 0.5; // ~68 m scale
            float grain = (0.55 * n1 + 0.30 * n2 + 0.15 * n3) * 0.24 * detail_fade;
            albedo *= (1.0 + grain);
        }

        // 3. Singularity-free 3D tangent-plane normal directly from NASA LOLA DEM
        float eps_rad = PI / u_dem_size.y;
        vec3 e_b = normalize(v_east_body);
        vec3 n_b = normalize(v_north_body);

        float h_e1 = demLinear(smooth_dem_uv(body_to_uv(normalize(u_b + eps_rad * e_b))));
        float h_e0 = demLinear(smooth_dem_uv(body_to_uv(normalize(u_b - eps_rad * e_b))));
        float h_n1 = demLinear(smooth_dem_uv(body_to_uv(normalize(u_b + eps_rad * n_b))));
        float h_n0 = demLinear(smooth_dem_uv(body_to_uv(normalize(u_b - eps_rad * n_b))));

        float step_km = 2.0 * eps_rad * R_MOON;
        float grad_e = ((h_e1 - h_e0) / step_km) * 1.45;
        float grad_n = ((h_n1 - h_n0) / step_km) * 1.45;

        vec3 u_n = normalize(v_u_pt);
        vec3 e_n = normalize(v_east_pt);
        vec3 n_n = normalize(v_north_pt);
        vec3 N = normalize(u_n - grad_e * e_n - grad_n * n_n);

        // 4. Regolith scattering model (Lommel-Seeliger + Lambert) with deep airless shadows
        vec3 V = normalize(-v_pos_enu);
        float mu0 = max(0.0, dot(N, u_sun_enu));
        float mu  = max(0.0, dot(N, V));
        float lommel = (1.45 * mu0) / (mu0 + max(0.45, mu));
        float lambert = pow(mu0, 0.88);
        float direct = mix(lambert, lommel, 0.50) * u_sun_effective_vis;

        float earth_facing = 0.35 + 0.65 * max(0.0, dot(N, u_earth_enu));
        float ambient = 0.012 + u_earthshine * earth_facing;

        float base_light = 140.0 * ambient + 810.0 * direct;
        vec3 lit = clamp(albedo * base_light * u_tint, 1.0, 245.0) / 255.0;
        out_color = vec4(clamp(lit + u_wire_add, 0.0, 1.0), 1.0);
    }
`;

// geografia.py:1464-1478
export const HORIZON_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    in vec3 in_enu;
    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;
    uniform vec2 u_offset_px;   // odchylenie 4: linia 2 px = 4 przejscia z offsetem 0/1 px
    uniform vec2 u_viewport;
    void main() {
        float zc = dot(in_enu, u_fwd);
        float xc = dot(in_enu, u_right);
        float yc = dot(in_enu, u_cam_up);
        gl_Position = vec4(xc / u_tan_x, yc / u_tan_y, 0.0, zc);
        gl_Position.xy += u_offset_px * 2.0 / u_viewport * gl_Position.w;
    }
`;

// geografia.py:1480-1486
export const HORIZON_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    out vec4 out_color;
    void main() {
        out_color = vec4(90.0 / 255.0, 175.0 / 255.0, 220.0 / 255.0, 1.0);
    }
`;

// geografia.py:527-578
export const STAR_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    in vec3 in_ecl;
    in float in_mag;

    uniform mat3 u_R_body;
    uniform vec3 u_north;
    uniform vec3 u_east;
    uniform vec3 u_up;
    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_cw;
    uniform float u_ch;
    uniform float u_focal;

    out float v_mag;

    void main() {
        vec3 sb = u_R_body * in_ecl;
        float sn = dot(sb, u_north);
        float se = dot(sb, u_east);
        float su = dot(sb, u_up);

        float s_alt = asin(clamp(su, -1.0, 1.0));
        if (s_alt <= -0.1) {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            v_mag = 0.0;
            return;
        }
        float s_az = atan(se, sn);
        float ca = cos(s_alt);
        vec3 p = vec3(ca * cos(s_az), ca * sin(s_az), sin(s_alt));

        float z_cam = dot(p, u_fwd);
        if (z_cam <= 0.05) {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            v_mag = 0.0;
            return;
        }
        float x_cam = dot(p, u_right);
        float y_cam = dot(p, u_cam_up);
        float sx = u_cw * 0.5 + (x_cam / z_cam) * u_focal;
        float sy = u_ch * 0.5 - (y_cam / z_cam) * u_focal;

        gl_Position = vec4((sx / u_cw) * 2.0 - 1.0, 1.0 - (sy / u_ch) * 2.0, 0.0, 1.0);
        gl_PointSize = 1.0;
        v_mag = in_mag;
    }
`;

// geografia.py:580-587
export const STAR_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    in float v_mag;
    out vec4 out_color;
    void main() {
        out_color = vec4(v_mag, v_mag, v_mag, 1.0);
    }
`;

// geografia.py:589-605
export const GRID_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    in vec3 in_enu;

    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;

    void main() {
        float zc = dot(in_enu, u_fwd);
        float xc = dot(in_enu, u_right);
        float yc = dot(in_enu, u_cam_up);
        gl_Position = vec4(xc / u_tan_x, yc / u_tan_y, 0.0, zc);
    }
`;

// geografia.py:607-614
export const GRID_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    uniform vec4 u_color;
    out vec4 out_color;
    void main() {
        out_color = u_color;
    }
`;

// geografia.py:616-625
export const QUAD_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    in vec2 in_pos;
    in vec2 in_uv;
    out vec2 v_uv;
    void main() {
        gl_Position = vec4(in_pos, 0.0, 1.0);
        v_uv = in_uv;
    }
`;

// geografia.py:627-664
export const SUN_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    uniform float u_sx;
    uniform float u_sy;
    uniform float u_r_sun;
    uniform float u_halo_mult;
    uniform float u_ch;

    out vec4 out_color;

    void main() {
        float px = gl_FragCoord.x - 0.5;
        float py = u_ch - gl_FragCoord.y - 0.5;
        float gx = (px - u_sx) / u_r_sun;
        float gy = (py - u_sy) / u_r_sun;
        float dist = sqrt(gx * gx + gy * gy);

        if (dist <= 1.0) {
            float mu = sqrt(clamp(1.0 - dist * dist, 0.0, 1.0));
            float limb_dark = 0.45 + 0.55 * pow(mu, 0.50);
            if (u_r_sun > 18.0) {
                float granulation = 0.028 * sin(gx * 55.0) * cos(gy * 55.0);
                limb_dark = clamp(limb_dark + granulation, 0.25, 1.05);
            }
            float r = clamp(min(1.0, limb_dark * 1.06), 0.0, 1.0);
            float g = clamp((246.0 / 255.0) * limb_dark, 0.0, 1.0);
            float b = clamp((218.0 / 255.0) * pow(limb_dark, 1.15), 0.0, 1.0);
            out_color = vec4(r, g, b, 1.0);
        } else if (dist <= u_halo_mult) {
            float t_c = (dist - 1.0) / (u_halo_mult - 1.0);
            float glow = exp(-2.6 * t_c) * (1.0 - t_c);
            float alpha = clamp((220.0 / 255.0) * glow, 0.0, 1.0);
            out_color = vec4(1.0, 228.0 / 255.0, 165.0 / 255.0, alpha);
        } else {
            discard;
        }
    }
`;

// geografia.py:666-834
export const EARTH_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
    const float PI = 3.14159265358979323846;
    const float R_EARTH = 6371.0;
    const float R_MOON = 1737.4;
    const float R_SUN = 696340.0;

    uniform float u_ex;
    uniform float u_ey;
    uniform float u_r_earth;
    uniform float u_ch;

    uniform vec3 u_e_x_cam;
    uniform vec3 u_e_y_cam;
    uniform vec3 u_e_z_cam;

    uniform vec3 u_x_ecef;
    uniform vec3 u_y_ecef;
    uniform vec3 u_z_ecef;

    uniform vec3 u_sun_from_earth_enu;
    uniform vec3 u_moon_from_earth_enu;
    uniform float u_moon_sun_dot;
    uniform float u_sun_dist_km;
    uniform float u_cloud_offset;
    uniform float u_eclipse_ring_factor;
    uniform float u_dark_side_exposure;

    uniform int u_has_day;
    uniform int u_has_night;
    uniform int u_has_clouds;
    uniform float u_night_lod;

    uniform sampler2D u_tex_day;
    uniform sampler2D u_tex_night;
    uniform sampler2D u_tex_clouds;

    out vec4 out_color;

    void main() {
        float px = gl_FragCoord.x - 0.5;
        float py = u_ch - gl_FragCoord.y - 0.5;
        float gx = (px - u_ex) / u_r_earth;
        float gy = (py - u_ey) / u_r_earth;
        float dist_sq = gx * gx + gy * gy;

        if (dist_sq <= 1.0) {
            float gz = sqrt(1.0 - dist_sq);
            vec3 n_enu = gx * u_e_x_cam - gy * u_e_y_cam + gz * u_e_z_cam;

            float px_e = dot(n_enu, u_x_ecef);
            float py_e = dot(n_enu, u_y_ecef);
            float pz_e = dot(n_enu, u_z_ecef);

            float lat_pt = asin(clamp(pz_e, -1.0, 1.0));
            float lon_pt = atan(py_e, px_e);

            float u = (lon_pt + PI) / (2.0 * PI);
            float v = (PI * 0.5 - lat_pt) / PI;

            vec3 day_rgb;
            if (u_has_day == 1) {
                day_rgb = texture(u_tex_day, vec2(u, v)).rgb;
            } else {
                float continent = sin(lon_pt * 2.1 + 0.4) * cos(lat_pt * 2.3)
                                + 0.55 * cos(lon_pt * 4.7 - 1.1) * sin(lat_pt * 3.8 + 0.3)
                                + 0.30 * sin(lon_pt * 9.0 + lat_pt * 7.0);
                bool is_land = continent > 0.18;
                bool is_ice = abs(lat_pt) > radians(72.0 - 8.0 * continent);
                day_rgb = vec3(22.0 / 255.0, 72.0 / 255.0, 158.0 / 255.0);
                if (is_land) day_rgb = vec3(64.0 / 255.0, 118.0 / 255.0, 62.0 / 255.0);
                if (is_ice) day_rgb = vec3(235.0 / 255.0, 242.0 / 255.0, 248.0 / 255.0);
            }

            vec3 night_rgb;
            if (u_has_night == 1) {
                vec3 raw_night = textureLod(u_tex_night, vec2(u, v), u_night_lod).rgb;
                vec3 clean_night = clamp((raw_night - 0.055) / 0.945, 0.0, 1.0);
                night_rgb = pow(clean_night, vec3(0.88)) * (1.15 * u_dark_side_exposure);
            } else {
                float continent = sin(lon_pt * 2.1 + 0.4) * cos(lat_pt * 2.3)
                                + 0.55 * cos(lon_pt * 4.7 - 1.1) * sin(lat_pt * 3.8 + 0.3);
                bool urban = (continent > 0.22)
                          && (abs(lat_pt) < radians(60.0))
                          && (sin(lon_pt * 28.0) * cos(lat_pt * 34.0) > 0.65);
                night_rgb = urban ? vec3(235.0 / 255.0, 175.0 / 255.0, 80.0 / 255.0) * u_dark_side_exposure
                                  : vec3(0.0);
            }

            float cos_sun = dot(n_enu, u_sun_from_earth_enu);
            float twilight_t = clamp((cos_sun + 0.07) / 0.15, 0.0, 1.0);
            float day_blend = twilight_t * twilight_t * (3.0 - 2.0 * twilight_t);
            float sun_diffuse = pow(clamp(cos_sun, 0.0, 1.0), 0.78);

            if (u_moon_sun_dot > 0.0) {
                vec3 pts_earth_km = R_EARTH * n_enu;
                vec3 rel_to_moon = pts_earth_km - u_moon_from_earth_enu;
                float along_sun = dot(rel_to_moon, u_sun_from_earth_enu);
                if (along_sun < 0.0) {
                    float dist_behind = -along_sun;
                    vec3 perp_vec = rel_to_moon + dist_behind * u_sun_from_earth_enu;
                    float perp_dist = length(perp_vec);

                    float r_penumbra = R_MOON + dist_behind * (R_SUN + R_MOON) / max(1.0, u_sun_dist_km);
                    float r_umbra = max(0.0, R_MOON - dist_behind * (R_SUN - R_MOON) / max(1.0, u_sun_dist_km));

                    if (perp_dist < r_penumbra) {
                        float pen_t = clamp(
                            (perp_dist - r_umbra) / max(r_penumbra - r_umbra, 1.0),
                            0.0,
                            1.0
                        );
                        float shadow_atten = 0.08 + 0.92 * (pen_t * pen_t * (3.0 - 2.0 * pen_t));
                        sun_diffuse *= shadow_atten;
                    }
                }
            }

            float terminator_glow = (cos_sun > -0.08) ? exp(-pow((cos_sun - 0.01) / 0.095, 2.0)) : 0.0;

            vec3 lit_day_rgb = day_rgb * (0.02 + 0.98 * sun_diffuse);
            lit_day_rgb.r += (36.0 / 255.0) * terminator_glow;
            lit_day_rgb.g += (12.0 / 255.0) * terminator_glow;

            if (u_has_clouds == 1) {
                float u_cloud = fract(u - u_cloud_offset);
                float c_raw = texture(u_tex_clouds, vec2(u_cloud, v)).r;
                float cloud_alpha = pow(clamp((c_raw - 0.04) / 0.96, 0.0, 1.0), 0.90) * 0.92;

                vec3 cloud_lit_rgb = vec3(
                    (252.0 / 255.0) * (0.03 + 0.97 * sun_diffuse) + (46.0 / 255.0) * terminator_glow,
                    (253.0 / 255.0) * (0.03 + 0.97 * sun_diffuse) + (16.0 / 255.0) * terminator_glow,
                    1.0 * (0.04 + 0.96 * sun_diffuse)
                );
                lit_day_rgb = mix(lit_day_rgb, cloud_lit_rgb, cloud_alpha);
                night_rgb *= (1.0 - 0.55 * cloud_alpha);
            }

            float twilight_cities = pow(clamp((0.04 - cos_sun) / 0.14, 0.0, 1.0), 1.4);
            vec3 out_rgb = lit_day_rgb * day_blend + night_rgb * twilight_cities;

            float limb_geom = pow(1.0 - gz, 2.6);
            float day_limb = limb_geom * clamp(cos_sun + 0.22, 0.0, 1.0) * (1.0 - 0.75 * u_eclipse_ring_factor);
            float ecl_limb = limb_geom * u_eclipse_ring_factor;

            out_rgb.r += (75.0 / 255.0) * day_limb + (245.0 / 255.0) * ecl_limb;
            out_rgb.g += (155.0 / 255.0) * day_limb + (95.0 / 255.0) * ecl_limb;
            out_rgb.b += (250.0 / 255.0) * day_limb + (35.0 / 255.0) * ecl_limb;

            out_color = vec4(clamp(out_rgb, 0.0, 1.0), 1.0);
        } else if (dist_sq <= 1.28) {
            float dist_h = sqrt(dist_sq);
            float h_fade = pow(clamp(1.0 - (dist_h - 1.0) / 0.13, 0.0, 1.0), 2.0);
            vec3 n_halo = gx * u_e_x_cam - gy * u_e_y_cam;
            float sun_facing = clamp(dot(n_halo, u_sun_from_earth_enu) + 0.30, 0.04, 1.0);
            float halo_strength = max(sun_facing, 0.85 * u_eclipse_ring_factor);

            vec3 halo_col = mix(
                vec3(75.0 / 255.0, 155.0 / 255.0, 250.0 / 255.0),
                vec3(235.0 / 255.0, 88.0 / 255.0, 32.0 / 255.0),
                u_eclipse_ring_factor
            );
            float alpha = clamp((150.0 / 255.0) * h_fade * halo_strength, 0.0, 1.0);
            out_color = vec4(halo_col, alpha);
        } else {
            discard;
        }
    }
`;
