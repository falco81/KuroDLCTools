#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
viewer_mdl.py — Direct .mdl preview without intermediate .fmt/.vb/.ib

Dependencies (shared with your MDL utility):
  - kuro_mdl_export_meshes.py  (in the same directory)
  - lib_fmtibvb.py             (in the same directory, imported by the parser)
  - blowfish, zstandard        (for CLE assets: pip install blowfish zstandard)

Usage:
  python viewer_mdl.py /path/to/model.mdl [--use-original-normals]

Output:
  - Generates HTML preview:  <mdl_basename>_viewer.html
  - Tries to open it in the default web browser
"""

from pathlib import Path
import sys
import json
import numpy as np

# Import ONLY the necessary functions from your parser
from kuro_mdl_export_meshes import decryptCLE, obtain_material_data, obtain_mesh_data  # type: ignore


# -----------------------------
# Smooth normals (lightweight version)
# -----------------------------
def compute_smooth_normals_with_sharing(vertices: np.ndarray, indices: np.ndarray, tolerance: float = 1e-6) -> np.ndarray:
    """Compute smooth normals with position sharing (within given tolerance)."""
    from collections import defaultdict

    position_map = {}
    vertex_to_position = {}
    for idx, v in enumerate(vertices):
        key = tuple(np.round(v / tolerance) * tolerance)
        position_map.setdefault(key, []).append(idx)
        vertex_to_position[idx] = key

    position_normals = defaultdict(lambda: np.zeros(3, dtype=np.float32))

    # Accumulate face normals per shared position
    for i in range(0, len(indices), 3):
        i0, i1, i2 = int(indices[i]), int(indices[i + 1]), int(indices[i + 2])
        v0, v1, v2 = vertices[i0], vertices[i1], vertices[i2]
        edge1 = v1 - v0
        edge2 = v2 - v0
        face_normal = np.cross(edge1, edge2)
        position_normals[vertex_to_position[i0]] += face_normal
        position_normals[vertex_to_position[i1]] += face_normal
        position_normals[vertex_to_position[i2]] += face_normal

    # Normalize and expand back to per-vertex array
    for k in position_normals:
        n = position_normals[k]
        L = np.linalg.norm(n)
        if L > 0:
            position_normals[k] = n / L

    normals = np.zeros_like(vertices, dtype=np.float32)
    for idx in range(len(vertices)):
        normals[idx] = position_normals[vertex_to_position[idx]]
    return normals


# -----------------------------
# Load MDL → vertices/normals/indices (via your parser)
# -----------------------------
def load_mdl_direct(mdl_path: Path, use_original_normals: bool = False):
    """
    Returns a list of meshes of the form:
      {
        'name': str,
        'vertices': np.ndarray [N,3],
        'normals':  np.ndarray [N,3] or None,
        'indices':  np.ndarray [M] (uint32)
      }
    """
    mdl_path = Path(mdl_path)
    with open(mdl_path, "rb") as f:
        mdl_data = f.read()

    # Decrypt/Decompress CLE container (if applicable)
    mdl_data = decryptCLE(mdl_data)

    # Materials: required by the parser for proper element mapping (not used in the preview itself)
    material_struct = obtain_material_data(mdl_data)

    # Extract mesh structures (contain 'mesh_buffers' with IB/VB and fmt)
    mesh_struct = obtain_mesh_data(mdl_data, material_struct=material_struct)

    meshes = []
    mesh_blocks = mesh_struct.get("mesh_blocks", [])
    all_buffers = mesh_struct.get("mesh_buffers", [])

    for i, submesh_list in enumerate(all_buffers):
        # Mesh block name (e.g., "body", "hair") if available
        base_name = mesh_blocks[i].get("name", f"mesh_{i}") if i < len(mesh_blocks) else f"mesh_{i}"

        for j, submesh in enumerate(submesh_list):
            vb = submesh.get("vb", [])
            ib = submesh.get("ib", {}).get("Buffer", [])

            # Find POSITION and (optionally) NORMAL
            pos_buffer = None
            normal_buffer = None

            for element in vb:
                sem = element.get("SemanticName")
                buf = element.get("Buffer")
                if sem == "POSITION":
                    pos_buffer = buf
                elif sem == "NORMAL":
                    normal_buffer = buf

            if not pos_buffer:
                # Without positions we can't render anything
                continue

            # Positions — take first 3 components
            vertices = np.array([p[:3] for p in pos_buffer], dtype=np.float32)

            # Indices — stored in triangles; flatten to 1D index buffer
            flat_indices = []
            for tri in ib:
                if len(tri) == 3:
                    flat_indices.extend(tri)
            indices = np.array(flat_indices, dtype=np.uint32)

            # Normals — use original if requested and present, otherwise compute
            if use_original_normals and normal_buffer:
                normals = np.array([n[:3] for n in normal_buffer], dtype=np.float32)
                # Ensure unit-length (SNORM may be pre-normalized, normalize just in case)
                lens = np.linalg.norm(normals, axis=1)
                nonzero = lens > 1e-8
                normals[nonzero] = normals[nonzero] / lens[nonzero][:, None]
            else:
                normals = compute_smooth_normals_with_sharing(vertices, indices) if len(indices) >= 3 else None

            meshes.append({
                "name": f"{i}_{base_name}_{j:02d}",
                "vertices": vertices,
                "normals": normals,
                "indices": indices
            })

    return meshes


# -----------------------------
# Export HTML (Three.js) – fixed script tag + fixed toggleColors()
# -----------------------------
def export_html_from_meshes(mdl_path: Path, meshes: list):
    """
    Create an HTML file <mdl_basename>_viewer.html with (positions, normals, indices).
    The template uses safe JS string concatenation (no backtick template strings).
    """

    # Build the JSON payload for the client-side renderer
    meshes_data = []
    for m in meshes:
        if m["vertices"] is None or m["indices"] is None:
            continue
        verts = m["vertices"]
        norms = m["normals"]
        idxs = m["indices"]
        if norms is None:
            # As a fallback, compute normals here (just in case)
            norms = compute_smooth_normals_with_sharing(verts, idxs)
        meshes_data.append({
            "name": m["name"],
            "vertices": verts.astype(np.float32).flatten().tolist(),
            "normals": norms.astype(np.float32).flatten().tolist(),
            "indices": idxs.astype(np.uint32).tolist()
        })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Model Viewer - MDL direct</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, sans-serif; overflow: hidden; background: #1a1a2e; }}
    #container {{ width: 100vw; height: 100vh; }}
    .panel {{ position: absolute; background: rgba(20,20,35,0.95); color: #e0e0e0;
              padding: 18px; border-radius: 10px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }}
    #info {{ top: 20px; left: 20px; max-width: 300px; }}
    #controls {{ top: 20px; right: 20px; max-height: 85vh; overflow-y: auto; }}
    #stats {{ bottom: 20px; left: 20px; font-family: monospace; font-size: 12px; }}
    h3 {{ margin: 0 0 12px 0; color: #7c3aed; font-size: 16px; }}
    h4 {{ margin: 15px 0 10px 0; padding-bottom: 8px; border-bottom: 1px solid rgba(124, 58, 237, 0.3);
          font-size: 14px; color: #a78bfa; font-weight: 500; }}
    button {{ background: linear-gradient(135deg, #7c3aed, #a855f7); border: none;
             color: white; padding: 10px; margin: 5px 0; cursor: pointer;
             border-radius: 6px; width: 100%; font-weight: 600; }}
    button:hover {{ transform: translateY(-1px); }}
    .mesh-toggle {{
      display: flex;
      align-items: center;
      margin: 8px 0;
      padding: 10px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 8px;
      transition: all 0.2s;
      border: 1px solid transparent;
    }}
    .mesh-toggle:hover {{
      background: rgba(124, 58, 237, 0.15);
      border-color: rgba(124, 58, 237, 0.3);
    }}
    .mesh-toggle input {{
      margin-right: 12px;
      cursor: pointer;
      width: 16px;
      height: 16px;
    }}
    .mesh-toggle label {{
      cursor: pointer;
      flex: 1;
      font-size: 13px;
      user-select: none;
    }}
    .info-row {{ margin: 6px 0; font-size: 13px; }}
    .label {{ color: #a78bfa; font-weight: 500; }}
  </style>
</head>
<body>
  <div id="container"></div>
  <div id="info" class="panel">
    <h3>🎨 3D Model Viewer (MDL direct)</h3>
    <div class="info-row"><span class="label">File:</span> {Path(mdl_path).name}</div>
    <div class="info-row"><span class="label">Source:</span> direct .mdl (no .fmt/.ib/.vb)</div>
  </div>

  <div id="controls" class="panel">
    <h4>🎨 Display</h4>
    <button onclick="toggleWireframe()">📐 Toggle Wireframe</button>
    <button onclick="resetCamera()">🎯 Reset Camera</button>
    <button onclick="toggleColors()">🎨 Change Colors</button>
    <h4>👁️ Mesh Visibility</h4>
    <button onclick="toggleAllMeshes(true)">✅ Show All</button>
    <button onclick="toggleAllMeshes(false)">❌ Hide All</button>
    <div id="mesh-list"></div>
  </div>

  <div id="stats" class="panel">
    <div id="fps">FPS: --</div>
    <div id="vertices">Vertices: --</div>
    <div id="triangles">Triangles: --</div>
    <div id="visible">Visible: --</div>
  </div>

  <!-- ✅ Correct Three.js import -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>

  <script>
    const data = {json.dumps(meshes_data, indent=2)};
    let scene, camera, renderer, controls, meshes = [], wireframeMode = false, colorMode = 0;

    // Minimal OrbitControls (custom, independent of three/examples)
    class OrbitControls {{
      constructor(camera, domElement) {{
        this.camera = camera; this.domElement = domElement; this.target = new THREE.Vector3();
        this.spherical = new THREE.Spherical(); this.sphericalDelta = new THREE.Spherical();
        this.scale = 1; this.panOffset = new THREE.Vector3();
        this.rotateStart = new THREE.Vector2(); this.panStart = new THREE.Vector2(); this.state = 0;
        domElement.addEventListener('contextmenu', function(e) {{ e.preventDefault(); }});
        domElement.addEventListener('mousedown', (e) => {{
          if (e.button === 0) {{ this.state = 1; this.rotateStart.set(e.clientX, e.clientY); }}
          else if (e.button === 2) {{ this.state = 2; this.panStart.set(e.clientX, e.clientY); }}
        }});
        domElement.addEventListener('mousemove', (e) => {{
          if (this.state === 1) {{
            const end = new THREE.Vector2(e.clientX, e.clientY);
            const delta = new THREE.Vector2().subVectors(end, this.rotateStart);
            this.sphericalDelta.theta -= 2 * Math.PI * delta.x / domElement.clientHeight;
            this.sphericalDelta.phi   -= 2 * Math.PI * delta.y / domElement.clientHeight;
            this.rotateStart.copy(end); this.update();
          }} else if (this.state === 2) {{
            const end = new THREE.Vector2(e.clientX, e.clientY);
            const delta = new THREE.Vector2().subVectors(end, this.panStart);
            const dist = this.camera.position.distanceTo(this.target);
            const factor = dist * Math.tan((this.camera.fov / 2) * Math.PI / 180.0);
            const left = new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 0);
            left.multiplyScalar(-2 * delta.x * factor / domElement.clientHeight);
            const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 1);
            up.multiplyScalar( 2 * delta.y * factor / domElement.clientHeight);
            this.panOffset.add(left).add(up); this.panStart.copy(end); this.update();
          }}
        }});
        domElement.addEventListener('mouseup', () => {{ this.state = 0; }});
        domElement.addEventListener('wheel', (e) => {{
          e.preventDefault();
          this.scale *= (e.deltaY < 0) ? 0.95 : 1.05;
          this.update();
        }});
        this.update();
      }}
      update() {{
        const offset = new THREE.Vector3();
        const quat = new THREE.Quaternion().setFromUnitVectors(this.camera.up, new THREE.Vector3(0,1,0));
        offset.copy(this.camera.position).sub(this.target); offset.applyQuaternion(quat);
        this.spherical.setFromVector3(offset);
        this.spherical.theta += this.sphericalDelta.theta;
        this.spherical.phi   += this.sphericalDelta.phi;
        this.spherical.phi = Math.max(0.01, Math.min(Math.PI - 0.01, this.spherical.phi));
        this.spherical.radius *= this.scale;
        this.target.add(this.panOffset);
        offset.setFromSpherical(this.spherical); offset.applyQuaternion(quat.invert());
        this.camera.position.copy(this.target).add(offset); this.camera.lookAt(this.target);
        this.sphericalDelta.set(0,0,0); this.scale = 1; this.panOffset.set(0,0,0);
      }}
    }}

    function init() {{
      scene = new THREE.Scene(); scene.background = new THREE.Color(0x2a2a3e);
      camera = new THREE.PerspectiveCamera(50, window.innerWidth/window.innerHeight, 0.1, 1000);
      camera.position.set(2, 1.2, 2);

      renderer = new THREE.WebGLRenderer({{antialias: true}});
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      document.getElementById('container').appendChild(renderer.domElement);

      scene.add(new THREE.AmbientLight(0xffffff, 0.5));
      const light = new THREE.DirectionalLight(0xffffff, 0.8);
      light.position.set(5, 5, 5); scene.add(light);

      const colors = [0xE8B4B8, 0xB8D4E8, 0xC8E8B8, 0xE8D4B8, 0xD8B8E8, 0xE8E8B8];
      let totalVerts = 0, totalTriangles = 0;
      const meshListDiv = document.getElementById('mesh-list');

      data.forEach(function(m, i) {{
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(m.vertices), 3));
        geo.setAttribute('normal',   new THREE.BufferAttribute(new Float32Array(m.normals), 3));
        geo.setIndex(new THREE.BufferAttribute(new Uint32Array(m.indices), 1));

        const mat = new THREE.MeshPhongMaterial({{
          color: colors[i % colors.length],
          side: THREE.DoubleSide,
          flatShading: false,
          shininess: 30
        }});
        const mesh = new THREE.Mesh(geo, mat);
        mesh.name = m.name;
        scene.add(mesh); meshes.push(mesh);

        totalVerts += m.vertices.length / 3;
        totalTriangles += m.indices.length / 3;

        // Mesh toggle entry (no JS template literals)
        const toggleDiv = document.createElement('div');
        toggleDiv.className = 'mesh-toggle';
        toggleDiv.innerHTML =
          '<input type="checkbox" id="mesh-' + i + '" checked onchange="toggleMesh(' + i + ')">' +
          '<label for="mesh-' + i + '">' + m.name + '</label>';
        meshListDiv.appendChild(toggleDiv);
      }});

      controls = new OrbitControls(camera, renderer.domElement);
      scene.add(new THREE.GridHelper(10, 10, 0x444444, 0x222222));

      const box = new THREE.Box3();
      meshes.forEach(function(m) {{ box.expandByObject(m); }});
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const dist = Math.max(size.x, size.y, size.z) * 2;
      camera.position.set(center.x + dist*0.5, center.y + dist*0.5, center.z + dist*0.5);
      camera.lookAt(center);
      controls.target.copy(center); controls.update();

      document.getElementById('vertices').textContent = 'Vertices: ' + totalVerts.toLocaleString();
      document.getElementById('triangles').textContent = 'Triangles: ' + totalTriangles.toLocaleString();
      document.getElementById('visible').textContent = 'Visible: ' + meshes.length + '/' + meshes.length;

      window.addEventListener('resize', function() {{
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
      }});

      animate();
    }}

    function toggleMesh(index) {{
      const cb = document.getElementById('mesh-' + index);
      if (cb) {{
        meshes[index].visible = cb.checked;
      }}
      const visibleCount = meshes.filter(function(m) {{ return m.visible; }}).length;
      document.getElementById('visible').textContent = 'Visible: ' + visibleCount + '/' + meshes.length;
    }}

    function toggleAllMeshes(visible) {{
      meshes.forEach(function(mesh, index) {{
        mesh.visible = visible;
        const cb = document.getElementById('mesh-' + index);
        if (cb) cb.checked = visible;
      }});
      document.getElementById('visible').textContent = 'Visible: ' + (visible ? meshes.length : 0) + '/' + meshes.length;
    }}

    // ✅ FIXED VERSION (previous syntax error removed)
    function toggleColors() {{
      colorMode = (colorMode + 1) % 3;
      meshes.forEach(function (mesh, index) {{
        if (colorMode === 0) {{
          const palette = [0xE8B4B8, 0xB8D4E8, 0xC8E8B8, 0xE8D4B8, 0xD8B8E8, 0xE8E8B8];
          mesh.material.color.setHex(palette[index % palette.length]);
        }} else if (colorMode === 1) {{
          mesh.material.color.setHex(0xCCCCCC);
        }} else {{
          const hue = index / Math.max(1, meshes.length);
          const color = new THREE.Color().setHSL(hue, 0.7, 0.6);
          mesh.material.color.copy(color);
        }}
      }});
    }}

    function toggleWireframe() {{
      wireframeMode = !wireframeMode;
      meshes.forEach(function(m) {{ m.material.wireframe = wireframeMode; }});
    }}

    function resetCamera() {{
      const box = new THREE.Box3();
      meshes.forEach(function(m) {{ box.expandByObject(m); }});
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const dist = Math.max(size.x, size.y, size.z) * 2;
      camera.position.set(center.x + dist*0.5, center.y + dist*0.5, center.z + dist*0.5);
      camera.lookAt(center);
      controls.target.copy(center); controls.update();
    }}

    let lastTime = performance.now(), frames = 0;
    function animate() {{
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      frames++;
      const time = performance.now();
      if (time >= lastTime + 1000) {{
        document.getElementById('fps').textContent = 'FPS: ' + Math.round(frames * 1000 / (time - lastTime));
        frames = 0; lastTime = time;
      }}
    }}
    init();
  </script>
</body>
</html>"""

    output = Path(mdl_path).with_suffix("")  # strip .mdl
    output = output.parent / f"{output.name}_viewer.html"
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    return output


# -----------------------------
# main
# -----------------------------
def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("mdl_path", help="Path to .mdl file")
    p.add_argument("--use-original-normals", action="store_true",
                   help="If the .mdl contains normals, use them (otherwise smooth normals are computed).")
    args = p.parse_args()

    mdl_path = Path(args.mdl_path)
    if not mdl_path.exists() or mdl_path.suffix.lower() != ".mdl":
        print("Error: please provide an existing .mdl file.")
        sys.exit(2)

    try:
        print(f"[1/3] Reading MDL: {mdl_path}")
        meshes = load_mdl_direct(mdl_path, use_original_normals=args.use_original_normals)
        if not meshes:
            print("No renderable mesh was found in the file.")
            sys.exit(1)

        print(f"[2/3] Mesh count: {len(meshes)}")
        total_verts = sum(len(m["vertices"]) for m in meshes if m["vertices"] is not None)
        total_tris = sum(len(m["indices"]) // 3 for m in meshes if m["indices"] is not None)
        print(f"       Vertices: {total_verts:,} | Triangles: {total_tris:,}")

        print("[3/3] Generating HTML…")
        out = export_html_from_meshes(mdl_path, meshes)
        print(f"[OK] Created: {out}")

        try:
            import webbrowser
            webbrowser.open(f"file://{out.absolute()}")
            print("[OK] Opened in default browser.")
        except Exception:
            print(f"Please open manually: {out.absolute()}")

    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
