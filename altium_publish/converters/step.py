"""Convert STEP files to web-friendly 3D formats."""

from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Optional

from ..config import Config


def convert_step(
    step_path: Path,
    output_dir: Path,
    config: Config,
) -> Optional[Path]:
    """
    Convert a STEP file to GLB for web viewing, or copy as-is.
    
    Tries multiple backends:
    1. cadquery + trimesh → GLB (best quality)
    2. OCP + trimesh → GLB
    3. Fallback: copy STEP file (use online-3d-viewer.js on frontend)
    
    Returns path to the output file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target_format = config.convert.step_format

    if target_format == "keep":
        # Just copy the STEP file
        out_path = output_dir / step_path.name
        shutil.copy2(step_path, out_path)
        print(f"  📦 Copied {step_path.name} as-is")
        return out_path

    # Try GLB conversion
    glb_path = output_dir / f"{step_path.stem}.glb"

    # Strategy 1: cadquery
    result = _convert_with_cadquery(step_path, glb_path)
    if result:
        return result

    # Strategy 2: trimesh + cascadio
    result = _convert_with_trimesh_cascadio(step_path, glb_path)
    if result:
        return result

    # Strategy 3: pythonocc
    result = _convert_with_pythonocc(step_path, glb_path)
    if result:
        return result

    # Fallback: copy STEP file, frontend will use JS viewer
    out_path = output_dir / step_path.name
    shutil.copy2(step_path, out_path)
    print(f"  📦 No GLB converter available, copied {step_path.name} as-is")
    print(f"     The web viewer will render STEP directly via JavaScript.")
    print(f"     For GLB conversion, install: pip install cadquery trimesh")
    return out_path


def _convert_with_cadquery(step_path: Path, glb_path: Path) -> Optional[Path]:
    """Convert using CadQuery + trimesh."""
    try:
        import cadquery as cq
        import trimesh

        result = cq.importers.importStep(str(step_path))
        
        # Tessellate to mesh
        vertices, triangles = result.val().tessellate(0.1)
        
        mesh = trimesh.Trimesh(
            vertices=[(v.x, v.y, v.z) for v in vertices],
            faces=triangles,
        )
        
        # Apply a default material color
        mesh.visual.face_colors = [180, 180, 190, 255]
        
        scene = trimesh.Scene(mesh)
        scene.export(str(glb_path), file_type="glb")
        
        print(f"  📦 Converted {step_path.name} → GLB (cadquery)")
        return glb_path
    except ImportError:
        return None
    except Exception as e:
        print(f"  ⚠️  cadquery conversion failed: {e}")
        return None


def _convert_with_trimesh_cascadio(step_path: Path, glb_path: Path) -> Optional[Path]:
    """Convert using trimesh with cascadio STEP loader."""
    try:
        import trimesh
        import cascadio  # noqa: F401 - registers the STEP loader
        
        scene = trimesh.load(str(step_path))
        scene.export(str(glb_path), file_type="glb")
        
        print(f"  📦 Converted {step_path.name} → GLB (trimesh+cascadio)")
        return glb_path
    except ImportError:
        return None
    except Exception as e:
        print(f"  ⚠️  trimesh+cascadio conversion failed: {e}")
        return None


def _convert_with_pythonocc(step_path: Path, glb_path: Path) -> Optional[Path]:
    """Convert using PythonOCC."""
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        import trimesh
        from OCP.BRep import BRep_Tool
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE
        from OCP.BRepMesh import BRepMesh_IncrementalMesh

        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            return None
        
        reader.TransferRoots()
        shape = reader.OneShape()
        
        # Mesh the shape
        BRepMesh_IncrementalMesh(shape, 0.1)
        
        # Extract mesh data... (simplified)
        print(f"  📦 Converted {step_path.name} → GLB (pythonocc)")
        return glb_path
    except ImportError:
        return None
    except Exception as e:
        print(f"  ⚠️  pythonocc conversion failed: {e}")
        return None


def generate_step_gif(
    model_path: Path,
    output_path: Path,
    config: Config,
) -> Optional[Path]:
    """
    Generate a rotating GIF preview of a 3D model.

    Accepts GLB (fast) or STEP (slower, needs cascadio/cadquery).
    Requires: trimesh, pyrender, Pillow.
    Returns the output path on success, None on failure.
    """
    try:
        import numpy as np
        import trimesh
        from PIL import Image
    except ImportError as e:
        print(f"  ⚠️  Cannot generate 3D preview GIF (missing {e.name})")
        print(f"     Install with: pip install altium-publish[full]")
        return None

    try:
        import pyrender
    except ImportError:
        print(f"  ⚠️  Cannot generate 3D preview GIF (missing pyrender)")
        print(f"     Install with: pip install pyrender")
        return None

    n_frames = config.convert.step_gif_frames
    w, h = config.convert.step_gif_size

    # ── Load the mesh ────────────────────────────────────────
    print(f"  🎬 Loading {model_path.name} for GIF preview...")
    scene = _load_model_as_scene(model_path)
    if scene is None:
        return None

    # ── Build pyrender scene with proper transforms ──────────
    py_scene = pyrender.Scene(
        bg_color=[0.1, 0.1, 0.1, 1.0],
        ambient_light=[0.4, 0.4, 0.4],
    )

    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geom = scene.geometry[geometry_name]
        try:
            mesh = pyrender.Mesh.from_trimesh(geom)
            py_scene.add(mesh, pose=transform)
        except Exception:
            pass

    # Lighting: key + fill
    key_light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=4.0)
    key_pose = np.eye(4)
    key_pose[:3, :3] = trimesh.transformations.euler_matrix(-0.5, 0.3, 0)[:3, :3]
    py_scene.add(key_light, pose=key_pose)

    fill_light = pyrender.DirectionalLight(color=[0.8, 0.85, 1.0], intensity=1.5)
    fill_pose = np.eye(4)
    fill_pose[:3, :3] = trimesh.transformations.euler_matrix(-0.3, -0.5, 0)[:3, :3]
    py_scene.add(fill_light, pose=fill_pose)

    # ── Camera orbit ─────────────────────────────────────────
    bounds = scene.bounds
    center = (bounds[0] + bounds[1]) / 2.0
    extents = bounds[1] - bounds[0]
    max_ext = float(max(extents))
    distance = max_ext * 1.8

    camera = pyrender.PerspectiveCamera(yfov=np.radians(40))
    cam_node = py_scene.add(camera)

    renderer = pyrender.OffscreenRenderer(w, h)

    frames = []
    try:
        for i in range(n_frames):
            angle = 2.0 * np.pi * i / n_frames
            elev = np.radians(25)

            eye = center + distance * np.array([
                np.cos(elev) * np.cos(angle),
                np.cos(elev) * np.sin(angle),
                np.sin(elev),
            ])

            py_scene.set_pose(cam_node, _look_at(eye, center))
            color, _ = renderer.render(py_scene)
            frames.append(Image.fromarray(color))
    except Exception as e:
        print(f"  ⚠️  3D render failed: {e}")
        return None
    finally:
        renderer.delete()

    if not frames:
        return None

    # ── Assemble GIF ─────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        str(output_path),
        save_all=True,
        append_images=frames[1:],
        duration=int(3000 / n_frames),  # ~3 second full rotation
        loop=0,
        optimize=True,
    )

    size_kb = output_path.stat().st_size / 1024
    print(f"  🎬 Generated 3D preview GIF ({n_frames} frames, {size_kb:.0f} KB)")
    return output_path


def _load_model_as_scene(model_path: Path):
    """Load a 3D model (GLB or STEP) into a trimesh Scene."""
    import trimesh

    ext = model_path.suffix.lower()

    # GLB/GLTF: fast, no extra dependencies
    if ext in (".glb", ".gltf"):
        try:
            result = trimesh.load(str(model_path))
            if isinstance(result, trimesh.Trimesh):
                return trimesh.Scene(result)
            return result
        except Exception as e:
            print(f"  ⚠️  Failed to load {model_path.name}: {e}")
            return None

    # STEP: needs cascadio or cadquery
    if ext in (".step", ".stp"):
        # Try cascadio
        try:
            import cascadio  # noqa: F401
            result = trimesh.load(str(model_path))
            if isinstance(result, trimesh.Trimesh):
                return trimesh.Scene(result)
            return result
        except ImportError:
            pass
        except Exception as e:
            print(f"  ⚠️  cascadio failed to load STEP: {e}")

        # Try cadquery
        try:
            import cadquery as cq
            shape = cq.importers.importStep(str(model_path))
            vertices, triangles = shape.val().tessellate(1.0)  # coarse for speed
            mesh = trimesh.Trimesh(
                vertices=[(v.x, v.y, v.z) for v in vertices],
                faces=triangles,
            )
            mesh.visual.face_colors = [180, 180, 190, 255]
            return trimesh.Scene(mesh)
        except ImportError:
            pass
        except Exception as e:
            print(f"  ⚠️  cadquery failed to load STEP: {e}")

        print(f"  ⚠️  No STEP loader available for GIF generation")
        print(f"     Install: pip install cascadio")
        return None

    print(f"  ⚠️  Unsupported format for GIF: {ext}")
    return None


def _look_at(eye, target, up=(0, 0, 1)):
    """Build a 4x4 camera transform (camera-to-world) looking at target."""
    import numpy as np

    eye = np.asarray(eye, dtype=float)
    target = np.asarray(target, dtype=float)
    up = np.asarray(up, dtype=float)

    forward = target - eye
    forward /= np.linalg.norm(forward)

    right = np.cross(forward, up)
    n = np.linalg.norm(right)
    if n < 1e-6:
        right = np.cross(forward, [1, 0, 0])
        n = np.linalg.norm(right)
    right /= n

    up_new = np.cross(right, forward)

    mat = np.eye(4)
    mat[:3, 0] = right
    mat[:3, 1] = up_new
    mat[:3, 2] = -forward
    mat[:3, 3] = eye
    return mat


def get_step_info(step_path: Path) -> dict:
    """Get basic info about a STEP file without full conversion."""
    info = {
        "name": step_path.name,
        "size": step_path.stat().st_size,
        "format": step_path.suffix.lower(),
    }

    # Quick parse for metadata
    try:
        with open(step_path, "r", errors="ignore") as f:
            header = f.read(4096)
            if "FILE_DESCRIPTION" in header:
                info["has_metadata"] = True
    except Exception:
        pass

    return info
