/*
 * HVIF (Haiku Vector Icon Format) parser + SVG renderer, client-side.
 *
 * Author: 3dEyes** (Gerasim Troeglazov) <3dEyes@gmail.com>
 * Source: https://hvif-store.art  (see also https://github.com/threedeyes/hvif-tools)
 * License: MIT
 *
 * Vendored into spritz to render app icons as SVG in the browser, so no
 * server-side hvif2png is required. Redistributed under the MIT License; the
 * copyright and this notice are retained per the license terms.
 */
(function() {
    const HaikonParser = (() => {
        const C = {
            Color: { RGBA: 1, RGB: 3, KA: 4, K: 5 },
            Style: { GRADIENT: 2 },
            GradFlag: { transform: 2, noAlpha: 4, greys: 16 },
            PathFlag: { closed: 2, commands: 4, noCurves: 8 },
            PathCmd: { VLINE: 0, HLINE: 1, LINE: 2, CURVE: 3 },
            ShapeFlag: { matrix: 2, lodScale: 8, transformers: 16, translate: 32 },
            TransType: { AFFINE: 20, CONTOUR: 21, PERSPECTIVE: 22, STROKE: 23 },
            LineJoin: { miter: 0, round: 2, bevel: 3 },
            LineCap: { butt: 0, square: 1, round: 2 },
            GradType: { linear: 0, radial: 1, diamond: 2, conic: 3, xy: 4, sqrtxy: 5 }
        };

        const _dv = new DataView(new ArrayBuffer(4));

        function parseIcon(buf, filename = null) {
            let p = 0;
            if (buf[0] !== 110 || buf[1] !== 99 || buf[2] !== 105 || buf[3] !== 102) throw new Error("Not a HVIF file");
            p = 4;

            function readArr(n, fn) {
                const r = new Array(n);
                for (let i = 0; i < n; i++) r[i] = fn();
                return r;
            }

            function readFloat24() {
                const v = (buf[p] << 16) | (buf[p + 1] << 8) | buf[p + 2];
                p += 3;
                if (v === 0) return 0.0;
                const ieee = ((v & 0x800000) >>> 23) << 31 | ((((v & 0x7e0000) >>> 17) - 32 + 127) << 23) | ((v & 0x01ffff) << 6);
                _dv.setUint32(0, ieee);
                return _dv.getFloat32(0);
            }

            const readM6 = () => readArr(6, readFloat24);
            const readM9 = () => readArr(9, readFloat24);

            function readCoords(n) {
                const r = new Array(n);
                for (let i = 0; i < n; i++) {
                    let v = buf[p++];
                    if (v >= 128) {
                        v = ((v & 127) << 8) | buf[p++];
                        r[i] = v - 13056; 
                    } else r[i] = v * 102 - 3264;
                }
                return r;
            }

            const styles = readArr(buf[p++], () => {
                let t = buf[p++];
                if (t === C.Style.GRADIENT) {
                    let [type, fl, n] = buf.slice(p, p += 3);
                    let fmt = (fl & C.GradFlag.greys) ? ((fl & C.GradFlag.noAlpha) ? C.Color.K : C.Color.KA) : ((fl & C.GradFlag.noAlpha) ? C.Color.RGB : C.Color.RGBA);
                    return {
                        tag: 2, type,
                        matrix: (fl & C.GradFlag.transform) ? readM6() : null,
                        stops: readArr(n, () => ({ off: buf[p++], col: readColor(fmt) })).sort((a, b) => a.off - b.off)
                    };
                }
                return readColor(t);
            });

            const paths = readArr(buf[p++], () => {
                let [fl, n] = buf.slice(p, p += 2);
                let pts = (fl & C.PathFlag.noCurves) ? readCoords(n * 2) : (fl & C.PathFlag.commands) ? readCmds(n) : readCoords(n * 6);
                return { type: (fl & C.PathFlag.noCurves) ? "points" : "curves", points: pts, closed: !!(fl & C.PathFlag.closed) };
            });

            const shapes = readArr(buf[p++], () => {
                let [type, sIdx, n] = buf.slice(p, p += 3);
                if (type !== 10) throw new Error("Unknown shape");
                let idxs = new Array(n);
                for (let i = 0; i < n; i++) idxs[i] = buf[p++];
                let fl = buf[p++], sh = { styleIndex: sIdx, pathIndices: idxs };

                if (fl & C.ShapeFlag.matrix) sh.transform = { tag: "matrix", data: readM6() };
                else if (fl & C.ShapeFlag.translate) sh.transform = { tag: "translate", data: readCoords(2) };

                if (fl & C.ShapeFlag.lodScale) {
                    sh.minLod = buf[p++] / 63.75;
                    sh.maxLod = buf[p++] / 63.75;
                }

                if (fl & C.ShapeFlag.transformers) sh.transformers = readArr(buf[p++], readTrans);
                return sh;
            });

            function readColor(t) {
                const l = [0, 4, 0, 3, 2, 1][t];
                const c = [t];
                for (let i = 0; i < l; i++) c.push(buf[p++]);
                return c;
            }

            function readCmds(n) {
                const nBytes = Math.ceil(n / 4);
                const cmds = [];
                for (let i = 0; i < nBytes; i++) {
                    let b = buf[p++];
                    cmds.push(b & 3, (b >> 2) & 3, (b >> 4) & 3, (b >> 6) & 3);
                }
                const pts = [], tmp = [0, 0, 0, 0, 0, 0];
                for (let i = 0; i < n; i++) {
                    const cmd = cmds[i];
                    const c = readCoords(cmd === C.PathCmd.CURVE ? 6 : 1);
                    if (cmd === C.PathCmd.VLINE) {
                        tmp[0] = tmp[2] = tmp[4] = c[0];
                        tmp[3] = tmp[5] = tmp[1];
                    } else if (cmd === C.PathCmd.HLINE) {
                        tmp[1] = tmp[3] = tmp[5] = c[0];
                        tmp[2] = tmp[4] = tmp[0];
                    } else if (cmd === C.PathCmd.LINE) { 
                        tmp[0] = tmp[2] = tmp[4] = c[0]; 
                        tmp[1] = tmp[3] = tmp[5] = readCoords(1)[0]; 
                    } else for (let k = 0; k < 6; k++) tmp[k] = c[k];
                    pts.push(...tmp);
                }
                return pts;
            }

            function readTrans() {
                let t = buf[p++];
                if (t === C.TransType.AFFINE) return { tag: "affine", matrix: readM6() };
                if (t === C.TransType.PERSPECTIVE) return { tag: "perspective", matrix: readM9() };
                let [w, j, l] = buf.slice(p, p += 3);
                let tr = { tag: t === C.TransType.CONTOUR ? "contour" : "stroke", width: (w - 128) * 102, miterLimit: l };
                if (t === C.TransType.CONTOUR) tr.lineJoin = j;
                else { tr.lineJoin = j & 15; tr.lineCap = j >> 4; }
                return tr;
            }

            return { filename, styles, paths, shapes, constants: C };
        }
        return { parse: parseIcon, constants: C };
    })();

    const HaikonSvgRenderer = (() => {
        const { Color: CT, GradType: GT } = HaikonParser.constants;
        const SCALE = 102.0;
        
        const F = n => Math.round(n * 100) / 100;
        const F6 = n => Math.round(n * 1000000) / 1000000;

        function transform(x, y, stack) {
            let tx = x / SCALE, ty = y / SCALE;
            for (let t of stack) {
                if (t.tag === "affine" || t.tag === "matrix") {
                    let m = t.matrix || t.data;
                    let _x = tx, _y = ty;
                    tx = _x * m[0] + _y * m[2] + m[4];
                    ty = _x * m[1] + _y * m[3] + m[5];
                } else if (t.tag === "perspective") {
                    let m = t.matrix;
                    let _x = tx, _y = ty;
                    let w = _x * m[2] + _y * m[5] + m[8];
                    if (Math.abs(w) < 1e-9) w = 1.0;
                    tx = (_x * m[0] + _y * m[3] + m[6]) / w;
                    ty = (_x * m[1] + _y * m[4] + m[7]) / w;
                }
            }
            return [tx * SCALE, ty * SCALE];
        }

        function getScale(stack) {
            let s = 1.0;
            for (let t of stack) {
                if (t.tag === "affine" || t.tag === "matrix") {
                    let m = t.matrix || t.data;
                    s *= Math.sqrt(m[0]*m[0] + m[1]*m[1]);
                }
            }
            return s;
        }

        function multM(a, b) {
            return [
                a[0] * b[0] + a[1] * b[2],
                a[0] * b[1] + a[1] * b[3],
                a[2] * b[0] + a[3] * b[2],
                a[2] * b[1] + a[3] * b[3],
                a[4] * b[0] + a[5] * b[2] + b[4],
                a[4] * b[1] + a[5] * b[3] + b[5]
            ];
        }

        function col(v) {
            let t = v[0], r, g, b, a = 1;
            if (t === CT.KA) { r = g = b = v[1]; a = v[2] / 255; }
            else if (t === CT.K) { r = g = b = v[1]; }
            else { r = v[1]; g = v[2]; b = v[3]; if(t === CT.RGBA) a = v[4] / 255; }
            const toHex = c => c.toString(16).padStart(2, "0");
            return { h: "#" + toHex(r) + toHex(g) + toHex(b), a: F(a) };
        }

        function* genPath(paths, stack) {
            for (let p of paths) {
                let pts = p.points;
                if (!pts || !pts.length) continue;

                if (p.type === "points") {
                    let [sx, sy] = transform(pts[0], pts[1], stack);
                    yield* ["M", F(sx), F(sy), "L"];
                    for (let i = 2; i < pts.length; i += 2) {
                        let [px, py] = transform(pts[i], pts[i + 1], stack);
                        yield* [F(px), F(py)];
                    }
                    if (p.closed) yield "Z";
                } else {
                    let start = pts.slice(0, 6);
                    let [sx, sy] = transform(start[0], start[1], stack);
                    let [sox, soy] = transform(start[4], start[5], stack);
                    yield* ["M", F(sx), F(sy)];
                    let pox = sox, poy = soy;
                    for (let i = 0; i < pts.length; i += 6) {
                        if (i === 0) {
                            let s = pts.slice(0, 6);
                            let t = transform(s[4], s[5], stack);
                            pox = t[0]; poy = t[1];
                            continue;
                        }
                        let s = pts.slice(i, i + 6);
                        let [cx, cy] = transform(s[0], s[1], stack);
                        let [cix, ciy] = transform(s[2], s[3], stack);
                        let [cox, coy] = transform(s[4], s[5], stack);
                        yield* ["C", F(pox), F(poy), F(cix), F(ciy), F(cx), F(cy)];
                        pox = cox; poy = coy;
                    }
                    if (p.closed) {
                        let [six, siy] = transform(start[2], start[3], stack);
                        yield* ["C", F(pox), F(poy), F(six), F(siy), F(sx), F(sy), "Z"];
                    }
                }
            }
        }

        function createRenderer(domContext) {
            const el = (ns, t, ats = {}) => {
                let e = domContext(ns, t);
                for (let k in ats) e.setAttribute(k, ats[k]);
                return e;
            };
            const svgNS = "http://www.w3.org/2000/svg";
            const htmlNS = "http://www.w3.org/1999/xhtml";

            function renderIcon(data, size = 64, id = "i" + (Math.random() * 1e9 | 0)) {
                let svg = el(svgNS, "svg", { 
                    id, 
                    width: "64", height: "64",
                    viewBox: "0 0 6528 6528", 
                    style: "width:2em;height:2em"
                });
                const scale = size / 64.0;
                data.shapes.forEach((s, idx) => {
                    if (s.minLod !== undefined && (scale < s.minLod || (s.maxLod < 4.0 && scale > s.maxLod))) return;
                    svg.append(renderShape(s, data, id + "-" + idx));
                });
                return el(htmlNS, "span", { class: "haikon" }).appendChild(svg).parentNode;
            }

            function renderShape(sh, data, uid) {
                let stack = [...(sh.transformers || [])];
                if (sh.transform) {
                    if (sh.transform.tag === "translate") {
                        let [tx, ty] = sh.transform.data;
                        stack.push({ tag: "affine", matrix: [1, 0, 0, 1, tx / 102, ty / 102] });
                    } else stack.push(sh.transform);
                }

                let d = [...genPath(sh.pathIndices.map(i => data.paths[i]), stack)].join(" ");
                let path = el(svgNS, "path", { d });

                let eff = { tag: "fill" };
                for (let t of sh.transformers || []) if (t.tag === "stroke" || t.tag === "contour") eff = t;

                let sty = data.styles[sh.styleIndex], fill = "", def = null, opacity = 1;
                if (sty.tag === 2) {
                    let gid = uid + "-g";
                    def = renderGrad(sty, gid, stack);
                    fill = `url(#${gid})`;
                } else {
                    let c = col(sty);
                    fill = c.h;
                    opacity = c.a;
                }

                let w = F(Math.abs(eff.width || 0) * getScale(stack));
                
                let css = `stroke-width:${w};stroke-linejoin:${["miter", "miter", "round", "bevel"][eff.lineJoin] || "miter"};stroke-linecap:${["butt", "square", "round"][eff.lineCap] || "butt"};`;

                if (eff.tag === "contour") {
                    css += eff.width < 0 ? "stroke:black;fill:white;" : "stroke:white;fill:white;";
                    path.setAttribute("style", css);
                    let mid = uid + "-m";
                    let mask = el(svgNS, "mask", { id: mid, maskUnits: "userSpaceOnUse", x: 0, y: 0, width: 6528, height: 6528 });
                    mask.append(path);
                    let g = el(svgNS, "g");
                    let rectAts = { x: 0, y: 0, width: 6528, height: 6528, fill, mask: `url(#${mid})` };
                    if(opacity < 1) rectAts["fill-opacity"] = opacity;
                    g.append(mask, el(svgNS, "rect", rectAts));
                    if (def) g.append(def);
                    return g;
                }

                if (eff.tag === "stroke") {
                    css += `stroke:${fill};fill:none;`;
                    if(opacity < 1) css += `stroke-opacity:${opacity};`;
                } else {
                    css += `fill:${fill};stroke:none;`;
                    if(opacity < 1) css += `fill-opacity:${opacity};`;
                }
                
                path.setAttribute("style", css);
                if (def) { let g = el(svgNS, "g"); g.append(def, path); return g; }
                return path;
            }

            function renderGrad({ type, stops, matrix }, id, stack) {
                let isLin = type === GT.linear || type > 2; 
                let isInv = type > 2;
                
                let g = el(svgNS, isLin ? "linearGradient" : "radialGradient", { id, gradientUnits: "userSpaceOnUse" });

                let m = matrix ? [...matrix] : [1, 0, 0, 1, 0, 0];
                if (stack) {
                    for (let t of stack) {
                        let tm = null;
                        if (t.tag === "affine" || t.tag === "matrix") {
                            tm = t.matrix || t.data;
                        } else if (t.tag === "perspective") {
                            let p = t.matrix;
                            let w = m[4] * p[2] + m[5] * p[5] + p[8];
                            if (Math.abs(w) < 1e-9) w = 1.0;
                            tm = [ p[0]/w, p[1]/w, p[3]/w, p[4]/w, p[6]/w, p[7]/w ];
                        }
                        if (tm) m = multM(m, tm);
                    }
                }

                g.setAttribute("gradientTransform", `matrix(${F6(m[0])},${F6(m[1])},${F6(m[2])},${F6(m[3])},${F(m[4] * 102)},${F(m[5] * 102)})`);
                
                if (isLin) { 
                    if (isInv) {
                        g.setAttribute("x1", 6528); g.setAttribute("x2", -6528); 
                        g.setAttribute("y1", -6528); g.setAttribute("y2", -6528);
                    } else {
                        g.setAttribute("x1", -6528); g.setAttribute("x2", 6528); 
                        g.setAttribute("y1", -6528); g.setAttribute("y2", -6528); 
                    }
                }
                else { 
                    g.setAttribute("cx", 0); g.setAttribute("cy", 0); g.setAttribute("r", 6528); 
                }
                
                stops.forEach(s => {
                    let c = col(s.col);
                    let ats = { offset: F(s.off / 2.55) + "%", "stop-color": c.h };
                    if(c.a < 1) ats["stop-opacity"] = c.a;
                    g.append(el(svgNS, "stop", ats));
                });
                return g;
            }
            return { renderIcon };
        }
        return { _renderers: createRenderer };
    })();

    globalThis.Haikon = HaikonParser;
    const internalRenderer = HaikonSvgRenderer._renderers(document.createElementNS.bind(document));
    globalThis.HaikonSvg = Object.assign(HaikonSvgRenderer, internalRenderer);
})();
