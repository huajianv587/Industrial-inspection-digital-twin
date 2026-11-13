#!/usr/bin/env python3
"""Build and render a meter-scale virtual industrial inspection factory.

The scene is procedural so it can run without downloaded CAD or robot assets.
One Blender unit represents one metre. The generated .blend and GLB files are
inspection-scene artifacts, not official Unitree assets or a physical robot
model.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hdri",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "web/public/assets/industrial_workshop_foundry_2k.hdr",
        help="Optional equirectangular environment used for factory lighting and reflections.",
    )
    parser.add_argument("--scene-input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", default=1920, type=int)
    parser.add_argument("--orbit-cameras", default=10, type=int)
    parser.add_argument(
        "--camera-filter",
        action="append",
        default=[],
        help="Render only matching camera filename tokens; repeat or use commas.",
    )
    parser.add_argument("--quality", choices=("preview", "production", "ultra"), default="production")
    parser.add_argument("--render-navigation-overlays", action="store_true")
    parser.add_argument("--skip-glb-export", action="store_true")
    parser.add_argument(
        "--stream-frames", default=0, type=int,
        help="Render a sampled robot RGB/CCTV image stream over the route.",
    )
    parser.add_argument(
        "--stream-resolution", default=512, type=int,
        help="Width of each sampled stream frame; height is 16:9.",
    )
    args = parser.parse_args(argv)
    args.camera_filter = tuple(
        token.strip()
        for value in args.camera_filter
        for token in value.split(",")
        if token.strip()
    )
    return args


def _material(bpy, name: str, color: tuple[float, float, float, float], *,
              metallic: float = 0.0, roughness: float = 0.55, emission=None,
              texture_scale: float = 0.0, bump_distance: float = 0.0):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    nodes = material.node_tree.nodes
    shader = nodes.get("Principled BSDF")
    if shader is not None:
        base_socket = shader.inputs.get("Base Color")
        metallic_socket = shader.inputs.get("Metallic")
        roughness_socket = shader.inputs.get("Roughness")
        if base_socket is not None:
            base_socket.default_value = color
        if metallic_socket is not None:
            metallic_socket.default_value = metallic
        if roughness_socket is not None:
            roughness_socket.default_value = roughness
        # Keep highlights physically legible without turning every painted
        # surface into a mirror. Blender 4/5 renamed this input, so use the
        # socket lookup rather than indexing a version-specific name.
        specular_socket = shader.inputs.get("Specular IOR Level")
        if specular_socket is not None:
            specular_socket.default_value = 0.38 if metallic < 0.5 else 0.45
        if emission is not None:
            for key in ("Emission Color", "Emission"):
                if key in shader.inputs:
                    shader.inputs[key].default_value = emission
                    break
            if "Emission Strength" in shader.inputs:
                shader.inputs["Emission Strength"].default_value = 3.0
        if texture_scale:
            texture = nodes.new("ShaderNodeTexNoise")
            texture.inputs["Scale"].default_value = texture_scale
            texture.inputs["Detail"].default_value = 3.0
            texture.inputs["Roughness"].default_value = 0.72
            ramp = nodes.new("ShaderNodeValToRGB")
            base = color[:3]
            ramp.color_ramp.elements[0].color = (*tuple(max(channel * 0.78, 0.0) for channel in base), 1.0)
            ramp.color_ramp.elements[1].color = (*tuple(min(channel * 1.10 + 0.012, 1.0) for channel in base), 1.0)
            material.node_tree.links.new(texture.outputs["Fac"], ramp.inputs["Fac"])
            if base_socket is not None:
                material.node_tree.links.new(ramp.outputs["Color"], base_socket)
            if roughness_socket is not None:
                roughness_map = nodes.new("ShaderNodeMapRange")
                roughness_map.inputs["From Min"].default_value = 0.18
                roughness_map.inputs["From Max"].default_value = 0.82
                roughness_map.inputs["To Min"].default_value = max(0.03, roughness * 0.82)
                roughness_map.inputs["To Max"].default_value = min(1.0, roughness * 1.18)
                material.node_tree.links.new(texture.outputs["Fac"], roughness_map.inputs["Value"])
                material.node_tree.links.new(roughness_map.outputs["Result"], roughness_socket)
        if texture_scale and bump_distance:
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.16
            bump.inputs["Distance"].default_value = bump_distance
            material.node_tree.links.new(texture.outputs["Fac"], bump.inputs["Height"])
            _chain_normal_layer(shader, material.node_tree.links, bump.inputs["Normal"],
                                bump.outputs["Normal"])
    return material


def _prepare_glb_export_materials(bpy) -> int:
    """Flatten procedural shader links that glTF cannot carry reliably.

    The Cycles/Eevee render keeps the layered procedural materials for the
    high-fidelity stills.  The interactive viewer needs a portable PBR
    representation, however, and Blender's glTF exporter can silently turn
    unsupported Noise/ColorRamp/Bump chains into white materials.  Export is
    intentionally performed after the .blend has been saved, so this display
    compatibility pass never changes the source scene on disk.
    """
    flattened = 0
    for material in bpy.data.materials:
        if not getattr(material, "use_nodes", False):
            continue
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        shader = nodes.get("Principled BSDF")
        if shader is None:
            continue

        base_socket = shader.inputs.get("Base Color")
        roughness_socket = shader.inputs.get("Roughness")
        normal_socket = shader.inputs.get("Normal")
        changed = False

        if base_socket is not None and base_socket.is_linked:
            # diffuse_color is the canonical color assigned by _material and
            # remains stable even when the procedural ColorRamp is unsupported.
            color = tuple(float(channel) for channel in material.diffuse_color[:4])
            for link in list(base_socket.links):
                links.remove(link)
            base_socket.default_value = color
            changed = True

        if roughness_socket is not None and roughness_socket.is_linked:
            # _material sets this default before attaching the procedural map.
            # Preserve that authored value as the portable fallback.
            roughness = max(0.04, min(1.0, float(roughness_socket.default_value)))
            for link in list(roughness_socket.links):
                links.remove(link)
            roughness_socket.default_value = roughness
            changed = True

        if normal_socket is not None and normal_socket.is_linked:
            # Procedural Bump nodes are not portable glTF normal maps. The
            # geometry-level detail and PBR roughness still remain visible.
            for link in list(normal_socket.links):
                links.remove(link)
            changed = True

        if changed:
            material["glb_export_material_mode"] = "flattened_pbr_fallback"
            flattened += 1
    return flattened


def _join_static_meshes_for_glb(bpy) -> int:
    """Reduce browser draw calls without changing the saved Blender source."""
    scene = bpy.context.scene

    def is_cutaway_roof_mesh(obj) -> bool:
        """Keep roof members addressable so the browser cutaway is real."""
        return obj.name.startswith((
            "RoofTruss",
            "RoofPurlin",
            "North_RingBeam",
            "East_RingBeam",
        ))

    static_meshes = [
        obj for obj in scene.objects
        if obj.type == "MESH"
        and obj.parent is None
        and obj.animation_data is None
        and not is_cutaway_roof_mesh(obj)
    ]
    if not static_meshes:
        return 0
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in static_meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = static_meshes[0]
    bpy.ops.object.convert(target="MESH", keep_original=False)

    groups = {}
    for obj in scene.objects:
        if (
            obj.type != "MESH"
            or obj.parent is not None
            or obj.animation_data is not None
            or is_cutaway_roof_mesh(obj)
            or len(obj.data.materials) != 1
        ):
            continue
        material = obj.data.materials[0]
        if material is not None:
            groups.setdefault(material, []).append(obj)

    merged = 0
    for material, objects in groups.items():
        if len(objects) < 2:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        active = objects[0]
        bpy.context.view_layer.objects.active = active
        bpy.ops.object.join()
        active.name = f"GLB_Static_{material.name}"
        merged += len(objects) - 1
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.update()
    return merged


def _chain_normal_layer(shader, links, layer_input, layer_output):
    """Preserve an existing normal layer before adding another bump stage."""
    normal_socket = shader.inputs.get("Normal")
    if normal_socket is None:
        return
    previous = normal_socket.links[0].from_socket if normal_socket.links else None
    if previous is not None and previous != layer_output:
        links.new(previous, layer_input)
    links.new(layer_output, normal_socket)


def _microfinish(material, *, scale: float = 180.0, detail: float = 4.0,
                 bump_strength: float = 0.12, bump_distance: float = 0.006,
                 roughness_min: float | None = None,
                 roughness_max: float | None = None):
    """Add a second, high-frequency finish layer to manufactured surfaces.

    The scene is procedural, so this keeps the detail deterministic and local:
    a low-amplitude noise field controls micro-normal breakup and, when
    requested, small roughness variation. It is deliberately separate from
    the broad color variation in ``_material`` so labels and gauges stay clean.
    """
    if not getattr(material, "use_nodes", False):
        return material
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        return material
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = f"{material.name}_MicroCoordinates"
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = f"{material.name}_MicroNoise"
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    noise.inputs["Roughness"].default_value = 0.78
    links.new(texcoord.outputs["Object"], noise.inputs["Vector"])

    bump = nodes.new("ShaderNodeBump")
    bump.name = f"{material.name}_MicroBump"
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_distance
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    _chain_normal_layer(shader, links, bump.inputs["Normal"], bump.outputs["Normal"])

    if roughness_min is not None and roughness_max is not None:
        roughness = nodes.new("ShaderNodeMapRange")
        roughness.name = f"{material.name}_MicroRoughness"
        roughness.inputs["From Min"].default_value = 0.20
        roughness.inputs["From Max"].default_value = 0.82
        roughness.inputs["To Min"].default_value = roughness_min
        roughness.inputs["To Max"].default_value = roughness_max
        links.new(noise.outputs["Fac"], roughness.inputs["Value"])
        links.new(roughness.outputs["Result"], shader.inputs["Roughness"])
    return material


def _set_transmission(material, weight: float, *, ior: float = 1.45):
    """Configure a small transparent cover without assuming one Blender socket name."""
    if not getattr(material, "use_nodes", False):
        return material
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        return material
    for key in ("Transmission Weight", "Transmission"):
        socket = shader.inputs.get(key)
        if socket is not None:
            socket.default_value = weight
            break
    ior_socket = shader.inputs.get("IOR")
    if ior_socket is not None:
        ior_socket.default_value = ior
    alpha_socket = shader.inputs.get("Alpha")
    if alpha_socket is not None:
        alpha_socket.default_value = 0.44
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    return material


def _add_midscale_surface_finish(material, *, scale: float = 28.0,
                                 bump_strength: float = 0.055,
                                 bump_distance: float = 0.004,
                                 roughness_min: float | None = None,
                                 roughness_max: float | None = None):
    """Add a second manufacturing-scale texture between broad noise and microfinish."""
    if not getattr(material, "use_nodes", False):
        return material
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        return material
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = f"{material.name}_MidCoordinates"
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = f"{material.name}_MidNoise"
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 5.0
    noise.inputs["Roughness"].default_value = 0.74
    links.new(texcoord.outputs["Object"], noise.inputs["Vector"])

    bump = nodes.new("ShaderNodeBump")
    bump.name = f"{material.name}_MidBump"
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_distance
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    _chain_normal_layer(shader, links, bump.inputs["Normal"], bump.outputs["Normal"])

    if roughness_min is not None and roughness_max is not None:
        roughness = nodes.new("ShaderNodeMapRange")
        roughness.name = f"{material.name}_MidRoughness"
        roughness.inputs["From Min"].default_value = 0.20
        roughness.inputs["From Max"].default_value = 0.82
        roughness.inputs["To Min"].default_value = roughness_min
        roughness.inputs["To Max"].default_value = roughness_max
        links.new(noise.outputs["Fac"], roughness.inputs["Value"])
        links.new(roughness.outputs["Result"], shader.inputs["Roughness"])
    return material


def _set_coat_weight(material, weight: float = 0.12, roughness: float = 0.22):
    """Set a restrained clear coat on painted or brushed metal when supported."""
    if not getattr(material, "use_nodes", False):
        return material
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        return material
    for key in ("Coat Weight", "Clearcoat"):
        socket = shader.inputs.get(key)
        if socket is not None:
            socket.default_value = weight
            break
    for key in ("Coat Roughness", "Clearcoat Roughness"):
        socket = shader.inputs.get(key)
        if socket is not None:
            socket.default_value = roughness
            break
    return material


def _set_anisotropy(material, strength: float = 0.22, rotation: float = 0.0):
    """Give brushed or machined metals directional highlight breakup."""
    if not getattr(material, "use_nodes", False):
        return material
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        return material
    for key in ("Anisotropic IOR Level", "Anisotropic"):
        socket = shader.inputs.get(key)
        if socket is not None:
            socket.default_value = strength
            break
    for key in ("Anisotropic Rotation",):
        socket = shader.inputs.get(key)
        if socket is not None:
            socket.default_value = rotation
            break
    return material


def _set_emission_strength(material, strength: float):
    """Tune emissive fixtures without changing their authored color."""
    if not getattr(material, "use_nodes", False):
        return material
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        return material
    socket = shader.inputs.get("Emission Strength")
    if socket is not None:
        socket.default_value = strength
    return material


def _add_directional_finish(material, *, scale: float = 150.0,
                            distortion: float = 2.0, detail: float = 2.0,
                            bump_strength: float = 0.055,
                            bump_distance: float = 0.002):
    """Add directional manufacturing marks to brushed or rolled surfaces."""
    if not getattr(material, "use_nodes", False):
        return material
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        return material
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = f"{material.name}_DirectionalCoordinates"
    wave = nodes.new("ShaderNodeTexWave")
    wave.name = f"{material.name}_DirectionalGrain"
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = scale
    wave.inputs["Distortion"].default_value = distortion
    wave.inputs["Detail"].default_value = detail
    links.new(texcoord.outputs["Object"], wave.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.name = f"{material.name}_DirectionalBump"
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_distance
    links.new(wave.outputs["Color"], bump.inputs["Height"])
    _chain_normal_layer(shader, links, bump.inputs["Normal"], bump.outputs["Normal"])
    return material


def _assign(obj, material):
    if material is not None:
        obj.data.materials.append(material)
    return obj


def _bevel(obj, width: float = 0.04, segments: int = 3):
    modifier = obj.modifiers.new(name="Small manufactured edge", type="BEVEL")
    modifier.width = width
    modifier.segments = segments
    return obj


def _box(bpy, name: str, location, half_extents, material, *, bevel=0.04, parent=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = half_extents
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _assign(obj, material)
    if bevel:
        _bevel(obj, bevel)
    if parent is not None:
        obj.parent = parent
    return obj


def _cylinder(bpy, name: str, location, radius: float, depth: float, material,
              *, rotation=(0.0, 0.0, 0.0), vertices=32, bevel=0.02, parent=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                        location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    _assign(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    if bevel:
        _bevel(obj, bevel, 2)
    if parent is not None:
        obj.parent = parent
    return obj


def _sphere(bpy, name: str, location, scale, material, *, parent=None, segments=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=max(12, segments // 2),
                                        radius=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    _assign(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    if parent is not None:
        obj.parent = parent
    return obj


def _torus(bpy, name: str, location, major_radius: float, minor_radius: float, material,
           *, rotation=(0.0, 0.0, 0.0), parent=None):
    bpy.ops.mesh.primitive_torus_add(major_segments=48, minor_segments=12,
                                     location=location, major_radius=major_radius,
                                     minor_radius=minor_radius, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    _assign(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    if parent is not None:
        obj.parent = parent
    return obj


def _add_valve(bpy, name: str, center, radius: float, materials, *, axis="x",
               wheel_material="warning", body_material="steel"):
    """Add a compact process valve with a stem, hand wheel and packing gland."""
    rotation = {
        "x": (0.0, math.pi / 2, 0.0),
        "y": (math.pi / 2, 0.0, 0.0),
        "z": (0.0, 0.0, 0.0),
    }[axis]
    x, y, z = center
    _cylinder(bpy, f"{name}_Body", center, radius, radius * 1.35, materials[body_material],
              rotation=rotation, vertices=48, bevel=0.025)
    _cylinder(bpy, f"{name}_Bonnet", (x, y, z + radius * 0.72), radius * 0.55,
              radius * 0.42, materials[body_material], vertices=32, bevel=0.018)
    _cylinder(bpy, f"{name}_Stem", (x, y, z + radius * 1.05), radius * 0.10,
              radius * 0.70, materials["brass"], vertices=20, bevel=0.008)
    _torus(bpy, f"{name}_HandWheel", (x, y, z + radius * 1.46), radius * 0.46,
           radius * 0.055, materials[wheel_material])


def _add_flange(bpy, name: str, center, radius: float, depth: float, materials,
                *, rotation=(0.0, 0.0, 0.0), bolt_count=8):
    """Add a flange face and evenly spaced hex fasteners."""
    x, y, z = center
    _cylinder(bpy, f"{name}_Face", center, radius, depth, materials["steel"],
              rotation=rotation, vertices=64, bevel=0.012)
    # The visible face is perpendicular to the local cylinder axis. The two
    # supported orientations cover all process connections in this scene.
    if abs(rotation[1]) > 0.5:
        face = (x + depth * 0.55, y, z)
        for bolt in range(bolt_count):
            angle = math.tau * bolt / bolt_count
            _cylinder(bpy, f"{name}_Bolt_{bolt}",
                      (face[0], y + math.sin(angle) * radius * 0.78,
                       z + math.cos(angle) * radius * 0.78), radius * 0.095,
                      depth * 0.52, materials["brass"], rotation=rotation, vertices=6,
                      bevel=0.005)
    else:
        face = (x, y - depth * 0.55, z)
        for bolt in range(bolt_count):
            angle = math.tau * bolt / bolt_count
            _cylinder(bpy, f"{name}_Bolt_{bolt}",
                      (x + math.sin(angle) * radius * 0.78, face[1],
                       z + math.cos(angle) * radius * 0.78), radius * 0.095,
                      depth * 0.52, materials["brass"], rotation=rotation, vertices=6,
                      bevel=0.005)
    return center


def _add_fastener_washer_and_nut(bpy, name: str, location, radius: float, materials,
                                 *, rotation=(0.0, 0.0, 0.0)):
    """Add the washer/nut stack that keeps a close-up flange from reading as a flat disk."""
    _torus(bpy, f"{name}_Washer", location, radius * 1.22, radius * 0.18,
           materials["fastener"], rotation=rotation)
    _cylinder(bpy, f"{name}_Nut", location, radius, radius * 0.60,
              materials["fastener"], rotation=rotation, vertices=6, bevel=radius * 0.08)


def _add_riveted_plate(bpy, name: str, location, half_extents, materials, *, text=None,
                       text_size=0.05):
    """Build a thin asset plate with four corner rivets and an optional face label."""
    x, y, z = location
    _box(bpy, f"{name}_Plate", location, half_extents, materials["label_plate"], bevel=0.006)
    for dx in (-half_extents[0] * 0.72, half_extents[0] * 0.72):
        for dz in (-half_extents[2] * 0.62, half_extents[2] * 0.62):
            _cylinder(bpy, f"{name}_Rivet_{dx:.3f}_{dz:.3f}",
                      (x + dx, y - half_extents[1] - 0.008, z + dz),
                      max(0.008, half_extents[2] * 0.12), 0.018,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=12, bevel=0.002)
    if text:
        _text(bpy, f"{name}_Text", text, (x, y - half_extents[1] - 0.020, z),
              materials["ink"], size=text_size)


def _add_plate_rivets(bpy, name: str, location, half_extents, materials):
    """Add rivets to an existing plate without duplicating its face or lettering."""
    x, y, z = location
    for dx in (-half_extents[0] * 0.72, half_extents[0] * 0.72):
        for dz in (-half_extents[2] * 0.62, half_extents[2] * 0.62):
            _cylinder(bpy, f"{name}_Rivet_{dx:.3f}_{dz:.3f}",
                      (x + dx, y - half_extents[1] - 0.008, z + dz),
                      max(0.008, half_extents[2] * 0.12), 0.018,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=12, bevel=0.002)


def _add_cable_loop(bpy, name: str, center, major_radius: float, material, *, rotation=(0, 0, 0)):
    """Add a short service loop so field wiring has strain relief and sag."""
    _torus(bpy, name, center, major_radius, max(0.014, major_radius * 0.10),
           material, rotation=rotation)
    _cylinder(bpy, f"{name}_GlandA", (center[0] - major_radius, center[1], center[2]),
              max(0.018, major_radius * 0.16), major_radius * 0.42,
              material, rotation=(0.0, math.pi / 2, 0.0), vertices=20, bevel=0.004)
    _cylinder(bpy, f"{name}_GlandB", (center[0] + major_radius, center[1], center[2]),
              max(0.018, major_radius * 0.16), major_radius * 0.42,
              material, rotation=(0.0, math.pi / 2, 0.0), vertices=20, bevel=0.004)


def _add_chequer_plate(bpy, name: str, location, half_extents, materials, *, bars=7):
    """Add a raised diamond-pattern service plate around a working asset."""
    x, y, z = location
    _box(bpy, f"{name}_Base", location, half_extents, materials["grating"], bevel=0.012)
    span_x, span_y = half_extents[0] * 1.72, half_extents[1] * 1.72
    for index in range(-bars, bars + 1):
        offset = index * span_y / max(1, bars * 1.35)
        raised = _box(
            bpy, f"{name}_Diamond_{index:+d}",
            (x + offset, y, z + half_extents[2] + 0.012),
            (0.018, span_x * 0.56, 0.010), materials["steel"], bevel=0.003,
        )
        raised.rotation_euler[2] = math.radians(45.0)


def _add_v19_factory_detail_layer(bpy, scene, bounds, materials):
    """Fill the middle scale of the plant with cable occupancy and service hardware."""
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Cable ladders are normally occupied. Four separate low-voltage bundles
    # make the tray read as a working distribution path instead of an empty box.
    for bundle in range(4):
        y = max_y - 1.10 - 0.20 + bundle * 0.13
        _pipe_path(
            bpy, f"V19_CableBundle_North_{bundle}",
            ((min_x + 1.10, y, 4.86), (center_x - 1.5, y, 4.86),
             (center_x + 2.0, y - 0.22, 4.56), (max_x - 1.25, y - 0.22, 4.56)),
            0.018 if bundle < 2 else 0.022, materials["cable"],
        )
        for clip_index, x in enumerate((center_x - 4.0, center_x, center_x + 4.0), start=1):
            if min_x + 1.0 < x < max_x - 1.0:
                _box(bpy, f"V19_CableBundleClip_{bundle}_{clip_index}",
                     (x, y, 4.86), (0.06, 0.05, 0.045),
                     materials["fastener"], bevel=0.006)

    # Bolt plates and gussets at portal-frame joints add manufactured load paths.
    for frame_index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 4), start=1):
        for side, y in enumerate((min_y + 0.35, max_y - 0.35), start=1):
            for z, name_suffix in ((5.95, "Upper"), (3.65, "Mid")):
                _box(bpy, f"V19_PortalGusset_{frame_index}_{side}_{name_suffix}",
                     (x, y - 0.14, z), (0.22, 0.035, 0.17),
                     materials["steel_dark"], bevel=0.010)
                for bolt in range(4):
                    dx = -0.12 if bolt % 2 == 0 else 0.12
                    dz = -0.08 if bolt < 2 else 0.08
                    _cylinder(
                        bpy, f"V19_PortalBolt_{frame_index}_{side}_{name_suffix}_{bolt}",
                        (x + dx, y - 0.183, z + dz), 0.020, 0.028,
                        materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                        vertices=6, bevel=0.003,
                    )

    # Cladding panel fasteners give the back wall scale and repeatable assembly logic.
    for panel_index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 2), start=1):
        for bolt_index, z in enumerate((1.10, 2.75, 4.38), start=1):
            _cylinder(bpy, f"V19_CladdingFastener_{panel_index}_{bolt_index}",
                      (x, max_y - 0.145, z), 0.014, 0.025,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=6, bevel=0.002)

    # Raised service plates make the equipment footprints mechanically plausible.
    _add_chequer_plate(bpy, "V19_ValveServicePlate", (4.0, 2.28, 0.052),
                       (1.55, 0.58, 0.035), materials, bars=5)
    _add_chequer_plate(bpy, "V19_MCCServicePlate", (8.0, -0.72, 0.052),
                       (1.12, 0.62, 0.035), materials, bars=5)
    _add_chequer_plate(bpy, "V19_PumpServicePlate", (11.5, 4.56, 0.052),
                       (1.55, 0.55, 0.035), materials, bars=6)

    # A small-bore instrument-air regulator assembly gives the header a real
    # termination and adds a second family of field-maintenance details.
    air_y, air_z = max_y - 2.72, 3.72
    regulator_x = center_x - 1.8
    _pipe_between(bpy, "V19_IA_RegulatorIn", (regulator_x, air_y, air_z),
                  (regulator_x, air_y - 0.22, air_z), 0.035, materials["instrument_air"])
    _cylinder(bpy, "V19_IA_RegulatorBody", (regulator_x, air_y - 0.35, air_z - 0.08),
              0.12, 0.26, materials["instrument"], rotation=(math.pi / 2, 0.0, 0.0),
              vertices=32, bevel=0.012)
    _cylinder(bpy, "V19_IA_RegulatorBowl", (regulator_x, air_y - 0.35, air_z - 0.30),
              0.10, 0.24, materials["gauge_glass"], rotation=(math.pi / 2, 0.0, 0.0),
              vertices=32, bevel=0.008)
    _add_valve(bpy, "V19_IA_RegulatorValve", (regulator_x, air_y - 0.35, air_z + 0.20),
               0.075, materials, axis="y", wheel_material="brass", body_material="steel")
    _add_riveted_plate(bpy, "V19_IA_RegulatorTag",
                       (regulator_x, air_y - 0.55, air_z + 0.12),
                       (0.18, 0.012, 0.045), materials, text="IA-REG", text_size=0.030)

    # Drain grates and cleanout collars are repeated floor hardware, not decals.
    for index, (x, y) in enumerate(((4.0, 1.05), (8.0, -1.55), (11.5, 3.40),
                                    (14.6, 2.30)), start=1):
        _box(bpy, f"V19_DrainGrate_{index}", (x, y, 0.030),
             (0.38, 0.22, 0.014), materials["drain"], bevel=0.008)
        for slot in range(7):
            _box(bpy, f"V19_DrainSlot_{index}_{slot}",
                 (x - 0.27 + slot * 0.09, y, 0.052),
                 (0.018, 0.18, 0.006), materials["fastener"], bevel=0.002)
        _torus(bpy, f"V19_CleanoutRing_{index}", (x + 0.62, y, 0.060),
               0.10, 0.015, materials["fastener"])

    # A compact overhead junction cabinet and four conduit drops break the
    # perfectly straight tray silhouette near the electrical boundary.
    _box(bpy, "V19_OverheadJunctionBody", (9.15, max_y - 1.12, 4.02),
         (0.36, 0.24, 0.28), materials["instrument"], bevel=0.022)
    _box(bpy, "V19_OverheadJunctionDoor", (9.15, max_y - 1.38, 4.02),
         (0.28, 0.018, 0.20), materials["instrument_door"], bevel=0.008)
    for drop in range(4):
        _pipe_between(bpy, f"V19_OverheadJunctionDrop_{drop}",
                      (8.82 + drop * 0.22, max_y - 1.12, 3.72),
                      (8.82 + drop * 0.22, max_y - 1.12, 2.96),
                      0.022, materials["conduit"])


def _add_v20_field_realism_layer(bpy, scene, bounds, materials):
    """Add local field evidence that keeps the plant from reading as a showroom.

    The layer is intentionally sparse and attached to plausible maintenance
    locations: panel joints, wall-foot grime, equipment plinths, weld zones and
    cable entries. It adds visual scale without covering inspection labels or
    turning the scene into a generic grunge pass.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Cladding panels have a dark gasket and a shallow horizontal overlap at
    # each assembly break. These are visible in wide shots and close camera
    # views, unlike a single broad wall texture.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 2), start=1):
        seam_x = x + 1.0
        _box(bpy, f"V20_NorthPanelJoint_{index}",
             (seam_x, max_y - 0.116, 4.15),
             (0.018, 0.012, 2.22), materials["wall_joint"], bevel=0)
        _box(bpy, f"V20_NorthPanelLap_{index}",
             (seam_x - 0.035, max_y - 0.132, 3.16),
             (0.040, 0.008, 0.018), materials["bare_steel"], bevel=0.002)
    for index, y in enumerate(range(math.ceil(min_y) + 1, math.floor(max_y), 2), start=1):
        seam_y = y + 1.0
        _box(bpy, f"V20_EastPanelJoint_{index}",
             (max_x - 0.116, seam_y, 4.15),
             (0.012, 0.018, 2.22), materials["wall_joint"], bevel=0)

    # Dust and moisture collect where the concrete wainscot meets the slab.
    _box(bpy, "V20_NorthWallFootGrime", (center_x, max_y - 0.187, 0.24),
         (max(1.0, (max_x - min_x) / 2 - 0.35), 0.012, 0.11),
         materials["base_dust"], bevel=0.012)
    _box(bpy, "V20_EastWallFootGrime", (max_x - 0.187, center_y, 0.24),
         (0.012, max(1.0, (max_y - min_y) / 2 - 0.35), 0.11),
         materials["base_dust"], bevel=0.012)
    for index, (x, y, sx, sy) in enumerate((
        (min_x + 2.0, max_y - 0.52, 0.55, 0.16),
        (center_x - 1.2, max_y - 0.54, 0.42, 0.12),
        (max_x - 2.0, max_y - 0.50, 0.62, 0.14),
        (max_x - 0.48, center_y - 3.4, 0.14, 0.66),
    ), start=1):
        _add_flat_stain(bpy, f"V20_WallFootPatch_{index}", (x, y, 0.020),
                        (sx, sy), materials["grime"])

    # Shadow/dust envelopes under equipment are slightly offset from the
    # plinths so the bases remain readable and the floor does not look tiled.
    for index, waypoint in enumerate(scene.get("waypoints", []), start=1):
        equipment_x, equipment_y = _equipment_position(waypoint)
        waypoint_id = waypoint.get("waypoint_id", "")
        if "CABINET" in waypoint_id:
            sx, sy = 1.18, 0.82
        elif "PUMP" in waypoint_id:
            sx, sy = 1.86, 1.12
        elif "PIPE" in waypoint_id:
            sx, sy = 1.72, 0.92
        elif "VESSEL" in waypoint_id:
            sx, sy = 1.10, 1.04
        else:
            sx, sy = 1.28, 0.76
        _add_flat_stain(
            bpy, f"V20_BaseDust_{index}",
            (equipment_x, equipment_y - 0.08, 0.022),
            (sx, sy), materials["base_dust"],
        )
        _add_flat_stain(
            bpy, f"V20_BaseShadow_{index}",
            (equipment_x + 0.08, equipment_y - 0.14, 0.026),
            (sx * 0.72, sy * 0.62), materials["floor_oil"],
        )

    # A weld bead is accompanied by a darker, wider heat-affected band. The
    # pair is placed on the visible process header and on a support joint.
    for index, x in enumerate((2.8, 3.5, 4.2, 4.9, 5.6), start=1):
        _torus(bpy, f"V20_SteamHeaderHeatZone_{index}", (x, 3.20, 2.55),
               0.222, 0.019, materials["heat_affected"],
               rotation=(0.0, math.pi / 2, 0.0))
    for index, x in enumerate((8.0, 10.0, 12.0, 14.0), start=1):
        _torus(bpy, f"V20_RackWeldHeatZone_{index}", (x, max_y - 1.15, 3.68),
               0.092, 0.012, materials["heat_affected"],
               rotation=(math.pi / 2, 0.0, 0.0))

    # Localised impact wear on columns, handrails and service plates. Small
    # bare-metal patches are more convincing than a uniform roughness change.
    for index, (x, y, z, sx, sy, sz) in enumerate((
        (min_x + 1.02, min_y + 0.36, 1.06, 0.010, 0.072, 0.050),
        (center_x - 0.18, max_y - 1.54, 4.24, 0.070, 0.010, 0.014),
        (8.0, -0.71, 0.66, 0.16, 0.010, 0.014),
        (11.5, 4.58, 0.72, 0.20, 0.010, 0.016),
    ), start=1):
        _box(bpy, f"V20_BareMetalWear_{index}", (x, y, z),
             (sx, sy, sz), materials["bare_steel"], bevel=0.002)

    # Add a few restrained cable drops with a service loop at the MCC and
    # pump. The sag is geometric, so it remains legible from oblique cameras.
    _pipe_path(
        bpy, "V20_MCC_CableBundle",
        ((7.20, -0.60, 2.65), (7.20, -0.90, 2.38),
         (7.52, -1.05, 2.18), (8.05, -1.05, 2.18)),
        0.028, materials["cable"],
    )
    _add_cable_loop(bpy, "V20_MCC_ServiceLoop", (8.38, -0.72, 1.06),
                    0.14, materials["cable"], rotation=(math.pi / 2, 0.0, 0.0))
    _pipe_path(
        bpy, "V20_Pump_SensorBundle",
        ((10.90, 6.22, 1.82), (11.20, 6.22, 1.58),
         (11.62, 6.10, 1.46), (12.10, 6.10, 1.46)),
        0.022, materials["conduit"],
    )
    _add_cable_loop(bpy, "V20_Pump_ServiceLoop", (12.22, 6.02, 1.46),
                    0.12, materials["cable"], rotation=(math.pi / 2, 0.0, 0.0))


def _add_irregular_flat_patch(bpy, name: str, location, scale, material):
    """Build a soft-edged irregular patch from overlapping flattened lobes."""
    x, y, z = location
    sx, sy = scale
    lobes = (
        (-0.55, 0.05, 0.72, 0.76),
        (-0.18, -0.24, 0.92, 0.68),
        (0.22, 0.18, 0.88, 0.82),
        (0.58, -0.04, 0.58, 0.64),
    )
    for index, (offset_x, offset_y, width, depth) in enumerate(lobes, start=1):
        _sphere(
            bpy, f"{name}_{index}",
            (x + offset_x * sx, y + offset_y * sy, z + 0.012 + index * 0.0008),
            (sx * width, sy * depth, 0.010 + (index % 2) * 0.002),
            material, segments=24,
        )


def _add_v21_realism_layer(bpy, scene, bounds, materials):
    """Add the close-range material evidence that separates a plant from a clean mock-up."""
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Vehicle and foot traffic leave broken, directional marks instead of
    # perfect oval decals. The small curves keep the evidence visible in wide
    # views without competing with the route overlay.
    traffic_marks = (
        (center_x - 5.4, min_y + 1.38, 1.55, 0.10),
        (center_x - 2.4, min_y + 2.04, 0.92, 0.07),
        (center_x + 2.55, center_y - 2.28, 1.85, 0.09),
        (max_x - 3.8, min_y + 0.96, 1.15, 0.08),
    )
    for index, (x, y, length, radius) in enumerate(traffic_marks, start=1):
        _pipe_path(
            bpy, f"V21_ForkliftScuff_{index}",
            ((x, y, 0.020), (x + length * 0.44, y + 0.025, 0.021),
             (x + length, y - 0.012, 0.020)),
            radius, materials["floor_scuff"],
        )
        _add_irregular_flat_patch(
            bpy, f"V21_TrafficDust_{index}", (x + length * 0.46, y, 0.018),
            (length * 0.54, 0.13), materials["dust_edge"],
        )

    # Oil and condensate collect in serviceable places: beneath the pump,
    # filter skid and maintenance bench. Multiple roughness layers read more
    # like a wet stain than the single flat patches used in earlier builds.
    wet_marks = (
        (11.95, 5.18, 0.55, 0.26),
        (15.62, -5.62, 0.44, 0.20),
        (-1.85, -5.35, 0.38, 0.18),
        (center_x + 4.6, center_y - 0.55, 0.32, 0.15),
    )
    for index, (x, y, sx, sy) in enumerate(wet_marks, start=1):
        _add_irregular_flat_patch(
            bpy, f"V21_OilHalo_{index}", (x, y, 0.020), (sx, sy),
            materials["floor_oil"],
        )
        _add_irregular_flat_patch(
            bpy, f"V21_OilSheen_{index}", (x + 0.04, y - 0.02, 0.026),
            (sx * 0.48, sy * 0.44), materials["oil_sheen"],
        )

    # Condensate drips break into beads as they reach the slab. This creates a
    # plausible vertical-to-horizontal transition under wall joints and drains.
    for index, (x, y, height) in enumerate((
        (min_x + 1.6, max_y - 0.19, 0.64),
        (center_x - 2.2, max_y - 0.19, 0.48),
        (max_x - 2.4, max_y - 0.19, 0.72),
        (max_x - 0.20, center_y - 2.8, 0.56),
    ), start=1):
        _pipe_between(
            bpy, f"V21_CondensateLine_{index}",
            (x, y, 0.42), (x + 0.018, y, 0.42 + height),
            0.012, materials["rust_scale"],
        )
        for bead in range(3):
            _sphere(
                bpy, f"V21_CondensateBead_{index}_{bead}",
                (x + 0.018 + bead * 0.020, y - 0.012, 0.10 + bead * 0.045),
                (0.030 - bead * 0.005, 0.020, 0.012), materials["rust_scale"],
                segments=16,
            )

    # Painted portal columns and cladding receive edge strikes, faded bands
    # and exposed substrate at service height. The marks are sparse by design.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 4), start=1):
        for side, y in enumerate((min_y + 0.355, max_y - 0.355), start=1):
            for mark, z in enumerate((0.78, 1.08, 1.42), start=1):
                _box(
                    bpy, f"V21_PortalEdgeWear_{index}_{side}_{mark}",
                    (x + 0.127, y, z + (index % 2) * 0.035),
                    (0.006, 0.035 + mark * 0.010, 0.010),
                    materials["bare_steel"], bevel=0.002,
                )
    for index, x in enumerate((min_x + 2.2, center_x - 2.6, center_x + 2.8, max_x - 1.8), start=1):
        _box(
            bpy, f"V21_CladdingPaintFade_{index}",
            (x, max_y - 0.142, 1.10 + index * 0.20),
            (0.16 + index * 0.018, 0.006, 0.010), materials["paint_fade"], bevel=0.002,
        )
        _box(
            bpy, f"V21_CladdingScratch_{index}",
            (x + 0.04, max_y - 0.151, 1.22 + index * 0.20),
            (0.085, 0.004, 0.006), materials["bare_steel"], bevel=0.001,
        )

    # Exposed cabinet internals get individually routed control wires and
    # ferrule tags, giving the open MCC a real termination layout.
    cabinet = next((item for item in scene.get("waypoints", [])
                    if "CABINET" in item.get("waypoint_id", "")), None)
    if cabinet:
        x, y = _equipment_position(cabinet)
        wire_materials = ("wire_red", "wire_blue", "wire_yellow", "wire_black", "copper")
        for index, key in enumerate(wire_materials, start=1):
            wire_x = x - 0.64 + (index - 1) * 0.28
            _pipe_path(
                bpy, f"V21_MCC_FieldWire_{index}",
                ((wire_x, y - 0.73, 0.72), (wire_x - 0.10, y - 0.75, 1.25),
                 (wire_x + 0.08, y - 0.75, 1.78), (wire_x, y - 0.75, 2.25)),
                0.013, materials[key],
            )
            _box(
                bpy, f"V21_MCC_Ferrule_{index}",
                (wire_x, y - 0.78, 2.30), (0.075, 0.010, 0.025),
                materials["label_white"], bevel=0.002,
            )
            _text(
                bpy, f"V21_MCC_FerruleText_{index}", f"{index:02d}",
                (wire_x, y - 0.795, 2.292), materials["ink"], size=0.024,
            )

    # The pump and exchanger show handling scratches on the painted shell and
    # different fastener finishes at maintenance-access height.
    pump = next((item for item in scene.get("waypoints", [])
                 if "PUMP" in item.get("waypoint_id", "")), None)
    if pump:
        x, y = _equipment_position(pump)
        motor_x = x - 0.74
        for index in range(5):
            _box(
                bpy, f"V21_PumpMotorScratch_{index}",
                (motor_x - 0.28 + index * 0.13, y - 0.425, 0.82 + (index % 2) * 0.13),
                (0.042 + (index % 2) * 0.020, 0.004, 0.007),
                materials["paint_fade"], bevel=0.001,
            )
        for index in range(6):
            _box(
                bpy, f"V21_PumpVoluteScratch_{index}",
                (x + 0.14 + index * 0.10, y - 0.505, 0.78 + index * 0.055),
                (0.030, 0.004, 0.006), materials["bare_steel"], bevel=0.001,
            )

    # Small barcode-like asset plates and lockout tags make industrial IDs
    # readable without relying on texture images or unverifiable real data.
    for index, (x, y, z, label) in enumerate((
        (11.85, 4.12, 1.90, "P-021"),
        (14.62, 4.48, 2.28, "E-201"),
        (8.02, -0.43, 2.56, "MCC-04"),
    ), start=1):
        _box(bpy, f"V21_IDPlate_{index}", (x, y, z),
             (0.25, 0.012, 0.075), materials["label_white"], bevel=0.004)
        for bar in range(7):
            width = 0.006 if bar % 3 else 0.012
            _box(
                bpy, f"V21_IDPlateBar_{index}_{bar}",
                (x - 0.17 + bar * 0.035, y - 0.015, z - 0.022),
                (width, 0.002, 0.025), materials["ink"], bevel=0.001,
            )
        _text(bpy, f"V21_IDPlateText_{index}", label,
              (x, y - 0.020, z + 0.032), materials["ink"], size=0.031)

    # Compressed gasket contact shadows and lock washers add a second edge at
    # selected flanges so close views do not read as single smooth cylinders.
    for index, (x, y, z, radius, rotation) in enumerate((
        (5.46, 3.20, 2.55, 0.222, (0.0, math.pi / 2, 0.0)),
        (12.28, 6.70, 1.04, 0.28, (math.pi / 2, 0.0, 0.0)),
        (15.32, 5.20, 1.62, 0.48, (0.0, math.pi / 2, 0.0)),
    ), start=1):
        _torus(bpy, f"V21_CompressedGasket_{index}", (x, y, z),
               radius * 0.92, radius * 0.028,
               materials["gasket_compressed"], rotation=rotation)

    # Drain lips and floor joints trap fine dust. These narrow strips are
    # intentionally placed below the walking surface, so the slab still reads
    # as concrete rather than a tiled graphic.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 4), start=1):
        _box(bpy, f"V21_ExpansionDust_{index}", (x + 0.025, center_y, 0.010),
             (0.020, max(0.8, (max_y - min_y) * 0.30), 0.003),
             materials["dust_edge"], bevel=0)


def _add_v22_industrial_completion_layer(bpy, scene, bounds, materials):
    """Add the last layer of operational hardware used in a working plant.

    v21 established surface wear and close-range evidence. This layer focuses
    on the relationships that make a wide shot read as an installed facility:
    access covers, flow tags, field cable entries, fixed CCTV hardware and a
    robot charging point. The parts are deliberately sparse and deterministic
    so they support inspection framing instead of becoming set dressing.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Service covers and anchor hardware break up the slab at plausible
    # maintenance locations. Bolt heads are separate geometry so they catch
    # the same highlights as the equipment fasteners.
    access_covers = (
        (center_x - 4.0, min_y + 2.0, 0.62, 0.42),
        (center_x + 0.8, min_y + 3.8, 0.52, 0.36),
        (max_x - 2.2, center_y - 2.1, 0.58, 0.40),
        (min_x + 2.0, center_y + 2.3, 0.46, 0.32),
    )
    for index, (x, y, sx, sy) in enumerate(access_covers, start=1):
        _box(bpy, f"V22_AccessCover_{index}", (x, y, 0.026),
             (sx, sy, 0.014), materials["drain"], bevel=0.008)
        for bolt, (dx, dy) in enumerate(((-sx * 0.70, -sy * 0.62),
                                          (sx * 0.70, -sy * 0.62),
                                          (-sx * 0.70, sy * 0.62),
                                          (sx * 0.70, sy * 0.62)), start=1):
            _cylinder(bpy, f"V22_AccessCoverBolt_{index}_{bolt}",
                      (x + dx, y + dy, 0.052), 0.024, 0.035,
                      materials["fastener"], vertices=6, bevel=0.003)
        for slot in range(5):
            _box(bpy, f"V22_AccessCoverSlot_{index}_{slot}",
                 (x - sx * 0.54 + slot * sx * 0.27, y, 0.047),
                 (0.012, sy * 0.70, 0.006), materials["steel_dark"], bevel=0.002)

    # Installed process lines carry directional bands and readable service
    # labels. The text stays short so it remains legible in robot-height shots.
    pipe_labels = (
        (2.55, 3.20, 2.55, "STM 302", "warning"),
        (8.60, max_y - 2.35, 4.58, "PROC", "label_white"),
        (13.80, max_y - 1.81, 4.92, "STM", "label_white"),
        (11.65, 6.28, 3.25, "CW", "warning"),
    )
    for index, (x, y, z, label, plate_material) in enumerate(pipe_labels, start=1):
        _box(bpy, f"V22_PipeLabelPlate_{index}", (x, y - 0.10, z),
             (0.30, 0.018, 0.075), materials[plate_material], bevel=0.004)
        _text(bpy, f"V22_PipeLabelText_{index}", label,
              (x, y - 0.125, z - 0.010), materials["ink"], size=0.040)
        _box(bpy, f"V22_PipeFlowBand_{index}", (x + 0.43, y, z),
             (0.028, 0.11, 0.11), materials["warning"], bevel=0.003)
        _text(bpy, f"V22_PipeFlowText_{index}", ">",
              (x + 0.43, y - 0.125, z - 0.02), materials["warning_black"], size=0.050)

    # Cable entries are tied down at the point where a tray becomes field
    # wiring. This adds real termination logic to wide shots and close views.
    cable_entries = (
        (4.00, 0.55, 2.55, 0.0),
        (8.00, -0.52, 2.18, 0.0),
        (11.50, 5.95, 1.72, math.pi / 2),
        (14.60, 4.28, 1.72, math.pi / 2),
    )
    for index, (x, y, z, rotation_z) in enumerate(cable_entries, start=1):
        _box(bpy, f"V22_CableEntryPlate_{index}", (x, y, z),
             (0.26, 0.08, 0.09), materials["instrument_door"], bevel=0.012)
        for gland in range(3):
            _cylinder(bpy, f"V22_CableEntryGland_{index}_{gland}",
                      (x - 0.14 + gland * 0.14, y - 0.095, z - 0.02),
                      0.028, 0.055, materials["rubber_seal"],
                      rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.004)
        if rotation_z:
            _pipe_between(bpy, f"V22_CableEntryConduit_{index}",
                          (x, y + 0.12, z), (x, y + 0.12, z + 0.34),
                          0.018, materials["conduit"])

    # Fixed cameras are part of the facility. The housings and service loops
    # appear in oblique views and anchor the CCTV feed to a physical location.
    cctv_mounts = (
        (max_x - 1.05, min_y + 0.92, 5.72, 1),
        (min_x + 1.05, max_y - 1.02, 5.46, -1),
    )
    for index, (x, y, z, direction) in enumerate(cctv_mounts, start=1):
        _box(bpy, f"V22_CCTV_Mount_{index}", (x, y, z + 0.34),
             (0.07, 0.07, 0.34), materials["steel_dark"], bevel=0.012)
        _box(bpy, f"V22_CCTV_Housing_{index}", (x, y, z),
             (0.20, 0.16, 0.13), materials["robot_dark"], bevel=0.035)
        _cylinder(bpy, f"V22_CCTV_Lens_{index}",
                  (x, y - direction * 0.18, z - 0.02), 0.072, 0.045,
                  materials["lens"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=32, bevel=0.004)
        _sphere(bpy, f"V22_CCTV_Status_{index}",
                (x + 0.13, y - direction * 0.04, z + 0.04),
                (0.018, 0.018, 0.018), materials["pilot_green"], segments=16)
        _pipe_between(bpy, f"V22_CCTV_ServiceLoop_{index}",
                      (x - 0.10, y + 0.12, z + 0.20),
                      (x - 0.10, y + 0.12, z - 0.20),
                      0.018, materials["conduit"])
        _box(bpy, f"V22_CCTV_Tag_{index}", (x, y - direction * 0.18, z - 0.22),
             (0.17, 0.012, 0.038), materials["label_white"], bevel=0.003)
        _text(bpy, f"V22_CCTV_TagText_{index}", f"CCTV-{index:02d}",
              (x, y - direction * 0.205, z - 0.232), materials["ink"], size=0.030)

    # A small charging/docking point gives the kinematic robot a credible
    # operational home without implying autonomous charging is implemented.
    dock_x, dock_y = min_x + 2.15, min_y + 1.25
    _box(bpy, "V22_RobotDockBase", (dock_x, dock_y, 0.12),
         (0.78, 0.48, 0.12), materials["steel_dark"], bevel=0.035)
    _box(bpy, "V22_RobotDockFace", (dock_x, dock_y - 0.49, 0.62),
         (0.62, 0.05, 0.52), materials["instrument"], bevel=0.025)
    _box(bpy, "V22_RobotDockPad", (dock_x, dock_y - 0.02, 0.275),
         (0.50, 0.32, 0.018), materials["warning"], bevel=0.005)
    for index, lamp in enumerate(("pilot_green", "warning"), start=1):
        _cylinder(bpy, f"V22_RobotDockLamp_{index}",
                  (dock_x - 0.16 + index * 0.16, dock_y - 0.56, 0.92),
                  0.035, 0.026, materials[lamp],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.004)
    _box(bpy, "V22_RobotDockLabel", (dock_x, dock_y - 0.56, 0.42),
         (0.30, 0.014, 0.055), materials["label_white"], bevel=0.004)
    _text(bpy, "V22_RobotDockLabelText", "ROBOT DOCK",
          (dock_x, dock_y - 0.58, 0.408), materials["ink"], size=0.038)

    # Add a few overhead cable drops with saddle clamps so the ceiling
    # infrastructure has vertical continuity instead of ending at the tray.
    for index, x in enumerate((center_x - 4.0, center_x - 0.8, center_x + 2.6,
                               center_x + 5.4), start=1):
        if not min_x + 0.6 < x < max_x - 0.6:
            continue
        _pipe_path(
            bpy, f"V22_OverheadDrop_{index}",
            ((x, max_y - 1.10, 4.78), (x, max_y - 1.10, 4.16),
             (x + 0.16, max_y - 1.36, 3.82),
             (x + 0.16, max_y - 1.36, 3.22)),
            0.020, materials["conduit"],
        )
        _add_pipe_clamp(bpy, f"V22_OverheadDropClamp_{index}",
                        (x, max_y - 1.10, 4.78), 0.020, materials, axis="z")

    # A real door has a frame, guides and a threshold. These are kept shallow
    # so the existing cutaway still works as the main viewing aperture.
    door_x = min_x + 0.16
    _box(bpy, "V22_RollUpDoorHeader", (door_x, center_y, 4.38),
         (0.12, 2.28, 0.12), materials["steel_dark"], bevel=0.018)
    for side in (-1, 1):
        _box(bpy, f"V22_RollUpDoorGuide_{side}",
             (door_x, center_y + side * 2.26, 2.10),
             (0.12, 0.08, 2.08), materials["steel_dark"], bevel=0.012)
    _box(bpy, "V22_RollUpDoorThreshold", (door_x + 0.12, center_y, 0.05),
         (0.18, 2.22, 0.035), materials["warning_black"], bevel=0.006)


def _add_v23_high_granularity_layer(bpy, scene, bounds, materials):
    """Add field-installation details that remain legible in inspection views.

    v22 completed the facility-level relationships. v23 concentrates on the
    last visible installation scale: occupied trays, terminations, weld
    witnesses, maintenance labels, and small interface hardware. The parts
    are sparse and placed only where a camera can use them as evidence.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Independent tray conductors make the overhead distribution path read as
    # installed wiring rather than a single dark procedural tube.
    tray_y = max_y - 1.10
    cable_specs = (
        ("wire_red", -0.22, 4.86, 0.014),
        ("wire_blue", -0.11, 4.89, 0.014),
        ("wire_yellow", 0.00, 4.92, 0.014),
        ("wire_black", 0.11, 4.89, 0.014),
        ("copper", 0.22, 4.86, 0.016),
    )
    cable_start, cable_end = min_x + 1.30, max_x - 1.30
    for index, (material_key, offset, z, radius) in enumerate(cable_specs, start=1):
        points = (
            (cable_start, tray_y + offset, z),
            (center_x - 3.20, tray_y + offset, z),
            (center_x + 1.20, tray_y + offset - 0.04, z - 0.02),
            (cable_end, tray_y + offset - 0.04, z - 0.02),
        )
        _pipe_path(bpy, f"V23_TrayConductor_{index}", points, radius,
                   materials[material_key])
        for clip_index, clip_x in enumerate((cable_start + 1.0, center_x - 1.2,
                                              center_x + 2.4, cable_end - 1.0), start=1):
            if cable_start < clip_x < cable_end:
                _box(bpy, f"V23_TrayTie_{index}_{clip_index}",
                     (clip_x, tray_y + offset, z + 0.028),
                     (0.028, 0.040, 0.012), materials["label_white"], bevel=0.002)

    # Vertical field drops carry the tray's color coding to the junction boxes.
    for index, waypoint in enumerate(scene.get("waypoints", [])[:6], start=1):
        equipment_x, equipment_y = _equipment_position(waypoint)
        drop_x = min(max(equipment_x, min_x + 1.35), max_x - 1.35)
        drop_y = equipment_y - 0.84
        _pipe_path(
            bpy, f"V23_FieldHarness_{index}",
            ((drop_x, tray_y, 4.74), (drop_x, drop_y, 4.74),
             (drop_x + 0.08, drop_y, 2.42),
             (equipment_x + 0.62, equipment_y - 0.64, 1.22)),
            0.018, materials["wire_black"],
        )
        for clip_index, z in enumerate((4.18, 3.54, 2.86), start=1):
            _box(bpy, f"V23_FieldHarnessClip_{index}_{clip_index}",
                 (drop_x + 0.02, drop_y, z), (0.055, 0.040, 0.018),
                 materials["fastener"], bevel=0.003)
        _box(bpy, f"V23_FieldHarnessTag_{index}",
             (equipment_x + 0.62, equipment_y - 0.70, 1.24),
             (0.23, 0.012, 0.042), materials["label_white"], bevel=0.003)
        _text(bpy, f"V23_FieldHarnessTagText_{index}",
              waypoint["waypoint_id"].replace("WP_", ""),
              (equipment_x + 0.62, equipment_y - 0.718, 1.228),
              materials["ink"], size=0.028)

    # MCC terminal rail: ferrules, colored conductors and a second earth bond
    # give the opened cabinet a credible termination sequence.
    cabinet = next((item for item in scene.get("waypoints", [])
                    if "CABINET" in item.get("waypoint_id", "")), None)
    if cabinet:
        x, y = _equipment_position(cabinet)
        _box(bpy, "V23_MCC_TerminalRail", (x - 0.08, y - 0.76, 1.18),
             (0.66, 0.018, 0.045), materials["steel_dark"], bevel=0.006)
        terminal_colors = ("wire_red", "wire_blue", "wire_yellow", "wire_black")
        for index in range(10):
            terminal_x = x - 0.62 + index * 0.14
            terminal_z = 0.92 + (index % 5) * 0.18
            _box(bpy, f"V23_MCC_TerminalBlock_{index}",
                 (terminal_x, y - 0.80, terminal_z),
                 (0.052, 0.040, 0.052), materials["breaker"], bevel=0.006)
            _cylinder(bpy, f"V23_MCC_TerminalScrew_{index}",
                      (terminal_x, y - 0.846, terminal_z), 0.014, 0.010,
                      materials["fastener"], rotation=(math.pi / 2, 0, 0),
                      vertices=12, bevel=0.002)
            wire_material = materials[terminal_colors[index % len(terminal_colors)]]
            _pipe_path(
                bpy, f"V23_MCC_TerminalWire_{index}",
                ((terminal_x, y - 0.85, terminal_z),
                 (terminal_x + 0.04, y - 0.96, terminal_z + 0.12),
                 (terminal_x + 0.02, y - 1.06, 1.84)),
                0.012, wire_material,
            )
            _box(bpy, f"V23_MCC_Ferrule_{index}",
                 (terminal_x + 0.02, y - 1.075, 1.88),
                 (0.042, 0.010, 0.020), materials["label_white"], bevel=0.002)
            _text(bpy, f"V23_MCC_FerruleText_{index}", f"{index + 10:02d}",
                  (terminal_x + 0.02, y - 1.092, 1.875), materials["ink"], size=0.022)
        _pipe_path(
            bpy, "V23_MCC_EarthBond",
            ((x - 0.78, y - 0.84, 0.62), (x - 0.92, y - 1.02, 0.62),
             (x - 0.92, y - 1.02, 0.20)),
            0.020, materials["copper"],
        )
        _box(bpy, "V23_MCC_LotoPlate", (x + 0.62, y - 0.82, 2.62),
             (0.18, 0.012, 0.080), materials["warning_plate"], bevel=0.004)
        _text(bpy, "V23_MCC_LotoText", "LOTO", (x + 0.62, y - 0.840, 2.605),
              materials["warning_ink"], size=0.042)

    # Weld beads and heat-affected bands are distinct geometry so they catch
    # a highlight in both the hero valve and process-floor cameras.
    weld_sites = (
        (5.46, 3.20, 2.55, 0.222, (0.0, math.pi / 2, 0.0)),
        (4.12, 1.00, 2.55, 0.204, (0.0, math.pi / 2, 0.0)),
        (12.28, 6.70, 1.04, 0.28, (math.pi / 2, 0.0, 0.0)),
        (15.32, 5.20, 1.62, 0.48, (0.0, math.pi / 2, 0.0)),
    )
    for index, (x, y, z, radius, rotation) in enumerate(weld_sites, start=1):
        _torus(bpy, f"V23_WeldBead_{index}", (x, y, z), radius * 1.01,
               radius * 0.026, materials["weld_bead"], rotation=rotation)
        _torus(bpy, f"V23_WeldHeatBand_{index}", (x, y, z), radius * 1.045,
               radius * 0.010, materials["heat_affected"], rotation=rotation)
        for bead in range(5):
            angle = math.tau * bead / 5.0
            _sphere(
                bpy, f"V23_WeldBeadTexture_{index}_{bead}",
                (x, y + math.sin(angle) * radius * 1.01,
                 z + math.cos(angle) * radius * 1.01),
                (radius * 0.034, radius * 0.022, radius * 0.022),
                materials["weld_bead"], segments=12,
            )

    # LOTO and line-service markers are physical plates, not floating decals.
    service_tags = (
        (4.00, 0.62, 3.18, "STM-302", "warning_plate"),
        (11.50, 5.64, 2.78, "P-021", "label_white"),
        (14.60, 4.42, 2.32, "E-201", "label_white"),
    )
    for index, (x, y, z, label, plate_key) in enumerate(service_tags, start=1):
        _box(bpy, f"V23_ServiceTag_{index}", (x, y, z),
             (0.25, 0.016, 0.060), materials[plate_key], bevel=0.004)
        _text(bpy, f"V23_ServiceTagText_{index}", label,
              (x, y - 0.022, z - 0.010), materials["ink"], size=0.034)

    # Panel seams receive a few captive fasteners and seal beads so the wall
    # reads as assembled cladding instead of a tessellated background plane.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 2), start=1):
        seam_x = x + 1.0
        for fastener_index, z in enumerate((1.62, 3.28, 4.76), start=1):
            _cylinder(bpy, f"V23_CladdingCaptiveFastener_{index}_{fastener_index}",
                      (seam_x, max_y - 0.158, z), 0.018, 0.026,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=6, bevel=0.002)
        _box(bpy, f"V23_CladdingSeal_{index}",
             (seam_x + 0.026, max_y - 0.154, 2.42),
             (0.006, 0.004, 1.28), materials["rubber_seal"], bevel=0)

    # Add the missing cross-direction floor joints and a few recessed anchor
    # sockets around the service aisle, keeping the walking surface readable.
    for index, y in enumerate((center_y - 3.6, center_y - 0.8, center_y + 2.0,
                               center_y + 4.8), start=1):
        if min_y + 0.4 < y < max_y - 0.4:
            _box(bpy, f"V23_FloorExpansionJointY_{index}", (center_x, y, 0.006),
                 ((max_x - min_x) * 0.43, 0.010, 0.004), materials["floor_joint"], bevel=0)
    for index, (x, y) in enumerate(((3.4, 0.52), (8.8, 0.52), (12.4, 5.75),
                                    (15.2, -2.20)), start=1):
        _cylinder(bpy, f"V23_RecessedAnchor_{index}", (x, y, 0.034), 0.050,
                  0.018, materials["steel_dark"], vertices=24, bevel=0.004)
        _torus(bpy, f"V23_RecessedAnchorRing_{index}", (x, y, 0.048), 0.052,
               0.008, materials["fastener"])

    # Fixed CCTV installation gets a gland plate and a short armored tail at
    # the wall entry, tying the synchronized feed to a physical mount.
    cctv_mounts = (
        (max_x - 1.05, min_y + 0.92, 5.72, 1),
        (min_x + 1.05, max_y - 1.02, 5.46, -1),
    )
    for index, (x, y, z, direction) in enumerate(cctv_mounts, start=1):
        _box(bpy, f"V23_CCTV_GlandPlate_{index}",
             (x - 0.28, y + direction * 0.10, z - 0.14),
             (0.14, 0.07, 0.10), materials["instrument_door"], bevel=0.010)
        for gland in range(2):
            _cylinder(bpy, f"V23_CCTV_Gland_{index}_{gland}",
                      (x - 0.34 + gland * 0.12, y + direction * 0.18, z - 0.14),
                      0.022, 0.045, materials["rubber_seal"],
                      rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.003)
        _pipe_path(
            bpy, f"V23_CCTV_ArmoredTail_{index}",
            ((x - 0.28, y + direction * 0.18, z - 0.14),
             (x - 0.52, y + direction * 0.36, z - 0.14),
             (x - 0.52, y + direction * 0.36, z - 0.52)),
            0.014, materials["conduit"],
        )


def _add_v24_operational_finish(bpy, scene, bounds, materials):
    """Add localized task lighting and installation evidence for close views.

    v24 is intentionally a finish layer rather than another large geometry
    pass. The scene already has the plant relationships; this layer gives the
    inspection assets their own light response and adds a few physical tags
    that remain readable when the operator switches between synchronized feeds.
    """
    min_x, max_x, min_y, max_y = bounds
    points = {item["waypoint_id"]: item for item in scene.get("waypoints", [])}

    # Local task lights separate the cool high-bay ambience from the warm
    # metal and instrument surfaces that the robot is supposed to inspect.
    task_lights = (
        ("Valve", (2.75, 0.82, 4.05), (4.00, 3.10, 2.58), 230, (1.0, 0.68, 0.42), 1.35),
        ("MCC", (6.55, -1.55, 3.35), (8.10, -0.46, 1.42), 185, (0.54, 0.72, 1.0), 1.15),
        ("Pump", (9.55, 3.78, 3.05), (11.55, 5.22, 1.28), 220, (1.0, 0.74, 0.52), 1.30),
        ("Instrument", (4.45, 1.38, 4.25), (5.10, 3.16, 2.82), 135, (0.72, 0.88, 1.0), 0.90),
    )
    for name, location, target, energy, color, size in task_lights:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = f"V24_TaskLight_{name}"
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.data.color = color
        _look_at(light, location, target)

    # Slim emissive inspection bars sit beneath selected access points. They
    # are geometry and light together, so the glow has a believable source.
    inspection_bars = (
        ("Valve", (4.00, 2.44, 2.08), (0.42, 0.025, 0.018), (0.78, 0.92, 0.82, 1)),
        ("MCC", (8.00, -0.42, 0.62), (0.36, 0.018, 0.016), (0.62, 0.84, 1.0, 1)),
        ("Pump", (11.50, 4.78, 0.62), (0.44, 0.020, 0.018), (1.0, 0.78, 0.52, 1)),
    )
    for name, location, half_extents, color in inspection_bars:
        _box(bpy, f"V24_InspectionBar_{name}", location, half_extents,
             materials["luminaire"], bevel=0.006)
        bpy.context.object.data.materials.clear()
        _assign(bpy.context.object, materials["luminaire"])
        bpy.ops.object.light_add(type="AREA", location=(location[0], location[1] - 0.10, location[2] + 0.16))
        light = bpy.context.object
        light.name = f"V24_InspectionBarLight_{name}"
        light.data.energy = 38
        light.data.shape = "RECTANGLE"
        light.data.size = max(0.28, half_extents[0] * 2.0)
        light.data.size_y = 0.18
        light.data.color = color[:3]
        _look_at(light, (location[0], location[1] - 0.10, location[2] + 0.16),
                 (location[0], location[1], location[2] - 0.35))

    # Physical calibration/witness tabs make the inspection targets read as
    # maintained assets rather than anonymous procedural primitives.
    witness_sites = (
        ("PIPE", (4.00, 2.74, 2.02), "PI-302 / CAL 2026"),
        ("MCC", (8.00, -0.77, 2.78), "MCC-04 / IR"),
        ("PUMP", (11.50, 5.10, 2.14), "P-021 / VIB"),
        ("E201", (14.60, 4.42, 2.10), "E-201 / TT"),
    )
    for index, (name, location, label) in enumerate(witness_sites, start=1):
        x, y, z = location
        _box(bpy, f"V24_WitnessPlate_{index}", location,
             (0.29, 0.014, 0.052), materials["label_white"], bevel=0.004)
        _text(bpy, f"V24_WitnessText_{index}", label,
              (x, y - 0.021, z - 0.010), materials["ink"], size=0.030)
        for rivet, dx in enumerate((-0.20, 0.20), start=1):
            _cylinder(bpy, f"V24_WitnessRivet_{index}_{rivet}",
                      (x + dx, y - 0.020, z), 0.010, 0.016,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=12, bevel=0.002)

    # Add a small cable gland and service loop to the high-value instrument
    # box. This is deliberately local so the macro camera has a termination
    # relationship to inspect without adding a generic wire forest.
    pipe = points.get("WP_01_PIPE")
    if pipe:
        x, y = _equipment_position(pipe)
        _cylinder(bpy, "V24_PT302_Gland", (x + 1.10, y - 0.87, 2.62),
                  0.040, 0.070, materials["rubber_seal"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=24, bevel=0.006)
        _add_cable_loop(bpy, "V24_PT302_ServiceLoop", (x + 1.10, y - 0.98, 2.42),
                        0.10, materials["wire_blue"], rotation=(math.pi / 2, 0.0, 0.0))

    # A restrained service-height dust line grounds the local assets to the
    # slab and keeps the new task lights from making the plant look showroom-new.
    for index, (x, y, sx, sy) in enumerate((
        (4.00, 2.20, 1.12, 0.16),
        (8.00, -0.55, 0.92, 0.14),
        (11.50, 4.58, 1.25, 0.18),
    ), start=1):
        _add_flat_stain(bpy, f"V24_ServiceDust_{index}", (x, y, 0.025),
                        (sx, sy), materials["dust_edge"])


def _add_v25_mcc_detail_layer(bpy, scene, bounds, materials):
    """Refine the MCC into a serviceable electrical enclosure close-up.

    Earlier layers established the cabinet shell and representative wiring, but
    the macro view still read as a foreground wire bundle. v25 keeps the
    installation relationship explicit: old loose bundle geometry is muted for
    the render, the existing ferrules are moved behind the service face, and a
    bounded set of DIN rails, terminal blocks, wire ducts, labels and earth
    hardware fills the cabinet at a plausible maintenance scale.
    """
    cabinet = next((item for item in scene.get("waypoints", [])
                    if "CABINET" in item.get("waypoint_id", "")), None)
    if cabinet is None:
        return
    x, y = _equipment_position(cabinet)

    # Keep the legacy scene layers in the saved .blend for provenance, but do
    # not let them compete with the v25 service-face geometry in close renders.
    # The v23 terminal blocks were still visible after their wires were moved;
    # that produced the repeated white-module pattern in the macro image.
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(("V20_MCC_CableBundle", "V20_MCC_ServiceLoop")):
            obj.hide_render = True
        elif obj.name.startswith((
            "DEV-CAB-108_CopperBus", "DEV-CAB-108_Terminal",
            "DEV-CAB-108_Breaker", "DEV-CAB-108_CableDrop",
        )):
            obj.hide_render = True
        elif obj.name.startswith((
            "V23_MCC_Terminal", "V23_MCC_LotoPlate", "V23_MCC_LotoText",
        )):
            obj.hide_render = True
        elif obj.name.startswith((
            "MCC_LocalControl", "MCC_ControlLamp", "MCC_ControlScreen",
            "MCC_ControlScreenText",
        )):
            obj.hide_render = True
        elif obj.name.startswith((
            "DEV-CAB-108_InnerBackplate", "DEV-CAB-108_Display",
            "DEV-CAB-108_PilotLamp", "DEV-CAB-108_Nameplate",
            "DEV-CAB-108_Label", "DEV-CAB-108_DoorFrame",
            "DEV-CAB-108_DoorSeal", "DEV-CAB-108_OpenDoor",
            "DEV-CAB-108_DoorStay", "DEV-CAB-108_DoorStiffener",
            "DEV-CAB-108_Hinge", "DEV-CAB-108_EarthBraid",
        )):
            obj.hide_render = True

    # Re-seat the earlier terminal hardware behind the new service-face layer,
    # but hide the old free-spanning conductors and open-door accessories from
    # the photographic layer. Their uniform radius and front-of-cabinet path
    # were the main source of occlusion in v24; v25 replaces them with routed,
    # labeled conductors and a clean service opening.
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(("V21_MCC_FieldWire", "V21_MCC_Ferrule",
                                "V21_MCC_FerruleText", "V23_MCC_TerminalWire",
                                "V23_MCC_Ferrule", "V23_MCC_FerruleText",
                                "V23_MCC_EarthBond", "V18_MCC_DoorLoop",
                                "V18_MCC_BusLabel", "V18_MCC_BusLabelText",
                                "V18_MCC_", "V23_FieldHarness_3",
                                "V23_FieldHarnessClip_3", "V23_FieldHarnessTag_3",
                                "V23_FieldHarnessTagText_3")):
            obj.hide_render = True

    front_y = y - 0.49
    rail_y = y - 0.56
    wire_y = y - 0.62

    # Three functional bays sit on a single dark service backplate. The bays
    # are deliberately different: power protection, control starters and field
    # termination. This avoids a repeated white-module grid and gives the
    # cabinet a readable electrical hierarchy.
    _box(bpy, "V25_MCC_ServiceBackplate", (x, front_y + 0.018, 1.54),
         (0.80, 0.018, 0.86), materials["steel_dark"], bevel=0.012)
    bay_centers = (x - 0.50, x, x + 0.50)
    bay_rows = (
        ("power", (1.04, 1.42, 1.80)),
        ("control", (1.16, 1.64)),
        ("field", (1.02, 1.30, 1.58)),
    )
    for bay_index, bay_x in enumerate(bay_centers, start=1):
        bay_kind, row_heights = bay_rows[bay_index - 1]
        _box(bpy, f"V25_MCC_BayDivider_{bay_index}", (bay_x, front_y - 0.008, 1.54),
             (0.018, 0.026, 0.86), materials["cabinet_frame"], bevel=0.004)
        _box(bpy, f"V25_MCC_BayRailTop_{bay_index}", (bay_x, rail_y, 2.02),
             (0.205, 0.026, 0.024), materials["fastener"], bevel=0.004)
        _box(bpy, f"V25_MCC_BayRailBottom_{bay_index}", (bay_x, rail_y, 0.88),
             (0.205, 0.026, 0.024), materials["fastener"], bevel=0.004)
        _box(bpy, f"V25_MCC_BayLabel_{bay_index}", (bay_x, y - 0.60, 2.30),
             (0.095, 0.012, 0.028), materials["label_white"], bevel=0.002)
        label = {"power": "QF1", "control": "K1", "field": "X1"}[bay_kind]
        _text(bpy, f"V25_MCC_BayLabelText_{bay_index}", label,
              (bay_x, y - 0.619, 2.291), materials["ink"], size=0.025)

        for component_index, z in enumerate(row_heights, start=1):
            housing_material = "steel_dark" if bay_kind != "field" else "cabinet_frame"
            face_material = "panel" if bay_kind != "field" else "label_plate"
            _box(bpy, f"V25_MCC_Component_{bay_index}_{component_index}",
                 (bay_x, rail_y - 0.015, z), (0.135, 0.070, 0.145),
                 materials[housing_material], bevel=0.010)
            _box(bpy, f"V25_MCC_BreakerFace_{bay_index}_{component_index}",
                 (bay_x, wire_y, z), (0.082, 0.018, 0.088),
                 materials[face_material], bevel=0.004)
            indicator_material = (
                "warning" if bay_kind == "power" and component_index == 1
                else "pilot_green" if bay_kind == "control"
                else "fastener"
            )
            _box(bpy, f"V25_MCC_BreakerToggle_{bay_index}_{component_index}",
                 (bay_x, wire_y - 0.021, z + 0.008),
                 (0.018, 0.008, 0.045), materials[indicator_material], bevel=0.003)
            _cylinder(bpy, f"V25_MCC_BreakerScrew_{bay_index}_{component_index}",
                      (bay_x - 0.052, wire_y - 0.022, z - 0.055), 0.009, 0.010,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=6, bevel=0.001)

    # Upper copper bars have insulating stand-offs and a restrained engraved
    # phase label; this gives the panel a power-side hierarchy.
    for index, bus_x in enumerate((x - 0.58, x - 0.29, x, x + 0.29), start=1):
        _cylinder(bpy, f"V25_MCC_Busbar_{index}", (bus_x, wire_y, 2.18),
                  0.026, 0.62, materials["copper"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=24, bevel=0.004)
        for stand_index, z in enumerate((2.04, 2.32), start=1):
            _cylinder(bpy, f"V25_MCC_BusStand_{index}_{stand_index}",
                      (bus_x, rail_y, z), 0.040, 0.030,
                      materials["rubber_seal"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=20, bevel=0.003)
        _box(bpy, f"V25_MCC_PhaseLabel_{index}", (bus_x, y - 0.60, 2.54),
             (0.064, 0.010, 0.025), materials["label_plate"], bevel=0.002)
        _text(bpy, f"V25_MCC_PhaseText_{index}", f"L{index}",
              (bus_x, y - 0.618, 2.532), materials["ink"], size=0.022)

    # Slotted wiring ducts organize the low-voltage harness and give the close
    # view a manufactured edge instead of a field of floating cylinders.
    _box(bpy, "V25_MCC_VerticalDuct", (x - 0.75, rail_y, 1.42),
         (0.075, 0.055, 0.86), materials["cabinet_frame"], bevel=0.010)
    _box(bpy, "V25_MCC_BottomDuct", (x - 0.06, rail_y, 0.70),
         (0.74, 0.055, 0.095), materials["cabinet_frame"], bevel=0.010)
    for index, z in enumerate((0.92, 1.10, 1.28, 1.46, 1.64, 1.82), start=1):
        _box(bpy, f"V25_MCC_VerticalDuctSlot_{index}",
             (x - 0.75, wire_y - 0.060, z), (0.046, 0.012, 0.022),
             materials["steel_dark"], bevel=0.002)
    for index, duct_x in enumerate((x - 0.62, x - 0.32, x - 0.02, x + 0.28, x + 0.58), start=1):
        _box(bpy, f"V25_MCC_BottomDuctSlot_{index}",
             (duct_x, wire_y - 0.060, 0.70), (0.042, 0.012, 0.022),
             materials["steel_dark"], bevel=0.002)

    # A compact terminal strip connects the internal devices to field wiring.
    terminal_z = 0.86
    _box(bpy, "V25_MCC_FieldTerminalRail", (x + 0.42, rail_y, terminal_z),
         (0.27, 0.030, 0.038), materials["fastener"], bevel=0.004)
    for index in range(6):
        terminal_x = x + 0.20 + index * 0.088
        _box(bpy, f"V25_MCC_FieldTerminal_{index}",
             (terminal_x, wire_y, terminal_z), (0.034, 0.042, 0.050),
             materials["label_plate"], bevel=0.004)
        _cylinder(bpy, f"V25_MCC_FieldTerminalScrew_{index}",
                  (terminal_x, wire_y - 0.050, terminal_z), 0.010, 0.010,
                  materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=6, bevel=0.001)
        _box(bpy, f"V25_MCC_FieldFerrule_{index}",
             (terminal_x, y - 0.70, 1.10), (0.035, 0.010, 0.018),
             materials["label_white"], bevel=0.002)
        _text(bpy, f"V25_MCC_FieldFerruleText_{index}", f"X{index + 1:02d}",
              (terminal_x, y - 0.718, 1.094), materials["ink"], size=0.018)

    # Six slim conductors are routed through the lower duct in layered service
    # paths. They drop vertically first and then travel horizontally, matching
    # a cabinet wiring practice instead of crossing the service face diagonally.
    wire_keys = ("wire_red", "wire_blue", "wire_black", "wire_black",
                 "copper", "copper")
    for index, material_key in enumerate(wire_keys):
        start_x = x - 0.54 + (index % 4) * 0.18
        end_x = x + 0.22 + (index % 6) * 0.088
        start_z = 1.93 - (index // 4) * 0.18
        duct_z = 0.78 + (index % 3) * 0.045
        points = (
            (start_x, wire_y - 0.015, start_z),
            (start_x, y - 0.70, start_z),
            (x - 0.68, y - 0.70, start_z),
            (x - 0.68, y - 0.70, duct_z),
            (end_x, y - 0.70, duct_z),
            (end_x, y - 0.70, terminal_z + 0.06),
        )
        _pipe_path(bpy, f"V25_MCC_ControlWire_{index + 1}", points,
                   0.0045, materials[material_key])
        _box(bpy, f"V25_MCC_WireMarker_{index + 1}",
             (start_x, y - 0.705, start_z - 0.10),
             (0.028, 0.010, 0.014), materials["label_white"], bevel=0.001)

    # Earth bar, braided bond, door gasket witness and a service warning plate
    # close the electrical story at the edge of the existing open door.
    _box(bpy, "V25_MCC_EarthBar", (x - 0.68, y - 0.61, 0.56),
         (0.13, 0.024, 0.028), materials["copper"], bevel=0.004)
    for index in range(4):
        _cylinder(bpy, f"V25_MCC_EarthBarScrew_{index}",
                  (x - 0.77 + index * 0.06, y - 0.65, 0.56), 0.010, 0.012,
                  materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=6, bevel=0.001)
    _pipe_path(bpy, "V25_MCC_EarthBraidV25",
               ((x - 0.68, y - 0.64, 0.56), (x - 0.76, y - 0.72, 0.44),
                (x - 0.82, y - 0.72, 0.22)), 0.014, materials["copper"])
    for side in (-1, 1):
        _box(bpy, f"V25_MCC_DoorGasket_{side}",
             (x + side * 0.75, y - 0.41, 1.42),
             (0.014, 0.010, 0.96), materials["rubber_seal"], bevel=0.003)
    _box(bpy, "V25_MCC_ServiceWarningPlate", (x + 0.58, y - 0.65, 0.56),
         (0.16, 0.012, 0.040), materials["warning_plate"], bevel=0.003)
    _text(bpy, "V25_MCC_ServiceWarningText", "415 V / LOTO",
          (x + 0.58, y - 0.669, 0.548), materials["warning_ink"], size=0.025)

    # Small coating wear and dust at the lower rail make the cabinet feel
    # installed and maintained rather than newly generated.
    _box(bpy, "V25_MCC_LowerRailWear", (x + 0.32, y - 0.67, 0.49),
         (0.18, 0.006, 0.008), materials["bare_steel"], bevel=0.001)
    _add_flat_stain(bpy, "V25_MCC_ServiceDust", (x, y - 0.74, 0.035),
                    (0.74, 0.12), materials["dust_edge"])


def _add_v26_mcc_realism_layer(bpy, scene, bounds, materials):
    """Replace the flat MCC face with an open, depth-readable service enclosure.

    v25 added representative electrical parts, but the original cabinet body
    remained an opaque box in front of most of that detail. v26 keeps the
    historical objects in the blend, hides them from the photographic layer,
    and builds the cabinet as assembled sheet metal around a real service
    opening. The result is intentionally a visual inspection proxy, not a
    manufacturer CAD model.
    """
    cabinet = next((item for item in scene.get("waypoints", [])
                    if "CABINET" in item.get("waypoint_id", "")), None)
    if cabinet is None:
        return
    x, y = _equipment_position(cabinet)

    # Remove the opaque legacy shell and all earlier service-face layers from
    # the render while keeping them in the saved blend for version history.
    hidden_prefixes = (
        "V25_MCC_", "V23_MCC_", "V21_MCC_", "V20_MCC_", "V18_MCC_",
        "DEV-CAB-108_Body", "DEV-CAB-108_Plinth", "DEV-CAB-108_Vent",
        "DEV-CAB-108_CableGland", "DEV-CAB-108_ServiceLight",
        "DEV-CAB-108_OpenDoor", "DEV-CAB-108_DoorFrame",
        "DEV-CAB-108_DoorSeal", "DEV-CAB-108_InnerBackplate",
        "DEV-CAB-108_DoorStay", "DEV-CAB-108_DoorStiffener",
        "DEV-CAB-108_Hinge", "DEV-CAB-108_EarthBraid",
        "DEV-CAB-108_CopperBus", "DEV-CAB-108_Terminal",
        "DEV-CAB-108_Breaker", "DEV-CAB-108_PilotLamp",
        "DEV-CAB-108_Display", "DEV-CAB-108_Nameplate",
        "DEV-CAB-108_Label", "V24_InspectionBar_MCC",
        "V24_InspectionBarLight_MCC",
        "FieldCableLabel_3", "FieldCableLabelText_3",
    )
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(hidden_prefixes):
            obj.hide_render = True

    # The prior MCC task light was tuned for the opaque cabinet. Lower it so
    # the new dark interior keeps readable contrast, then add a local service
    # source that actually sits inside the enclosure.
    for name in ("V24_TaskLight_MCC",):
        light = bpy.data.objects.get(name)
        if light is not None and light.type == "LIGHT":
            light.data.energy = 72
    for name in ("V24_TaskLight_Valve", "V24_TaskLight_Pump", "V24_TaskLight_Instrument"):
        light = bpy.data.objects.get(name)
        if light is not None and light.type == "LIGHT":
            light.data.energy = min(float(light.data.energy), 210)

    front_y = y - 0.58
    rear_y = y + 0.28
    z_floor, z_top = 0.28, 2.72
    outer_half_width = 1.16

    # Sheet-metal enclosure: side walls, roof, base and a recessed back panel
    # leave the front open so the camera can read multiple installation depths.
    _box(bpy, "V26_MCC_BasePlinth", (x, y, 0.15),
         (1.22, 0.58, 0.14), materials["mcc_shell"], bevel=0.035)
    _box(bpy, "V26_MCC_LeftSide", (x - outer_half_width, y - 0.02, 1.50),
         (0.10, 0.48, 1.18), materials["mcc_shell"], bevel=0.018)
    _box(bpy, "V26_MCC_RightSide", (x + outer_half_width, y - 0.02, 1.50),
         (0.10, 0.48, 1.18), materials["mcc_shell"], bevel=0.018)
    _box(bpy, "V26_MCC_Roof", (x, y - 0.02, z_top),
         (1.06, 0.48, 0.10), materials["mcc_shell"], bevel=0.018)
    _box(bpy, "V26_MCC_BottomPanel", (x, y - 0.02, z_floor),
         (1.06, 0.48, 0.09), materials["mcc_shell"], bevel=0.014)
    _box(bpy, "V26_MCC_RearBackplate", (x, rear_y, 1.50),
         (1.05, 0.055, 1.08), materials["mcc_back"], bevel=0.012)
    for bay_index, bay_x in enumerate((x - 0.70, x, x + 0.70), start=1):
        _box(bpy, f"V26_MCC_RearBay_{bay_index}", (bay_x, rear_y - 0.065, 1.50),
             (0.31, 0.018, 0.98), materials["mcc_back"], bevel=0.006)

    # Front frame and captive fasteners establish the opening boundary and
    # give the camera a manufactured edge instead of a floating display board.
    for side in (-1, 1):
        frame_x = x + side * 1.02
        _box(bpy, f"V26_MCC_FrontPost_{side}", (frame_x, front_y, 1.50),
             (0.075, 0.075, 1.15), materials["cabinet_frame"], bevel=0.012)
        for bolt_index, bolt_z in enumerate((0.48, 1.02, 1.96, 2.50), start=1):
            _cylinder(bpy, f"V26_MCC_FrontBolt_{side}_{bolt_index}",
                      (frame_x, front_y - 0.088, bolt_z), 0.022, 0.018,
                      materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                      vertices=12, bevel=0.003)
    for beam_name, beam_z in (("Top", 2.57), ("Bottom", 0.43)):
        _box(bpy, f"V26_MCC_FrontBeam_{beam_name}", (x, front_y, beam_z),
             (0.95, 0.075, 0.075), materials["cabinet_frame"], bevel=0.012)

    # Rear separators and service rails make the three functional zones read
    # as one cabinet assembly rather than three repeated white boxes.
    for separator_index, separator_x in enumerate((x - 0.35, x + 0.35), start=1):
        _box(bpy, f"V26_MCC_BaySeparator_{separator_index}",
             (separator_x, y - 0.01, 1.48), (0.024, 0.33, 1.02),
             materials["mcc_shell"], bevel=0.005)
    for rail_index, rail_z in enumerate((0.70, 1.36, 2.03), start=1):
        _box(bpy, f"V26_MCC_DINRail_{rail_index}", (x, y - 0.22, rail_z),
             (0.90, 0.025, 0.025), materials["fastener"], bevel=0.004)

    # Left bay: a vertical three-phase busbar chamber with insulating supports.
    for phase_index, bus_x in enumerate((x - 0.82, x - 0.64, x - 0.46), start=1):
        _cylinder(bpy, f"V26_MCC_Busbar_L{phase_index}",
                  (bus_x, y - 0.18, 1.55), 0.032, 1.48,
                  materials["copper"], vertices=24, bevel=0.004)
        for support_index, support_z in enumerate((0.78, 1.52, 2.25), start=1):
            _cylinder(bpy, f"V26_MCC_BusInsulator_{phase_index}_{support_index}",
                      (bus_x, y - 0.16, support_z), 0.065, 0.075,
                      materials["mcc_insulator"], vertices=24, bevel=0.005)
        _box(bpy, f"V26_MCC_BusLabel_{phase_index}",
             (bus_x, front_y - 0.025, 2.38), (0.065, 0.015, 0.030),
             materials["label_plate"], bevel=0.003)
        _text(bpy, f"V26_MCC_BusLabelText_{phase_index}", f"L{phase_index}",
              (bus_x, front_y - 0.048, 2.372), materials["ink"], size=0.025)
    _box(bpy, "V26_MCC_BusGuardTop", (x - 0.64, y - 0.30, 2.30),
         (0.28, 0.018, 0.025), materials["mcc_guard"], bevel=0.004)
    _box(bpy, "V26_MCC_BusGuardBottom", (x - 0.64, y - 0.30, 0.80),
         (0.28, 0.018, 0.025), materials["mcc_guard"], bevel=0.004)

    # Centre bay: one larger molded-case breaker and a starter assembly with
    # distinct housings, toggles, trip button and phase termination points.
    _box(bpy, "V26_MCC_MainBreakerHousing", (x, y - 0.18, 1.68),
         (0.27, 0.14, 0.46), materials["mcc_plastic"], bevel=0.024)
    _box(bpy, "V26_MCC_MainBreakerFace", (x, y - 0.35, 1.68),
         (0.22, 0.025, 0.36), materials["breaker"], bevel=0.010)
    _box(bpy, "V26_MCC_MainBreakerToggle", (x, y - 0.385, 1.74),
         (0.045, 0.018, 0.12), materials["warning"], bevel=0.008)
    _cylinder(bpy, "V26_MCC_MainBreakerTrip", (x + 0.13, y - 0.39, 1.42),
              0.030, 0.018, materials["pilot_red"],
              rotation=(math.pi / 2, 0.0, 0.0), vertices=24, bevel=0.004)
    for phase_index, phase_x in enumerate((x - 0.17, x, x + 0.17), start=1):
        _cylinder(bpy, f"V26_MCC_MainTerminal_{phase_index}",
                  (phase_x, y - 0.40, 2.12), 0.026, 0.030,
                  materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=12, bevel=0.003)
    _box(bpy, "V26_MCC_MainBreakerLabel", (x, y - 0.40, 2.20),
         (0.15, 0.012, 0.032), materials["label_white"], bevel=0.003)
    _text(bpy, "V26_MCC_MainBreakerLabelText", "QF1  63A",
          (x, y - 0.421, 2.192), materials["ink"], size=0.028)

    _box(bpy, "V26_MCC_StarterHousing", (x, y - 0.17, 0.96),
         (0.25, 0.13, 0.23), materials["mcc_plastic"], bevel=0.018)
    _box(bpy, "V26_MCC_StarterFace", (x, y - 0.33, 0.96),
         (0.19, 0.022, 0.17), materials["panel"], bevel=0.007)
    for indicator_index, (indicator_x, indicator_material) in enumerate(
            ((x - 0.10, "pilot_green"), (x, "warning"), (x + 0.10, "pilot_red")), start=1):
        _cylinder(bpy, f"V26_MCC_StarterLamp_{indicator_index}",
                  (indicator_x, y - 0.36, 1.05), 0.026, 0.018,
                  materials[indicator_material], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=24, bevel=0.004)
    for phase_index, phase_x in enumerate((x - 0.16, x, x + 0.16), start=1):
        _pipe_between(bpy, f"V26_MCC_BusLink_{phase_index}",
                      (phase_x, y - 0.30, 1.98),
                      (phase_x, y - 0.34, 1.86), 0.012, materials["copper"])

    # Right bay: DIN-mounted contactor, relay and a field terminal strip with
    # individual screw heads and ferrule markers.
    for module_index, (module_x, module_z, module_width, module_material) in enumerate(
            ((x + 0.48, 1.98, 0.19, "breaker"),
             (x + 0.72, 1.98, 0.22, "mcc_plastic"),
             (x + 0.90, 1.98, 0.12, "label_plate"),
             (x + 0.48, 1.35, 0.27, "mcc_plastic"),
             (x + 0.78, 1.35, 0.18, "breaker")), start=1):
        _box(bpy, f"V26_MCC_Module_{module_index}",
             (module_x, y - 0.19, module_z),
             (module_width / 2, 0.12, 0.22), materials[module_material], bevel=0.014)
        _box(bpy, f"V26_MCC_ModuleFace_{module_index}",
             (module_x, y - 0.34, module_z),
             (max(0.035, module_width / 2 - 0.035), 0.018, 0.16),
             materials["panel"], bevel=0.005)
    for lamp_index, lamp_x in enumerate((x + 0.52, x + 0.78), start=1):
        _cylinder(bpy, f"V26_MCC_RelayLamp_{lamp_index}",
                  (lamp_x, y - 0.37, 1.50), 0.022, 0.016,
                  materials["pilot_green" if lamp_index == 1 else "warning"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.003)

    terminal_z = 0.64
    for terminal_index in range(8):
        terminal_x = x + 0.36 + terminal_index * 0.145
        _box(bpy, f"V26_MCC_TerminalBlock_{terminal_index}",
             (terminal_x, y - 0.24, terminal_z), (0.052, 0.105, 0.075),
             materials["mcc_plastic" if terminal_index % 3 else "label_plate"], bevel=0.006)
        _cylinder(bpy, f"V26_MCC_TerminalScrew_{terminal_index}",
                  (terminal_x, y - 0.36, terminal_z + 0.01), 0.016, 0.014,
                  materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=8, bevel=0.002)
        _box(bpy, f"V26_MCC_TerminalMarker_{terminal_index}",
             (terminal_x, y - 0.37, terminal_z - 0.09), (0.042, 0.008, 0.014),
             materials["label_white"], bevel=0.002)
        _text(bpy, f"V26_MCC_TerminalMarkerText_{terminal_index}",
              f"X{terminal_index + 1:02d}",
              (terminal_x, y - 0.386, terminal_z - 0.095), materials["ink"], size=0.018)

    # Slotted ducts frame the wiring rather than letting conductors float in
    # front of the cabinet. The slots are separate geometry for hard edges.
    for duct_index, duct_x in enumerate((x - 0.94, x + 0.94), start=1):
        _box(bpy, f"V26_MCC_VerticalDuct_{duct_index}",
             (duct_x, y - 0.18, 1.50), (0.075, 0.11, 0.92),
             materials["mcc_duct"], bevel=0.012)
        for slot_index, slot_z in enumerate((0.76, 0.94, 1.12, 1.30, 1.48,
                                              1.66, 1.84, 2.02, 2.20), start=1):
            _box(bpy, f"V26_MCC_DuctSlot_{duct_index}_{slot_index}",
                 (duct_x, y - 0.30, slot_z), (0.045, 0.012, 0.024),
                 materials["mcc_back"], bevel=0.002)
    _box(bpy, "V26_MCC_BottomDuct", (x, y - 0.18, 0.49),
         (0.88, 0.11, 0.075), materials["mcc_duct"], bevel=0.012)
    for slot_index, slot_x in enumerate((x - 0.72, x - 0.48, x - 0.24, x,
                                          x + 0.24, x + 0.48, x + 0.72), start=1):
        _box(bpy, f"V26_MCC_BottomDuctSlot_{slot_index}",
             (slot_x, y - 0.30, 0.49), (0.050, 0.012, 0.024),
             materials["mcc_back"], bevel=0.002)

    # Routed low-voltage conductors use distinct colors and stay behind the
    # terminal labels, which gives the close camera a believable wiring order.
    wire_specs = (
        ("wire_red", x - 0.18, x + 0.38, 1.94),
        ("wire_blue", x - 0.04, x + 0.53, 1.88),
        ("wire_black", x + 0.10, x + 0.68, 1.82),
        ("wire_yellow", x + 0.22, x + 0.82, 1.76),
        ("wire_red", x + 0.02, x + 0.96, 1.30),
        ("wire_blue", x + 0.16, x + 0.84, 1.24),
        ("wire_black", x + 0.30, x + 0.70, 1.18),
        ("wire_yellow", x + 0.44, x + 0.56, 1.12),
    )
    wire_route_y = y - 0.28
    right_duct_x = x + 0.94
    for wire_index, (material_key, start_x, end_x, start_z) in enumerate(wire_specs, start=1):
        end_z = 0.74 + (wire_index % 4) * 0.035
        points = (
            (start_x, y - 0.36, start_z),
            (start_x, wire_route_y, start_z),
            (right_duct_x, wire_route_y, start_z),
            (right_duct_x, wire_route_y, end_z),
            (end_x, wire_route_y, end_z),
            (end_x, y - 0.36, end_z),
        )
        _pipe_path(bpy, f"V26_MCC_ControlWire_{wire_index}", points,
                   0.0045, materials[material_key])
        _box(bpy, f"V26_MCC_WireClip_{wire_index}",
             (right_duct_x, wire_route_y - 0.012, start_z),
             (0.022, 0.012, 0.018), materials["fastener"], bevel=0.003)

    # Open door, hinge barrels and earth bond complete the enclosure story.
    door = _box(bpy, "V26_MCC_OpenDoor", (x + 1.42, y - 0.13, 1.50),
                (0.50, 0.045, 1.15), materials["cabinet_door"], bevel=0.028)
    door.rotation_euler[2] = math.radians(-21)
    for rib_index, rib_z in enumerate((0.72, 1.28, 1.84, 2.34), start=1):
        rib = _box(bpy, f"V26_MCC_DoorRib_{rib_index}",
                   (x + 1.42, y - 0.19, rib_z), (0.38, 0.018, 0.018),
                   materials["steel_dark"], bevel=0.004)
        rib.rotation_euler[2] = math.radians(-21)
    for hinge_index, hinge_z in enumerate((0.60, 1.50, 2.38), start=1):
        _cylinder(bpy, f"V26_MCC_Hinge_{hinge_index}",
                  (x + 1.02, y - 0.54, hinge_z), 0.050, 0.16,
                  materials["fastener"], rotation=(0.0, math.pi / 2, 0.0),
                  vertices=24, bevel=0.005)
    _box(bpy, "V26_MCC_DoorHandle", (x + 1.58, y - 0.47, 1.52),
         (0.07, 0.025, 0.15), materials["fastener"], bevel=0.008)
    _box(bpy, "V26_MCC_RatingPlate", (x, front_y - 0.12, 2.42),
         (0.34, 0.016, 0.075), materials["label_plate"], bevel=0.006)
    _text(bpy, "V26_MCC_RatingText", "MCC-04  /  415 V",
          (x, front_y - 0.145, 2.405), materials["ink"], size=0.044)
    _box(bpy, "V26_MCC_LOTOPlate", (x + 0.64, front_y - 0.12, 0.52),
         (0.18, 0.014, 0.045), materials["warning_plate"], bevel=0.004)
    _text(bpy, "V26_MCC_LOTOText", "LOTO",
          (x + 0.64, front_y - 0.144, 0.51), materials["warning_ink"], size=0.028)
    _box(bpy, "V26_MCC_EarthBar", (x - 0.82, y - 0.39, 0.58),
         (0.13, 0.022, 0.028), materials["copper"], bevel=0.004)
    for screw_index in range(4):
        _cylinder(bpy, f"V26_MCC_EarthScrew_{screw_index}",
                  (x - 0.91 + screw_index * 0.06, y - 0.43, 0.58),
                  0.012, 0.014, materials["fastener"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=8, bevel=0.002)
    _pipe_path(bpy, "V26_MCC_EarthBond",
               ((x - 0.82, y - 0.43, 0.58), (x - 0.98, y - 0.52, 0.44),
                (x - 1.06, y - 0.42, 0.30)), 0.015, materials["copper"])

    # A soft internal source gives the dark enclosure depth without lifting
    # the entire factory exposure.
    bpy.ops.object.light_add(type="AREA", location=(x - 0.10, y - 1.02, 2.10))
    interior_light = bpy.context.object
    interior_light.name = "V26_MCC_InteriorServiceLight"
    interior_light.data.energy = 58
    interior_light.data.shape = "RECTANGLE"
    interior_light.data.size = 0.72
    interior_light.data.size_y = 1.08
    interior_light.data.color = (0.52, 0.68, 1.0)
    _look_at(interior_light, (x - 0.10, y - 1.02, 2.10), (x, y + 0.16, 1.38))
    bpy.ops.object.light_add(type="AREA", location=(x + 1.05, y - 0.66, 2.30))
    edge_light = bpy.context.object
    edge_light.name = "V26_MCC_DoorEdgeLight"
    edge_light.data.energy = 32
    edge_light.data.shape = "DISK"
    edge_light.data.size = 0.42
    edge_light.data.color = (1.0, 0.56, 0.28)
    _look_at(edge_light, (x + 1.05, y - 0.66, 2.30), (x + 0.65, y - 0.20, 1.32))


def _add_v27_global_presentation_layer(bpy, scene, bounds, materials):
    """Add plant-wide installation evidence and a more deliberate presentation layer.

    The earlier versions concentrated detail around inspection assets. v27 fills
    the visual scale between those assets: believable high-bay fixtures,
    wall-mounted service hardware, floor access points, electrical boundary
    markings and a robot charging point. These are restrained additions so the
    factory still reads as an operating plant rather than a decorated set.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # High-bay luminaires are physical housings plus local light sources. They
    # break the dark ceiling silhouette and give wide shots a believable light
    # rhythm without lifting the whole scene with a flat ambient fill.
    luminaire_positions = (
        (center_x - 5.2, center_y - 2.8),
        (center_x - 0.8, center_y - 2.8),
        (center_x + 3.8, center_y - 2.8),
        (center_x - 3.4, center_y + 2.2),
        (center_x + 1.8, center_y + 2.2),
        (center_x + 6.2, center_y + 2.2),
    )
    for index, (light_x, light_y) in enumerate(luminaire_positions, start=1):
        _box(bpy, f"V27_HighBayHousing_{index}", (light_x, light_y, 5.78),
             (1.05, 0.13, 0.045), materials["light_housing"], bevel=0.018)
        _box(bpy, f"V27_HighBayDiffuser_{index}", (light_x, light_y, 5.72),
             (0.82, 0.055, 0.018), materials["luminaire"], bevel=0.006)
        for side in (-1, 1):
            _pipe_between(bpy, f"V27_HighBayHanger_{index}_{side}",
                          (light_x + side * 0.72, light_y, 5.84),
                          (light_x + side * 0.72, light_y, 6.12),
                          0.016, materials["conduit"])
        bpy.ops.object.light_add(type="AREA", location=(light_x, light_y, 5.56))
        light = bpy.context.object
        light.name = f"V27_HighBayLight_{index}"
        light.data.energy = 150
        light.data.shape = "RECTANGLE"
        light.data.size = 1.75
        light.data.size_y = 0.42
        light.data.color = (0.82, 0.91, 1.0) if index % 3 else (1.0, 0.76, 0.52)
        _look_at(light, (light_x, light_y, 5.56), (light_x, light_y, 0.0))

    # Wall-mounted service boxes and labelled penetrations add scale to the
    # large cladding surfaces visible in overview and CCTV views.
    for index, wall_x in enumerate((min_x + 2.3, center_x - 2.6, center_x + 2.1,
                                    max_x - 2.3), start=1):
        if not (min_x + 1.0 < wall_x < max_x - 1.0):
            continue
        wall_y = max_y - 0.28
        _box(bpy, f"V27_WallServiceBox_{index}", (wall_x, wall_y, 2.85),
             (0.32, 0.08, 0.38), materials["instrument"], bevel=0.018)
        _box(bpy, f"V27_WallServiceDoor_{index}", (wall_x, wall_y - 0.095, 2.85),
             (0.25, 0.016, 0.29), materials["instrument_door"], bevel=0.008)
        _cylinder(bpy, f"V27_WallServiceLatch_{index}",
                  (wall_x + 0.18, wall_y - 0.12, 2.85), 0.022, 0.016,
                  materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=12, bevel=0.003)
        _box(bpy, f"V27_WallServiceTag_{index}", (wall_x, wall_y - 0.12, 2.37),
             (0.18, 0.012, 0.038), materials["label_plate"], bevel=0.004)
        _text(bpy, f"V27_WallServiceTagText_{index}", f"JB-{index:02d}",
              (wall_x, wall_y - 0.141, 2.36), materials["ink"], size=0.026)
        _pipe_path(bpy, f"V27_WallServiceConduit_{index}",
                   ((wall_x - 0.18, wall_y - 0.04, 2.50),
                    (wall_x - 0.18, wall_y - 0.04, 1.78),
                    (wall_x, wall_y - 0.04, 1.78)),
                   0.018, materials["conduit"])

    # Raised floor service boxes and anchor clusters make the slab read as a
    # maintainable industrial floor instead of a tiled graphic plane.
    floor_hardware = (
        (center_x - 5.4, center_y - 2.8, "A"),
        (center_x - 1.2, center_y - 2.8, "B"),
        (center_x + 3.0, center_y - 2.8, "C"),
        (center_x + 6.0, center_y + 0.6, "D"),
        (center_x - 3.0, center_y + 3.2, "E"),
    )
    for index, (floor_x, floor_y, suffix) in enumerate(floor_hardware, start=1):
        if not (min_x + 0.7 < floor_x < max_x - 0.7 and min_y + 0.7 < floor_y < max_y - 0.7):
            continue
        _box(bpy, f"V27_FloorServiceBox_{suffix}", (floor_x, floor_y, 0.055),
             (0.28, 0.20, 0.025), materials["drain"], bevel=0.008)
        for bolt_index, (dx, dy) in enumerate(((-0.20, -0.13), (0.20, -0.13),
                                                 (-0.20, 0.13), (0.20, 0.13)), start=1):
            _cylinder(bpy, f"V27_FloorServiceBolt_{suffix}_{bolt_index}",
                      (floor_x + dx, floor_y + dy, 0.092), 0.018, 0.020,
                      materials["fastener"], vertices=6, bevel=0.003)
        _box(bpy, f"V27_FloorServiceStripe_{suffix}",
             (floor_x, floor_y - 0.25, 0.040), (0.38, 0.018, 0.006),
             materials["warning_plate"], bevel=0.002)

    # Fixed safety signage is placed on the electrical boundary and the north
    # wall. The short labels remain legible in close views without polluting the
    # synchronized RGB/CCTV evidence with navigation overlays.
    signs = (
        (center_x - 1.9, min_y + 0.18, 2.82, "PPE  REQUIRED"),
        (center_x + 1.0, min_y + 0.18, 2.82, "ARC  FLASH"),
        (center_x + 4.2, max_y - 0.31, 3.35, "EYEWASH"),
    )
    for index, (sign_x, sign_y, sign_z, label) in enumerate(signs, start=1):
        _box(bpy, f"V27_SafetySign_{index}", (sign_x, sign_y, sign_z),
             (0.42, 0.024, 0.14), materials["warning_plate"], bevel=0.008)
        _text(bpy, f"V27_SafetySignText_{index}", label,
              (sign_x, sign_y - 0.035, sign_z - 0.012), materials["warning_ink"],
              size=0.040)
        _add_plate_rivets(bpy, f"V27_SafetySignRivets_{index}",
                          (sign_x, sign_y, sign_z), (0.42, 0.024, 0.14), materials)

    # A charging/docking point makes the robot part of the operating plant,
    # instead of an object that only appears on the route line.
    dock_x, dock_y = min_x + 3.0, min_y + 2.2
    _box(bpy, "V27_RobotDockPad", (dock_x, dock_y, 0.035),
         (0.72, 0.52, 0.025), materials["grating"], bevel=0.012)
    _box(bpy, "V27_RobotDockBackplate", (dock_x, dock_y + 0.46, 0.88),
         (0.54, 0.08, 0.72), materials["steel_dark"], bevel=0.018)
    _box(bpy, "V27_RobotDockCharger", (dock_x, dock_y + 0.34, 0.92),
         (0.30, 0.04, 0.24), materials["instrument"], bevel=0.012)
    _box(bpy, "V27_RobotDockDisplay", (dock_x, dock_y + 0.285, 0.99),
         (0.16, 0.012, 0.07), materials["display"], bevel=0.006)
    _text(bpy, "V27_RobotDockText", "DOCK / CHARGE",
          (dock_x, dock_y + 0.265, 0.96), materials["display_text"], size=0.032)
    for index, color_key in enumerate(("pilot_green", "warning"), start=1):
        _cylinder(bpy, f"V27_RobotDockLamp_{index}",
                  (dock_x - 0.12 + (index - 1) * 0.24, dock_y + 0.28, 1.18),
                  0.028, 0.018, materials[color_key],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.003)
    _pipe_path(bpy, "V27_RobotDockCable",
               ((dock_x + 0.32, dock_y + 0.28, 0.56),
                (dock_x + 0.70, dock_y + 0.28, 0.56),
                (dock_x + 0.70, dock_y + 0.08, 0.20)),
               0.018, materials["cable"])

    # Short labelled pipe bands establish the plant's operating language in
    # the wide composition and provide visual anchors for navigation.
    pipe_tags = (
        (3.15, 3.20, 2.55, "STEAM"),
        (11.20, 5.70, 2.55, "CW-RETURN"),
        (center_x + 0.8, max_y - 2.72, 3.72, "IA"),
    )
    for index, (tag_x, tag_y, tag_z, label) in enumerate(pipe_tags, start=1):
        _box(bpy, f"V27_ProcessTag_{index}", (tag_x, tag_y - 0.19, tag_z),
             (0.20, 0.016, 0.038), materials["label_plate"], bevel=0.004)
        _text(bpy, f"V27_ProcessTagText_{index}", label,
              (tag_x, tag_y - 0.215, tag_z - 0.010), materials["ink"], size=0.030)


def _add_v28_micro_geometry_layer(bpy, scene, bounds, materials):
    """Add close-range manufactured cues that survive a moving RGB camera."""
    min_x, max_x, min_y, max_y = bounds

    # Captive fasteners and vertical seams on the visible north cladding.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 2), start=1):
        for z in (3.05, 5.05):
            _cylinder(
                bpy, f"V28_NorthCladdingFastener_{index}_{int(z * 10)}",
                (x, max_y - 0.115, z), 0.024, 0.012, materials["fastener"],
                rotation=(math.pi / 2, 0, 0), vertices=12, bevel=0.003,
            )
        _box(
            bpy, f"V28_NorthCladdingSeam_{index}", (x + 0.94, max_y - 0.108, 4.15),
            (0.010, 0.006, 2.27), materials["wall_joint"], bevel=0.002,
        )

    # East wall panel anchors are oriented into the wall plane.
    for index, y in enumerate(range(math.ceil(min_y) + 1, math.floor(max_y), 2), start=1):
        for z in (3.05, 5.05):
            _cylinder(
                bpy, f"V28_EastCladdingFastener_{index}_{int(z * 10)}",
                (max_x - 0.115, y, z), 0.024, 0.012, materials["fastener"],
                rotation=(0, math.pi / 2, 0), vertices=12, bevel=0.003,
            )

    # Short service glands and strain reliefs at field junction boxes make the
    # wall-to-equipment wiring read as installed hardware.
    for index, (x, y, z) in enumerate(((1.1, 2.15, 2.72), (5.4, 3.22, 2.72),
                                       (8.6, -0.72, 1.52), (12.4, 5.6, 1.72)), start=1):
        _box(bpy, f"V28_ServicePlate_{index}", (x, y, z), (0.12, 0.055, 0.10),
             materials["label_plate"], bevel=0.008)
        for gland in (-0.055, 0.055):
            _cylinder(
                bpy, f"V28_ServiceGland_{index}_{gland}", (x + gland, y - 0.065, z - 0.005),
                0.018, 0.065, materials["conduit"], rotation=(math.pi / 2, 0, 0),
                vertices=16, bevel=0.003,
            )
        _pipe_between(
            bpy, f"V28_ServiceTail_{index}", (x, y - 0.09, z - 0.005),
            (x, y - 0.34, z - 0.005), 0.012, materials["conduit"],
        )

    # A restrained set of floor joint inserts adds scale and catches light at
    # low robot height without turning the route into a decorative grid.
    for index, x in enumerate(range(math.ceil(min_x) + 2, math.floor(max_x), 3), start=1):
        _box(
            bpy, f"V28_FloorJoint_{index}", (x, min_y + 0.72, -0.005),
            (0.012, max(0.6, (max_y - min_y) * 0.42), 0.004),
            materials["floor_joint"], bevel=0.001,
        )

    # Calibration witness plates anchor close-up frames to a physical datum.
    for index, waypoint in enumerate(scene.get("waypoints", []), start=1):
        x, y = float(waypoint["x"]), float(waypoint["y"])
        _box(
            bpy, f"V28_CalibrationWitness_{index}", (x - 0.28, y - 0.44, 0.045),
            (0.18, 0.035, 0.012), materials["label_plate"], bevel=0.004,
        )
        _cylinder(
            bpy, f"V28_CalibrationRivet_{index}", (x - 0.41, y - 0.44, 0.062),
            0.012, 0.008, materials["fastener"], vertices=12, bevel=0.002,
        )


def _add_v35_material_breakup(material, *, scale: float, dark_factor: float,
                              light_factor: float, bump_strength: float,
                              bump_distance: float, roughness_min: float,
                              roughness_max: float):
    """Add a restrained manufacturing-scale breakup to a material.

    Earlier layers already provide broad noise, mid-scale variation and a
    microfinish. v35 keeps those layers and adds a second signal that combines
    noise and cellular distance: powder coat, cast metal and concrete therefore
    stop sharing the same smooth procedural highlight.
    """
    if not getattr(material, "use_nodes", False):
        return material
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        return material

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = f"{material.name}_V35Coordinates"
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = f"{material.name}_V35CoatingNoise"
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.82
    links.new(texcoord.outputs["Object"], noise.inputs["Vector"])

    cells = nodes.new("ShaderNodeTexVoronoi")
    cells.name = f"{material.name}_V35SurfaceCells"
    cells.distance = "EUCLIDEAN"
    cells.feature = "DISTANCE_TO_EDGE"
    cells.inputs["Scale"].default_value = scale * 0.34
    links.new(texcoord.outputs["Object"], cells.inputs["Vector"])

    # Preserve the existing broad material network and multiply a subtle coat
    # response over it. The variation is deliberately small so labels and
    # sensor faces remain readable.
    base_socket = shader.inputs.get("Base Color")
    if base_socket is not None:
        previous_link = base_socket.links[0].from_socket if base_socket.links else None
        previous_default = tuple(float(value) for value in base_socket.default_value)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.name = f"{material.name}_V35CoatingRamp"
        base = tuple(float(value) for value in material.diffuse_color[:3])
        ramp.color_ramp.elements[0].color = tuple(
            max(0.0, min(1.0, value * dark_factor)) for value in base
        ) + (1.0,)
        ramp.color_ramp.elements[1].color = tuple(
            max(0.0, min(1.0, value * light_factor + 0.008)) for value in base
        ) + (1.0,)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

        mix = nodes.new("ShaderNodeMixRGB")
        mix.name = f"{material.name}_V35CoatingMix"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 0.34
        if previous_link is not None:
            links.new(previous_link, mix.inputs[1])
        else:
            mix.inputs[1].default_value = previous_default
        links.new(ramp.outputs["Color"], mix.inputs[2])
        for link in list(base_socket.links):
            links.remove(link)
        links.new(mix.outputs["Color"], base_socket)

    detail_mix = nodes.new("ShaderNodeMixRGB")
    detail_mix.name = f"{material.name}_V35DetailMask"
    detail_mix.blend_type = "MULTIPLY"
    detail_mix.inputs[0].default_value = 0.62
    links.new(noise.outputs["Fac"], detail_mix.inputs[1])
    links.new(cells.outputs["Distance"], detail_mix.inputs[2])
    bump = nodes.new("ShaderNodeBump")
    bump.name = f"{material.name}_V35ManufacturingBump"
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_distance
    links.new(detail_mix.outputs["Color"], bump.inputs["Height"])
    _chain_normal_layer(shader, links, bump.inputs["Normal"], bump.outputs["Normal"])

    roughness_socket = shader.inputs.get("Roughness")
    if roughness_socket is not None:
        roughness_map = nodes.new("ShaderNodeMapRange")
        roughness_map.name = f"{material.name}_V35RoughnessVariation"
        roughness_map.inputs["From Min"].default_value = 0.20
        roughness_map.inputs["From Max"].default_value = 0.82
        roughness_map.inputs["To Min"].default_value = roughness_min
        roughness_map.inputs["To Max"].default_value = roughness_max
        links.new(noise.outputs["Fac"], roughness_map.inputs["Value"])
        for link in list(roughness_socket.links):
            links.remove(link)
        links.new(roughness_map.outputs["Result"], roughness_socket)
    material["surface_detail_pass"] = "v35_noise_voronoi_manufacturing_breakup"
    return material


def _add_v35_deep_realism_layer(bpy, scene, bounds, materials):
    """Add the manufacturing and maintenance evidence reserved for v35.

    This layer is intentionally tied to existing equipment coordinates. It
    increases the physical specificity of the same plant rather than adding
    decorative objects that would only make the overview busier.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    points = {item["waypoint_id"]: item for item in scene.get("waypoints", [])}

    # Reduce the showroom response in the photographic layer. The stored
    # scene remains an interactive PBR asset; these changes only make the
    # synthetic inspection frames read more like a maintained facility.
    for light in bpy.context.scene.objects:
        if light.type != "LIGHT":
            continue
        if light.name.startswith("HighBayLight_"):
            light.data.energy = min(float(light.data.energy), 285.0)
        elif light.name.startswith("V27_HighBayLight_"):
            light.data.energy = min(float(light.data.energy), 118.0)
        elif light.name.startswith("FactoryAreaLight_"):
            light.data.energy = min(float(light.data.energy), 620.0)

    # Steam header / valve station: flange sealing, witness welds, bolt
    # washers and small-bore fittings create the nested edge hierarchy a macro
    # camera needs to see.
    pipe = points.get("WP_01_PIPE")
    if pipe:
        x, y = _equipment_position(pipe)
        z = 2.55
        for side in (-1, 1):
            flange_x = x + side * 1.46
            _torus(bpy, f"V35_PipeFlangeGasket_{side}", (flange_x, y, z),
                   0.242, 0.018, materials["v35_gasket"],
                   rotation=(0.0, math.pi / 2, 0.0))
            for bolt in range(8):
                angle = math.tau * bolt / 8
                _add_fastener_washer_and_nut(
                    bpy, f"V35_PipeFlangeFastener_{side}_{bolt}",
                    (flange_x + side * 0.082,
                     y + math.sin(angle) * 0.255,
                     z + math.cos(angle) * 0.255), 0.040, materials,
                    rotation=(0.0, math.pi / 2, 0.0),
                )
        for index, weld_x in enumerate((x - 1.10, x - 0.38, x + 0.38, x + 1.10), start=1):
            _torus(bpy, f"V35_SteamWeldBead_{index}", (weld_x, y, z),
                   0.205, 0.012, materials["v35_weld"],
                   rotation=(0.0, math.pi / 2, 0.0))
            _torus(bpy, f"V35_SteamHeatBand_{index}", (weld_x, y, z),
                   0.221, 0.006, materials["heat_affected"],
                   rotation=(0.0, math.pi / 2, 0.0))
        _pipe_between(bpy, "V35_PressureTakeoff", (x, y - 0.22, z + 0.08),
                      (x, y - 0.22, 3.22), 0.050, materials["instrument_tube"])
        for fitting_z in (3.20, 3.38):
            _cylinder(bpy, f"V35_PressureFitting_{fitting_z}",
                      (x, y - 0.22, fitting_z), 0.075, 0.11,
                      materials["fastener"], vertices=24, bevel=0.006)

        gauge_face_y = y - 0.45
        _torus(bpy, "V35_GaugeGlassSeal", (x, gauge_face_y, 3.85),
               0.348, 0.018, materials["v35_gasket"],
               rotation=(math.pi / 2, 0.0, 0.0))
        for screw in range(6):
            angle = math.tau * screw / 6
            _cylinder(
                bpy, f"V35_GaugeBezelScrew_{screw}",
                (x + math.sin(angle) * 0.327, gauge_face_y - 0.045,
                 3.85 + math.cos(angle) * 0.327), 0.013, 0.022,
                materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                vertices=12, bevel=0.002,
            )
        _cylinder(bpy, "V35_GaugeAntiGlareGlass", (x, gauge_face_y - 0.062, 3.85),
                  0.322, 0.006, materials["v35_glass"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=64, bevel=0.002)
        _box(bpy, "V35_GaugeCalibrationSticker", (x + 0.25, gauge_face_y - 0.075, 3.58),
             (0.095, 0.006, 0.034), materials["label_white"], bevel=0.002)
        _text(bpy, "V35_GaugeCalibrationText", "CAL 26",
              (x + 0.25, gauge_face_y - 0.087, 3.57), materials["ink"], size=0.022)

    # Pump group: cast housing seam, base grout, bearing details and an oil
    # film that is irregular instead of a single clean ellipse.
    pump = points.get("WP_04_PUMP")
    if pump:
        x, y = _equipment_position(pump)
        _torus(bpy, "V35_PumpVoluteSplitLine", (x + 0.40, y - 0.58, 1.04),
               0.405, 0.014, materials["v35_weld"],
               rotation=(math.pi / 2, 0.0, 0.0))
        for bolt in range(10):
            angle = math.tau * bolt / 10
            _add_fastener_washer_and_nut(
                bpy, f"V35_PumpCoverFastener_{bolt}",
                (x + 0.40 + math.sin(angle) * 0.385, y - 0.625,
                 1.04 + math.cos(angle) * 0.385), 0.030, materials,
                rotation=(math.pi / 2, 0.0, 0.0),
            )
        _cylinder(bpy, "V35_PumpBearingHousing", (x - 0.12, y, 1.04),
                  0.15, 0.34, materials["motor"],
                  rotation=(0.0, math.pi / 2, 0.0), vertices=48, bevel=0.012)
        _torus(bpy, "V35_PumpBearingSeal", (x - 0.12, y - 0.18, 1.04),
               0.125, 0.012, materials["v35_gasket"],
               rotation=(math.pi / 2, 0.0, 0.0))
        for index, (dx, dy, sx, sy) in enumerate((
            (0.80, -1.02, 0.46, 0.13), (1.04, -0.94, 0.24, 0.08),
            (0.72, -1.12, 0.18, 0.06),
        ), start=1):
            _add_irregular_flat_patch(
                bpy, f"V35_PumpOilFilm_{index}", (x + dx, y + dy, 0.025),
                (sx, sy), materials["v35_oil"],
            )
        for index, crack_x in enumerate((x - 1.05, x - 0.35, x + 0.42, x + 1.05), start=1):
            _pipe_path(
                bpy, f"V35_PumpBaseGroutCrack_{index}",
                ((crack_x, y - 0.78, 0.045),
                 (crack_x + 0.12, y - 0.84, 0.046),
                 (crack_x + 0.23, y - 0.80, 0.046)),
                0.006, materials["v35_concrete_chip"],
            )
        _cylinder(bpy, "V35_PumpGreaseNipple", (x - 0.48, y - 0.39, 1.43),
                  0.027, 0.10, materials["brass"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.004)
        _box(bpy, "V35_PumpConditionLabel", (x + 0.32, y - 0.64, 1.80),
             (0.19, 0.010, 0.043), materials["label_white"], bevel=0.002)
        _text(bpy, "V35_PumpConditionText", "VIB / PT",
              (x + 0.32, y - 0.655, 1.788), materials["ink"], size=0.026)

    # MCC: add sheet-metal folds, gasket compression witnesses, gland locknuts
    # and a few terminal labels. These are small, but they create real depth in
    # the interior macro view without hiding the existing electrical hierarchy.
    cabinet = points.get("WP_03_CABINET")
    if cabinet:
        x, y = _equipment_position(cabinet)
        for side in (-1, 1):
            _box(bpy, f"V35_MCC_SheetFold_{side}", (x + side * 1.06, y - 0.53, 1.48),
                 (0.022, 0.032, 0.94), materials["v35_coating"], bevel=0.005)
            for z in (0.50, 1.24, 2.02, 2.48):
                _cylinder(bpy, f"V35_MCC_CaptiveScrew_{side}_{z}",
                          (x + side * 1.06, y - 0.58, z), 0.014, 0.018,
                          materials["fastener"], rotation=(math.pi / 2, 0.0, 0.0),
                          vertices=12, bevel=0.002)
        for index, z in enumerate((0.72, 1.10, 1.48, 1.86, 2.24), start=1):
            _box(bpy, f"V35_MCC_TerminalMarker_{index}",
                 (x + 0.45, y - 0.395, z), (0.040, 0.006, 0.018),
                 materials["label_white"], bevel=0.001)
            _text(bpy, f"V35_MCC_TerminalText_{index}", f"{index:02d}",
                  (x + 0.45, y - 0.404, z - 0.006), materials["ink"], size=0.016)
        for gland in range(6):
            gx = x - 0.45 + gland * 0.18
            _torus(bpy, f"V35_MCC_GlandLocknut_{gland}", (gx, y + 0.64, 0.32),
                   0.047, 0.008, materials["fastener"],
                   rotation=(math.pi / 2, 0.0, 0.0))
        _box(bpy, "V35_MCC_DoorEdgeChip", (x + 1.34, y - 0.48, 1.18),
             (0.11, 0.006, 0.018), materials["v35_concrete_chip"], bevel=0.002)
        _box(bpy, "V35_MCC_DoorServiceLabel", (x + 1.42, y - 0.49, 1.86),
             (0.17, 0.010, 0.042), materials["warning_plate"], bevel=0.003)
        _text(bpy, "V35_MCC_DoorServiceText", "ISOLATE",
              (x + 1.42, y - 0.503, 1.848), materials["warning_ink"], size=0.024)

    # Vessel and exchanger: circumferential welds, drain witness marks and
    # tube-sheet gasket compression keep the background assets from reading as
    # single smooth primitives when the route camera passes them.
    vessel = points.get("WP_02_VESSEL")
    if vessel:
        x, y = _equipment_position(vessel)
        for index, z in enumerate((1.36, 2.15, 2.96), start=1):
            _torus(bpy, f"V35_VesselWeldBand_{index}", (x, y, z),
                   0.805, 0.012, materials["v35_weld"])
        _add_flat_stain(bpy, "V35_VesselDrainRust", (x + 0.36, y - 0.08, 0.04),
                        (0.22, 0.11), materials["v35_oxide"])
        _box(bpy, "V35_VesselInspectionStamp", (x - 0.52, y - 0.89, 2.70),
             (0.16, 0.010, 0.038), materials["label_white"], bevel=0.002)
        _text(bpy, "V35_VesselInspectionText", "UT / 26",
              (x - 0.52, y - 0.904, 2.69), materials["ink"], size=0.024)

    exchanger = points.get("WP_05_EXCHANGER")
    if exchanger:
        x, y = _equipment_position(exchanger)
        for index, ring_x in enumerate((x - 1.02, x - 0.48, x + 0.06, x + 0.60, x + 1.14), start=1):
            _torus(bpy, f"V35_ExchangerShellWeld_{index}", (ring_x, y, 1.62),
                   0.565, 0.010, materials["v35_weld"],
                   rotation=(0.0, math.pi / 2, 0.0))
        for end in (-1, 1):
            x_face = x + end * 1.56
            _torus(bpy, f"V35_ExchangerGasket_{end}", (x_face, y, 1.62),
                   0.405, 0.015, materials["v35_gasket"],
                   rotation=(0.0, math.pi / 2, 0.0))
            for bolt in range(10):
                angle = math.tau * bolt / 10
                _add_fastener_washer_and_nut(
                    bpy, f"V35_ExchangerWasher_{end}_{bolt}",
                    (x_face + end * 0.058,
                     y + math.sin(angle) * 0.40,
                     1.62 + math.cos(angle) * 0.40), 0.027, materials,
                    rotation=(0.0, math.pi / 2, 0.0),
                )

    # Plant-wide substrate cues: localized dampness at drains, chipped paint
    # around service height and fastener clusters on the roof framing.
    for index, (x, y, sx, sy) in enumerate((
        (center_x - 3.7, min_y + 1.05, 0.82, 0.14),
        (center_x + 3.2, min_y + 3.25, 0.64, 0.12),
        (max_x - 2.2, center_y - 1.05, 0.52, 0.18),
    ), start=1):
        _add_irregular_flat_patch(bpy, f"V35_FloorMoisture_{index}", (x, y, 0.018),
                                  (sx, sy), materials["v35_oil"])
    for index, x in enumerate(range(math.ceil(min_x) + 2, math.floor(max_x), 4), start=1):
        for z in (0.92, 1.38):
            _box(bpy, f"V35_PortalImpactWear_{index}_{z}", (x + 0.128, min_y + 0.34, z),
                 (0.010, 0.030, 0.035), materials["v35_concrete_chip"], bevel=0.002)
        _add_fastener_washer_and_nut(
            bpy, f"V35_RoofJointFastener_{index}", (x, center_y, 6.56), 0.034,
            materials, rotation=(math.pi / 2, 0.0, 0.0),
        )

    # Small local sources model the way a real inspection route is lit: the
    # asset is brighter than the aisle, but the scene still keeps shadow depth.
    for name, location, target, energy, color in (
        ("Valve", (2.55, 0.20, 3.80), (4.00, 3.15, 2.75), 105, (1.0, 0.62, 0.36)),
        ("Pump", (9.85, 2.95, 2.55), (11.85, 5.15, 1.15), 86, (1.0, 0.70, 0.48)),
        ("MCC", (6.72, -3.35, 2.15), (8.00, -0.22, 1.48), 58, (0.48, 0.68, 1.0)),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = f"V35_MicroTaskLight_{name}"
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = 0.46
        light.data.color = color
        _look_at(light, location, target)


def _add_insulation_seams(bpy, name: str, start, end, radius: float, material, *, count=5):
    """Place narrow seam rings along a straight insulated pipe run."""
    from mathutils import Vector

    start_vector, end_vector = Vector(start), Vector(end)
    direction = end_vector - start_vector
    if direction.length < 1e-5:
        return
    direction.normalize()
    ring_rotation = direction.to_track_quat("Z", "Y").to_euler()
    for index in range(1, count + 1):
        point = start_vector.lerp(end_vector, index / (count + 1))
        _torus(bpy, f"{name}_Seam_{index}", point, radius * 1.035, radius * 0.055,
               material, rotation=ring_rotation)


def _add_guardrail(bpy, name: str, x_positions, y, z, materials):
    """Add a low maintenance rail for a service edge or equipment platform."""
    if len(x_positions) < 2:
        return
    for index, x in enumerate(x_positions):
        _pipe_between(bpy, f"{name}_Post_{index}", (x, y, z - 0.55), (x, y, z),
                      0.035, materials["fence"])
        _cylinder(bpy, f"{name}_Foot_{index}", (x, y, z - 0.58), 0.08, 0.04,
                  materials["steel"], vertices=24, bevel=0.006)
    for rail_z in (z - 0.12, z - 0.40):
        _pipe_between(bpy, f"{name}_Rail_{rail_z}", (x_positions[0], y, rail_z),
                      (x_positions[-1], y, rail_z), 0.028, materials["fence"])


def _add_flat_stain(bpy, name: str, location, scale, material):
    stain = _sphere(bpy, name, (location[0], location[1], location[2] + 0.012),
                    (scale[0], scale[1], 0.012), material, segments=32)
    return stain


def _pipe_path(bpy, name: str, points, radius: float, material, *, parent=None):
    """Create a segmented process route with explicit elbows and supports."""
    if len(points) < 2:
        return None
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1.0)
    route = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(route)
    _assign(route, material)
    if parent is not None:
        route.parent = parent
    for index, point in enumerate(points[1:-1], start=1):
        _sphere(bpy, f"{name}_Joint_{index}", point,
                (radius * 1.35, radius * 1.35, radius * 1.35), material,
                segments=20, parent=parent)
    return route


def _add_pipe_support(bpy, name: str, x: float, y: float, z: float, width: float,
                      materials, *, height: float = 1.2):
    """Add a compact steel pipe-rack frame under a multi-level header."""
    for side in (-1, 1):
        _box(bpy, f"{name}_Post_{side}", (x + side * width * 0.38, y, z - height / 2),
             (0.055, 0.055, height / 2), materials["steel_dark"], bevel=0.012)
        _box(bpy, f"{name}_Foot_{side}", (x + side * width * 0.38, y, z - height - 0.04),
             (0.14, 0.12, 0.035), materials["steel"], bevel=0.008)
    _box(bpy, f"{name}_Beam", (x, y, z - height + 0.07),
         (width / 2, 0.065, 0.065), materials["steel_dark"], bevel=0.012)
    _box(bpy, f"{name}_Brace", (x, y, z - height * 0.52),
         (width * 0.42, 0.025, 0.025), materials["steel"], bevel=0.006)


def _add_pipe_clamp(bpy, name: str, center, radius: float, materials, *, axis="x"):
    """Add a split clamp and a visible support shoe around a process line."""
    rotation = {
        "x": (0.0, math.pi / 2, 0.0),
        "y": (math.pi / 2, 0.0, 0.0),
        "z": (0.0, 0.0, 0.0),
    }[axis]
    _torus(bpy, f"{name}_Clamp", center, radius * 1.16, radius * 0.075,
           materials["steel_dark"], rotation=rotation)
    x, y, z = center
    if axis == "x":
        _box(bpy, f"{name}_Shoe", (x, y, z - radius * 1.22),
             (radius * 0.58, radius * 0.58, radius * 0.10),
             materials["steel"], bevel=0.012)
    elif axis == "y":
        _box(bpy, f"{name}_Shoe", (x, y, z - radius * 1.22),
             (radius * 0.58, radius * 0.58, radius * 0.10),
             materials["steel"], bevel=0.012)
    else:
        _box(bpy, f"{name}_Shoe", (x + radius * 1.22, y, z),
             (radius * 0.10, radius * 0.58, radius * 0.58),
             materials["steel"], bevel=0.012)


def _add_cable_tray_run(bpy, name: str, start, end, width: float, side_height: float,
                        materials, *, rung_spacing: float = 0.55):
    """Build an axis-aligned ladder tray with rails, rungs and steel hangers."""
    x1, y1, z1 = start
    x2, y2, z2 = end
    if abs(z2 - z1) > 1e-4:
        raise ValueError("cable tray runs must stay at one elevation")
    z = z1
    if abs(y2 - y1) < 1e-4:
        low, high = sorted((x1, x2))
        length = high - low
        center_x = (low + high) / 2
        _box(bpy, f"{name}_Bottom", (center_x, y1, z),
             (length / 2, width / 2, 0.025), materials["cable"], bevel=0.012)
        for side in (-1, 1):
            _box(bpy, f"{name}_Rail_{side}", (center_x, y1 + side * width / 2, z + side_height / 2),
                 (length / 2, 0.026, side_height / 2), materials["steel"], bevel=0.008)
        rung_count = max(2, int(length / rung_spacing) + 1)
        for index in range(rung_count):
            x = low + min(length, index * length / max(1, rung_count - 1))
            _box(bpy, f"{name}_Rung_{index:02d}", (x, y1, z + 0.045),
                 (0.022, width * 0.45, 0.018), materials["steel"], bevel=0.004)
        for index, x in enumerate((low + 1.0, center_x, high - 1.0), start=1):
            if low + 0.35 < x < high - 0.35:
                _pipe_between(bpy, f"{name}_Hanger_{index}", (x, y1, z - 0.03),
                              (x, y1, z - 0.58), 0.028, materials["steel_dark"])
                _box(bpy, f"{name}_HangerFoot_{index}", (x, y1, z - 0.61),
                     (0.14, 0.12, 0.035), materials["steel"], bevel=0.006)
    elif abs(x2 - x1) < 1e-4:
        low, high = sorted((y1, y2))
        length = high - low
        center_y = (low + high) / 2
        _box(bpy, f"{name}_Bottom", (x1, center_y, z),
             (width / 2, length / 2, 0.025), materials["cable"], bevel=0.012)
        for side in (-1, 1):
            _box(bpy, f"{name}_Rail_{side}", (x1 + side * width / 2, center_y, z + side_height / 2),
                 (0.026, length / 2, side_height / 2), materials["steel"], bevel=0.008)
        rung_count = max(2, int(length / rung_spacing) + 1)
        for index in range(rung_count):
            y = low + min(length, index * length / max(1, rung_count - 1))
            _box(bpy, f"{name}_Rung_{index:02d}", (x1, y, z + 0.045),
                 (width * 0.45, 0.022, 0.018), materials["steel"], bevel=0.004)
        for index, y in enumerate((low + 1.0, center_y, high - 1.0), start=1):
            if low + 0.35 < y < high - 0.35:
                _pipe_between(bpy, f"{name}_Hanger_{index}", (x1, y, z - 0.03),
                              (x1, y, z - 0.58), 0.028, materials["steel_dark"])
                _box(bpy, f"{name}_HangerFoot_{index}", (x1, y, z - 0.61),
                     (0.12, 0.14, 0.035), materials["steel"], bevel=0.006)


def _add_base_plate_and_anchors(bpy, name: str, location, materials, *, width=0.34, depth=0.34):
    """Add a structural column base plate with four visible anchor nuts."""
    x, y, z = location
    _box(bpy, f"{name}_BasePlate", (x, y, z), (width, depth, 0.035),
         materials["steel"], bevel=0.008)
    for dx in (-width * 0.62, width * 0.62):
        for dy in (-depth * 0.62, depth * 0.62):
            _cylinder(bpy, f"{name}_Anchor_{dx:.2f}_{dy:.2f}",
                      (x + dx, y + dy, z + 0.055), 0.028, 0.055,
                      materials["brass"], vertices=6, bevel=0.004)


def _add_instrument_junction_box(bpy, name: str, location, materials, *, label="JB-01"):
    """Build a small field junction box with glands, indicator lamps and conduit."""
    x, y, z = location
    _box(bpy, f"{name}_Body", (x, y, z), (0.34, 0.18, 0.42),
         materials["instrument"], bevel=0.035)
    _box(bpy, f"{name}_Door", (x, y - 0.19, z), (0.27, 0.018, 0.34),
         materials["instrument_door"], bevel=0.012)
    _box(bpy, f"{name}_Window", (x, y - 0.212, z + 0.14), (0.13, 0.008, 0.07),
         materials["display"], bevel=0.006)
    _text(bpy, f"{name}_WindowText", "I/O", (x, y - 0.224, z + 0.135),
          materials["display_text"], size=0.045)
    for index, lamp in enumerate(("pilot_green", "warning", "pilot_red")):
        _cylinder(bpy, f"{name}_Lamp_{index}", (x - 0.17 + index * 0.17, y - 0.22, z - 0.10),
                  0.032, 0.028, materials[lamp], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=20, bevel=0.004)
    for index in range(4):
        _cylinder(bpy, f"{name}_CableGland_{index}",
                  (x - 0.24 + index * 0.16, y + 0.20, z - 0.28),
                  0.040, 0.075, materials["rubber_seal"],
                  rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.006)
    _box(bpy, f"{name}_TagPlate", (x, y - 0.23, z + 0.31),
         (0.21, 0.012, 0.05), materials["label_plate"], bevel=0.004)
    _text(bpy, f"{name}_Tag", label, (x, y - 0.247, z + 0.298),
          materials["ink"], size=0.036)
    _pipe_between(bpy, f"{name}_ConduitDrop", (x, y + 0.20, z - 0.34),
                  (x, y + 0.20, 0.55), 0.022, materials["conduit"])
    return (x, y, z)


def _add_instrument_tubing(bpy, name: str, start, end, materials):
    """Route twin-bore stainless impulse tubing with small mounting clips."""
    x1, y1, z1 = start
    x2, y2, z2 = end
    bend_y = (y1 + y2) / 2
    for offset in (-0.045, 0.045):
        points = ((x1 + offset, y1, z1), (x1 + offset, bend_y, z1),
                  (x2 + offset, bend_y, z2), (x2 + offset, y2, z2))
        _pipe_path(bpy, f"{name}_{offset:+.3f}", points, 0.012, materials["instrument_tube"])
        for index, point in enumerate(points[1:-1], start=1):
            _add_pipe_clamp(bpy, f"{name}_Clip_{offset:+.3f}_{index}", point,
                            0.012, materials, axis="z")


def _add_plant_instrumentation(bpy, scene, materials):
    """Add field instrumentation so the process lines read as an operating plant."""
    points = {item["waypoint_id"]: item for item in scene["waypoints"]}
    pipe = points.get("WP_01_PIPE")
    if pipe:
        x, y = _equipment_position(pipe)
        box = _add_instrument_junction_box(bpy, "JB_PT302", (x + 1.10, y - 0.58, 2.62),
                                            materials, label="JB-PT302")
        _add_instrument_tubing(bpy, "PT302_ImpulseTube", (x + 0.02, y - 0.23, 3.26),
                               (box[0], box[1], box[2] + 0.18), materials)
        _box(bpy, "PT302_LocalDisplay", (x + 1.55, y - 0.48, 2.40),
             (0.24, 0.07, 0.18), materials["display"], bevel=0.015)
        _text(bpy, "PT302_LocalDisplayText", "1.08 MPa", (x + 1.55, y - 0.56, 2.40),
              materials["display_text"], size=0.055)

    vessel = points.get("WP_02_VESSEL")
    if vessel:
        x, y = _equipment_position(vessel)
        box = _add_instrument_junction_box(bpy, "JB_LT101", (x + 1.08, y - 0.74, 2.10),
                                            materials, label="JB-LT101")
        _add_instrument_tubing(bpy, "LT101_ImpulseTube", (x + 0.20, y - 0.95, 2.10),
                               (box[0], box[1], box[2] + 0.15), materials)

    pump = points.get("WP_04_PUMP")
    if pump:
        x, y = _equipment_position(pump)
        box = _add_instrument_junction_box(bpy, "JB_VIB021", (x + 1.72, y - 0.58, 1.72),
                                            materials, label="JB-VIB021")
        _pipe_between(bpy, "VIB021_Conduit", (x + 0.78, y - 0.50, 1.10),
                      (box[0], box[1], box[2] - 0.28), 0.025, materials["conduit"])
        for index in range(3):
            _box(bpy, f"P021_LubePoint_{index}", (x + 0.1 + index * 0.28, y - 0.56, 0.92),
                 (0.06, 0.025, 0.05), materials["brass"], bevel=0.006)

    exchanger = points.get("WP_05_EXCHANGER")
    if exchanger:
        x, y = _equipment_position(exchanger)
        _add_instrument_junction_box(bpy, "JB_TT201", (x + 1.70, y - 0.72, 1.72),
                                      materials, label="JB-TT201")
        _pipe_between(bpy, "TT201_Thermowell", (x + 0.35, y - 0.58, 2.20),
                      (x + 0.35, y - 0.76, 2.20), 0.025, materials["brass"])


def _add_access_platforms_and_stairs(bpy, scene, materials):
    """Add grating, stairs and guardrails around serviceable equipment."""
    points = {item["waypoint_id"]: item for item in scene["waypoints"]}
    vessel = points.get("WP_02_VESSEL")
    if vessel:
        x, y = _equipment_position(vessel)
        platform_z = 2.72
        _box(bpy, "V101_ServicePlatform", (x, y - 0.92, platform_z),
             (0.94, 0.60, 0.055), materials["grating"], bevel=0.012)
        for index in range(8):
            _box(bpy, f"V101_GratingBar_{index}",
                 (x - 0.84 + index * 0.24, y - 0.92, platform_z + 0.07),
                 (0.018, 0.54, 0.012), materials["steel"], bevel=0.003)
        _add_guardrail(bpy, "V101_PlatformRail",
                       (x - 0.92, x - 0.45, x + 0.02, x + 0.50, x + 0.92),
                       y - 1.45, platform_z + 0.58, materials)
        for step in range(5):
            _box(bpy, f"V101_Stair_{step}", (x + 1.05, y - 1.62 + step * 0.18,
                                               0.62 + step * 0.42),
                 (0.36, 0.12, 0.045), materials["grating"], bevel=0.008)
        _pipe_between(bpy, "V101_StairRail", (x + 1.42, y - 1.72, 0.60),
                      (x + 1.42, y - 0.98, 2.65), 0.026, materials["fence"])

    pump = points.get("WP_04_PUMP")
    if pump:
        x, y = _equipment_position(pump)
        _box(bpy, "P021_OperatorPad", (x + 0.30, y - 0.86, 0.72),
             (0.62, 0.30, 0.045), materials["grating"], bevel=0.012)
        for index in range(5):
            _box(bpy, f"P021_PadBar_{index}", (x - 0.18 + index * 0.24, y - 0.86, 0.78),
                 (0.018, 0.26, 0.012), materials["steel"], bevel=0.003)
        _add_guardrail(bpy, "P021_OperatorRail", (x - 0.30, x + 0.90),
                       y - 1.12, 1.28, materials)


def _add_pipe_rack_detail(bpy, bounds, materials):
    """Add pipe clamps, branch manifolds and identification bands to the rack."""
    min_x, max_x, min_y, max_y = bounds
    rack_y = max_y - 2.25
    rack_lines = (
        (rack_y - 0.62, 4.25, 0.075, "pipe"),
        (rack_y - 0.10, 4.58, 0.09, "process_pipe"),
        (rack_y + 0.44, 4.92, 0.08, "steam_pipe"),
    )
    for line_index, (y, z, radius, material_key) in enumerate(rack_lines, start=1):
        for clamp_index, x in enumerate((1.2, 4.4, 7.6, 10.8, 14.0, 17.0), start=1):
            if min_x + 0.8 < x < max_x - 0.8:
                _add_pipe_clamp(bpy, f"Rack{line_index}_Clamp_{clamp_index}",
                                (x, y, z), radius, materials, axis="x")
        for band_index, x in enumerate((3.0, 8.8, 14.6), start=1):
            _box(bpy, f"Rack{line_index}_IDBand_{band_index}", (x, y - radius * 1.05, z),
                 (0.22, 0.018, radius * 1.08), materials["label_plate"], bevel=0.004)
            _text(bpy, f"Rack{line_index}_IDText_{band_index}",
                  "STM" if line_index == 3 else "PROC",
                  (x, y - radius * 1.075, z), materials["ink"], size=0.038)
    # A branch header with real elbows, isolation valves and instrument take-offs.
    branch_x = 9.35
    branch_y = rack_y - 0.10
    _pipe_path(bpy, "Rack_Branch_To_P021",
               ((branch_x, branch_y, 4.58), (branch_x, 6.25, 4.58),
                (11.9, 6.25, 3.25), (11.9, 5.7, 3.25)),
               0.065, materials["process_pipe"])
    _add_valve(bpy, "Rack_Branch_Isolation", (11.9, 6.25, 3.25), 0.13,
               materials, axis="y", wheel_material="warning", body_material="steel")
    _add_pipe_clamp(bpy, "Rack_Branch_Clamp", (11.9, 5.70, 3.25), 0.065,
                    materials, axis="y")
    for x in (5.3, 12.2, 16.4):
        _pipe_path(bpy, f"Rack_Downcomer_{x}",
                   ((x, rack_y + 0.44, 4.92), (x, rack_y + 0.44, 3.98),
                    (x + 0.18, rack_y - 0.24, 3.98),
                    (x + 0.18, rack_y - 0.24, 2.90)),
                   0.045, materials["steam_pipe"])
        _add_valve(bpy, f"Rack_DowncomerValve_{x}",
                   (x + 0.18, rack_y - 0.24, 3.55), 0.095, materials,
                   axis="z", wheel_material="brass", body_material="steel")


def _add_utility_layers(bpy, scene, bounds, materials):
    """Add the secondary infrastructure that connects assets into one plant."""
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Structural base plates and anchor hardware are visible at the foot of
    # every portal frame, which prevents the shell from reading as a set.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 4), start=1):
        for side, y in enumerate((min_y + 0.35, max_y - 0.35), start=1):
            _add_base_plate_and_anchors(bpy, f"PortalBase_{index}_{side}",
                                        (x, y, 0.035), materials, width=0.22, depth=0.22)

    # A real cable ladder has a bottom tray, side rails and repeated rungs.
    # The two runs form a visible distribution path above the inspection aisle.
    _add_cable_tray_run(bpy, "CableTray_North_Main",
                        (min_x + 1.0, max_y - 1.10, 4.82),
                        (max_x - 1.0, max_y - 1.10, 4.82),
                        0.62, 0.16, materials)
    _add_cable_tray_run(bpy, "CableTray_East_Riser",
                        (max_x - 1.15, min_y + 1.1, 4.28),
                        (max_x - 1.15, max_y - 1.10, 4.28),
                        0.58, 0.14, materials)
    _add_cable_tray_run(bpy, "CableTray_West_Service",
                        (min_x + 1.15, min_y + 1.15, 3.10),
                        (min_x + 1.15, max_y - 1.35, 3.10),
                        0.48, 0.12, materials)

    # Drop legs make the field wiring legible from a low operator camera.
    for index, x in enumerate((1.7, 5.0, 8.3, 11.6, 15.0), start=1):
        if min_x + 1.0 < x < max_x - 1.0:
            _pipe_between(bpy, f"CableTrayDrop_{index}", (x, max_y - 1.10, 4.74),
                          (x, max_y - 1.10, 3.32), 0.035, materials["conduit"])
            _box(bpy, f"CableTrayDropClamp_{index}", (x, max_y - 1.10, 3.28),
                 (0.16, 0.18, 0.035), materials["steel"], bevel=0.008)

    # Instrument air header and small-bore branches sit behind the process
    # line; the color and supports distinguish them from process piping.
    air_y, air_z = max_y - 2.72, 3.72
    _pipe_path(bpy, "InstrumentAir_Header",
               ((min_x + 1.2, air_y, air_z), (max_x - 1.2, air_y, air_z)),
               0.045, materials["instrument_air"])
    for index, x in enumerate((1.5, 5.4, 9.4, 13.4, 16.8), start=1):
        if min_x + 1.0 < x < max_x - 1.0:
            _add_pipe_clamp(bpy, f"InstrumentAir_Clamp_{index}", (x, air_y, air_z),
                            0.045, materials, axis="x")
            _pipe_path(bpy, f"InstrumentAir_Branch_{index}",
                       ((x, air_y, air_z), (x, air_y - 0.38, air_z),
                        (x, air_y - 0.38, 2.92)), 0.025, materials["instrument_air"])
            _add_valve(bpy, f"InstrumentAir_Isolation_{index}",
                       (x, air_y - 0.38, 3.18), 0.065, materials,
                       axis="z", wheel_material="brass", body_material="steel")
            _box(bpy, f"InstrumentAir_Tag_{index}", (x, air_y - 0.44, 2.72),
                 (0.16, 0.018, 0.045), materials["label_plate"], bevel=0.004)
            _text(bpy, f"InstrumentAir_TagText_{index}", "IA",
                  (x, air_y - 0.463, 2.708), materials["ink"], size=0.032)

    # Add short cable bundles from the main tray to the field junction boxes.
    for index, waypoint in enumerate(scene.get("waypoints", [])[:6], start=1):
        x, y = _equipment_position(waypoint)
        drop_x = min(max(x, min_x + 1.2), max_x - 1.2)
        _pipe_path(bpy, f"FieldCableBundle_{index}",
                   ((drop_x, max_y - 1.10, 4.72), (drop_x, y - 0.72, 4.72),
                    (drop_x, y - 0.72, 1.18)), 0.022, materials["cable"])
        _box(bpy, f"FieldCableLabel_{index}", (drop_x, y - 0.76, 1.05),
             (0.18, 0.022, 0.045), materials["label_plate"], bevel=0.004)
        _text(bpy, f"FieldCableLabelText_{index}", waypoint["waypoint_id"].replace("WP_", ""),
              (drop_x, y - 0.788, 1.038), materials["ink"], size=0.028)

    # Cast-iron trench sections and cleanouts give the floor a service system.
    trench_x = center_x + 4.5
    for index, y in enumerate((-5.6, -3.0, -0.4, 2.2, 4.8), start=1):
        if min_y + 0.5 < y < max_y - 0.5:
            _box(bpy, f"ServiceTrench_{index}", (trench_x, y, 0.018),
                 (0.52, 0.17, 0.012), materials["drain"], bevel=0.008)
            for slot in range(6):
                _box(bpy, f"ServiceTrenchSlot_{index}_{slot}",
                     (trench_x - 0.39 + slot * 0.16, y, 0.038),
                     (0.022, 0.13, 0.008), materials["steel"], bevel=0.003)
            _cylinder(bpy, f"ServiceCleanout_{index}", (trench_x + 0.74, y, 0.045),
                      0.12, 0.045, materials["steel_dark"], vertices=32, bevel=0.006)
            _torus(bpy, f"ServiceCleanoutRing_{index}", (trench_x + 0.74, y, 0.072),
                   0.10, 0.018, materials["brass"])

    # Guard posts at the restricted electrical zone and around the main aisle.
    for index, x in enumerate((7.0, 9.0), start=1):
        _cylinder(bpy, f"ElectricalBollard_{index}", (x, -0.95, 0.48),
                  0.09, 0.86, materials["safety_yellow"], vertices=32, bevel=0.018)
        _torus(bpy, f"ElectricalBollardBand_{index}", (x, -0.95, 0.60),
               0.091, 0.012, materials["warning_black"])

    _box(bpy, "ZoneSign_ELEC_B", (center_x - 0.1, min_y + 0.18, 2.70),
         (0.65, 0.035, 0.24), materials["label_plate"], bevel=0.008)
    _text(bpy, "ZoneSign_ELEC_B_Text", "ELEC-B  RESTRICTED",
          (center_x - 0.1, min_y + 0.135, 2.68), materials["ink"], size=0.070)


def _add_factory_service_details(bpy, bounds, materials):
    """Add small but consequential details: conduits, signs, doors and floor hardware."""
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    # Parallel conduits and junction points along the east wall.
    for index, offset in enumerate((-0.26, -0.08, 0.10, 0.28), start=1):
        _pipe_path(bpy, f"East_Conduit_{index}",
                   ((max_x - 0.46, min_y + 1.0 + offset, 0.55),
                    (max_x - 0.46, max_y - 1.6 + offset, 0.55),
                    (max_x - 0.46, max_y - 1.6 + offset, 4.65)),
                   0.022, materials["conduit"])
    for index, y in enumerate((-4.7, -1.4, 2.0, 5.4), start=1):
        if min_y < y < max_y:
            _add_instrument_junction_box(bpy, f"JB_EAST_{index}",
                                         (max_x - 0.72, y, 1.05), materials,
                                         label=f"JB-{index:02d}")

    # Operator access door and visible push-button station.
    door_x, door_y = min_x + 0.25, min_y + 1.3
    _box(bpy, "PersonnelDoorFrame", (door_x, door_y, 1.55),
         (0.10, 0.92, 1.55), materials["steel_dark"], bevel=0.018)
    _box(bpy, "PersonnelDoorLeaf", (door_x + 0.03, door_y, 1.55),
         (0.045, 0.78, 1.42), materials["door"], bevel=0.012)
    _box(bpy, "PersonnelDoorWindow", (door_x + 0.085, door_y - 0.22, 2.10),
         (0.012, 0.34, 0.25), materials["window"], bevel=0.006)
    _cylinder(bpy, "PersonnelDoorHandle", (door_x + 0.12, door_y - 0.58, 1.48),
              0.035, 0.14, materials["brass"], rotation=(math.pi / 2, 0, 0),
              vertices=20, bevel=0.004)
    _box(bpy, "EmergencyStopStation", (door_x + 0.40, door_y - 1.05, 1.10),
         (0.18, 0.06, 0.34), materials["fire_red"], bevel=0.025)
    _cylinder(bpy, "EmergencyStopButton", (door_x + 0.40, door_y - 1.12, 1.20),
              0.095, 0.05, materials["warning"], rotation=(math.pi / 2, 0, 0),
              vertices=32, bevel=0.010)
    _text(bpy, "EmergencyStopText", "E-STOP", (door_x + 0.40, door_y - 1.18, 0.92),
          materials["label_plate"], size=0.075)

    # Hazard-striped exclusion boxes around the active pump and electrical cabinet.
    for index, x in enumerate((11.5, 8.0), start=1):
        y = 5.7 if index == 1 else 0.2
        for stripe in range(8):
            angle = -1 if stripe % 2 else 1
            _box(bpy, f"HazardStripe_{index}_{stripe}",
                 (x - 1.45 + stripe * 0.40, y - 1.20, 0.028),
                 (0.14, 0.035, 0.008),
                 materials["warning_black"] if angle < 0 else materials["warning"], bevel=0.002)

    # Cable tray drop supports and a small local control station beside the MCC.
    _box(bpy, "MCC_LocalControlPost", (8.95, -0.35, 1.10),
         (0.20, 0.16, 1.05), materials["steel_dark"], bevel=0.018)
    _box(bpy, "MCC_LocalControlFace", (8.95, -0.54, 1.35),
         (0.35, 0.025, 0.34), materials["instrument"], bevel=0.018)
    for index, lamp in enumerate(("pilot_green", "warning", "pilot_red")):
        _cylinder(bpy, f"MCC_ControlLamp_{index}", (8.80 + index * 0.15, -0.58, 1.50),
                  0.032, 0.03, materials[lamp], rotation=(math.pi / 2, 0, 0),
                  vertices=20, bevel=0.004)
    _box(bpy, "MCC_ControlScreen", (8.95, -0.58, 1.25),
         (0.18, 0.014, 0.10), materials["display"], bevel=0.008)
    _text(bpy, "MCC_ControlScreenText", "RUN", (8.95, -0.60, 1.24),
          materials["display_text"], size=0.052)


def _add_weathering_and_field_evidence(bpy, bounds, materials):
    """Break the procedural perfection with restrained, plant-like wear.

    These are small deterministic geometry marks rather than a decorative
    grunge overlay: drips sit below wall joints, oil gathers under rotating
    equipment, and paint chips cluster around service height and impact edges.
    """
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    # Rain and condensate streaks below the north cladding panels.
    for index, x in enumerate((min_x + 1.6, min_x + 4.9, center_x - 3.1,
                               center_x + 2.6, max_x - 2.1), start=1):
        height = 0.38 + (index % 3) * 0.17
        _box(bpy, f"North_CondensateStreak_{index}",
             (x, max_y - 0.174, 0.86 + height / 2),
             (0.018 + (index % 2) * 0.012, 0.008, height / 2),
             materials["rust_streak"], bevel=0.006)
        _add_flat_stain(bpy, f"North_CondensateFoot_{index}",
                        (x, max_y - 0.20, 0.018),
                        (0.12 + index * 0.012, 0.05), materials["grime"])

    # Fine scuffs and oil halos on service routes and below pumps.
    floor_marks = (
        (center_x - 5.4, min_y + 1.45, 0.60, 0.16),
        (center_x - 1.1, min_y + 3.25, 0.38, 0.11),
        (center_x + 2.8, center_y - 2.25, 0.74, 0.19),
        (11.9, 5.15, 0.48, 0.14),
        (-0.90, -4.70, 0.52, 0.22),
    )
    for index, (x, y, sx, sy) in enumerate(floor_marks, start=1):
        _add_flat_stain(bpy, f"FloorOilHalo_{index}", (x, y, 0.018),
                        (sx, sy), materials["floor_oil"])
        _add_flat_stain(bpy, f"FloorOilCore_{index}", (x + 0.04, y - 0.02, 0.022),
                        (sx * 0.42, sy * 0.48), materials["oil_wet"])

    # Paint loss on portal columns at the height where carts and tooling hit.
    for index, x in enumerate(range(math.ceil(min_x) + 1, math.floor(max_x), 4), start=1):
        for side, y in enumerate((min_y + 0.36, max_y - 0.36), start=1):
            _box(bpy, f"PortalPaintChip_{index}_{side}",
                 (x + 0.126, y - 0.03, 1.05 + (index % 2) * 0.18),
                 (0.006, 0.07, 0.06), materials["paint_chip"], bevel=0.002)

    # Small inspection labels and lockout tags at the electrical boundary.
    for index, (x, y, label) in enumerate(((7.3, -1.05, "LOTO"),
                                           (8.7, -1.05, "PPE"),
                                           (10.1, -1.05, "ARC")), start=1):
        _box(bpy, f"ElectricalTag_{index}", (x, y, 0.86),
             (0.32, 0.018, 0.11), materials["warning_plate"], bevel=0.008)
        _text(bpy, f"ElectricalTagText_{index}", label, (x, y - 0.024, 0.845),
              materials["warning_ink"], size=0.055)

    # Weld rosettes and inspection witness marks around the main process skid.
    for index, x in enumerate((2.8, 3.5, 4.2, 4.9, 5.6), start=1):
        _torus(bpy, f"SteamHeaderWeld_{index}", (x, 3.20, 2.55), 0.205, 0.010,
               materials["weld_bead"], rotation=(0.0, math.pi / 2, 0.0))
    for index, z in enumerate((1.05, 1.42, 1.79, 2.16), start=1):
        _box(bpy, f"VesselPaintWitness_{index}", (-2.30, 4.25, z),
             (0.012, 0.10, 0.016), materials["paint_chip"], bevel=0.002)


def _add_v18_asset_microdetails(bpy, scene, materials):
    """Add close-range maintenance evidence to the four primary inspection assets."""
    points = {item["waypoint_id"]: item for item in scene.get("waypoints", [])}

    pipe = points.get("WP_01_PIPE")
    if pipe:
        x, y = _equipment_position(pipe)
        z = 2.55
        valve_x = x - 0.72
        wheel_center = (valve_x, y, z + 0.365)
        # Handwheel spokes and packing rings make the isolation valve mechanically
        # readable in the macro camera instead of leaving a single torus silhouette.
        for spoke in range(4):
            angle = math.tau * spoke / 4
            _pipe_between(
                bpy, f"V18_XV302_WheelSpoke_{spoke}", wheel_center,
                (valve_x + math.sin(angle) * 0.115, y,
                 wheel_center[2] + math.cos(angle) * 0.115),
                0.018, materials["warning"],
            )
        for ring_index, ring_z in enumerate((z + 0.19, z + 0.27), start=1):
            _torus(bpy, f"V18_XV302_Packing_{ring_index}",
                   (valve_x, y, ring_z), 0.105, 0.014,
                   materials["rubber_seal"])
        # Repeated washer/nut stacks around the visible pipe flanges.
        for side in (-1, 1):
            flange_x = x + side * 1.46
            for bolt in range(8):
                angle = math.tau * bolt / 8
                _add_fastener_washer_and_nut(
                    bpy, f"V18_XV302_Flange_{side}_{bolt}",
                    (flange_x + side * 0.082,
                     y + math.sin(angle) * 0.25,
                     z + math.cos(angle) * 0.25),
                    0.040, materials, rotation=(0.0, math.pi / 2, 0.0),
                )
        _add_plate_rivets(
            bpy, "V18_XV302_Nameplate", (valve_x, y - 0.205, z + 0.38),
            (0.16, 0.012, 0.055), materials,
        )
        # Twin instrument cables leave a controlled service loop before entering JB-PT302.
        _add_cable_loop(
            bpy, "V18_PT302_ServiceLoop", (x + 1.10, y - 0.84, 2.48),
            0.16, materials["cable"], rotation=(math.pi / 2, 0.0, 0.0),
        )
        for index, offset in enumerate((-0.16, 0.16), start=1):
            _box(bpy, f"V18_PT302_CableClip_{index}",
                 (x + 1.10 + offset, y - 0.84, 2.48),
                 (0.028, 0.035, 0.055), materials["fastener"], bevel=0.004)

    cabinet = points.get("WP_03_CABINET")
    if cabinet:
        x, y = _equipment_position(cabinet)
        # Quarter-turn latches, hinge barrels and an earth-bond braid give the
        # open MCC door a serviceable enclosure detail at close range.
        for index, z in enumerate((0.72, 1.45, 2.18), start=1):
            _cylinder(bpy, f"V18_MCC_Latch_{index}", (x + 0.42, y - 0.72, z),
                      0.045, 0.035, materials["fastener"],
                      rotation=(math.pi / 2, 0.0, 0.0), vertices=20, bevel=0.004)
            _box(bpy, f"V18_MCC_LatchSlot_{index}", (x + 0.42, y - 0.745, z),
                 (0.020, 0.006, 0.055), materials["ink"], bevel=0.001)
        for index, z in enumerate((0.54, 1.42, 2.28), start=1):
            _torus(bpy, f"V18_MCC_Hinge_{index}", (x - 0.86, y - 0.60, z),
                   0.075, 0.018, materials["fastener"], rotation=(0.0, math.pi / 2, 0.0))
        _add_plate_rivets(
            bpy, "V18_MCC_RatingPlate", (x, y - 0.615, 2.50),
            (0.40, 0.018, 0.13), materials,
        )
        _add_cable_loop(
            bpy, "V18_MCC_DoorLoop", (x + 0.72, y - 0.70, 1.05),
            0.18, materials["copper"], rotation=(math.pi / 2, 0.0, 0.0),
        )
        # Small identification strips make the busbar field less uniform.
        for index, label in enumerate(("L1", "L2", "L3", "PE"), start=1):
            plate_x = x - 0.54 + (index - 1) * 0.25
            _box(bpy, f"V18_MCC_BusLabel_{index}", (plate_x, y - 0.67, 2.32),
                 (0.075, 0.012, 0.032), materials["label_plate"], bevel=0.003)
            _text(bpy, f"V18_MCC_BusLabelText_{index}", label,
                  (plate_x, y - 0.688, 2.315), materials["ink"], size=0.026)

    pump = points.get("WP_04_PUMP")
    if pump:
        x, y = _equipment_position(pump)
        motor_x = x - 0.74
        # End bell, cooling fan and grease points expose the mechanical service side.
        _cylinder(bpy, "V18_P021_MotorEndBell", (motor_x - 0.58, y, 1.04),
                  0.31, 0.08, materials["motor"], rotation=(0.0, math.pi / 2, 0.0),
                  vertices=48, bevel=0.012)
        _torus(bpy, "V18_P021_MotorFanGuard", (motor_x - 0.63, y, 1.04),
               0.26, 0.018, materials["steel_dark"], rotation=(0.0, math.pi / 2, 0.0))
        for blade in range(6):
            angle = math.tau * blade / 6
            _pipe_between(
                bpy, f"V18_P021_MotorFanBlade_{blade}",
                (motor_x - 0.64, y, 1.04),
                (motor_x - 0.64, y + math.sin(angle) * 0.20,
                 1.04 + math.cos(angle) * 0.20),
                0.012, materials["steel"],
            )
        for index, offset in enumerate((-0.28, 0.0, 0.28), start=1):
            _sphere(bpy, f"V18_P021_GreasePoint_{index}",
                    (motor_x + offset, y - 0.40, 1.42),
                    (0.035, 0.035, 0.035), materials["brass"], segments=16)
        for bx in (-1.28, 1.28):
            for by in (-0.63, 0.63):
                _add_fastener_washer_and_nut(
                    bpy, f"V18_P021_BaseFastener_{bx}_{by}",
                    (x + bx, y + by, 0.54), 0.040, materials,
                )
        _add_plate_rivets(
            bpy, "V18_P021_ServicePlate", (x + 0.35, y - 0.60, 1.78),
            (0.23, 0.014, 0.060), materials,
        )
        _add_cable_loop(
            bpy, "V18_P021_VibrationLoop", (x + 1.72, y - 0.74, 1.76),
            0.14, materials["conduit"], rotation=(math.pi / 2, 0.0, 0.0),
        )

    # A few local fasteners and cable loops on the field junction boxes stop
    # every instrument enclosure from sharing exactly the same silhouette.
    for index, waypoint_id in enumerate(("WP_01_PIPE", "WP_02_VESSEL", "WP_04_PUMP", "WP_05_EXCHANGER"), start=1):
        waypoint = points.get(waypoint_id)
        if not waypoint:
            continue
        x, y = _equipment_position(waypoint)
        loop_y = y - 0.82 - index * 0.02
        _add_cable_loop(
            bpy, f"V18_FieldBoxLoop_{index}", (x + 1.10, loop_y, 2.18),
            0.11, materials["cable"], rotation=(math.pi / 2, 0.0, 0.0),
        )


def _add_vertical_vessel(bpy, materials):
    """Build a background pressure vessel with service access and nozzles."""
    x, y = -1.45, 5.10
    body_z = 2.15
    _cylinder(bpy, "V101_Shell", (x, y, body_z), 0.82, 2.35,
              materials["tank_coat"], vertices=64, bevel=0.035)
    _sphere(bpy, "V101_TopHead", (x, y, 3.39), (0.82, 0.82, 0.34),
            materials["tank_coat"], segments=48)
    _sphere(bpy, "V101_BottomHead", (x, y, 0.91), (0.82, 0.82, 0.30),
            materials["tank_coat"], segments=48)
    for ring_z in (1.04, 2.15, 3.26):
        _torus(bpy, f"V101_Ring_{ring_z}", (x, y, ring_z), 0.79, 0.035,
               materials["steel_dark"])
    for index, (dx, dy) in enumerate(((-0.54, -0.50), (0.54, -0.50),
                                      (-0.54, 0.50), (0.54, 0.50)), start=1):
        _box(bpy, f"V101_Leg_{index}", (x + dx, y + dy, 0.48),
             (0.075, 0.075, 0.44), materials["steel_dark"], bevel=0.018)
        _box(bpy, f"V101_Foot_{index}", (x + dx, y + dy, 0.055),
             (0.18, 0.16, 0.04), materials["steel"], bevel=0.008)
    for dx in (-0.40, 0.40):
        _pipe_between(bpy, f"V101_CrossBrace_{dx}", (x + dx, y - 0.52, 0.58),
                      (x - dx, y - 0.52, 1.25), 0.026, materials["steel_dark"])

    _cylinder(bpy, "V101_TopNozzle", (x, y, 3.78), 0.16, 0.58,
              materials["process_pipe"], bevel=0.018)
    _add_flange(bpy, "V101_TopFlange", (x, y, 3.98), 0.24, 0.10,
                materials, rotation=(0.0, 0.0, 0.0), bolt_count=8)
    _pipe_between(bpy, "V101_SouthNozzle", (x, y - 0.74, 2.20),
                  (x, y - 1.18, 2.20), 0.14, materials["process_pipe"])
    _add_flange(bpy, "V101_SouthFlange", (x, y - 1.18, 2.20), 0.22, 0.09,
                materials, rotation=(math.pi / 2, 0.0, 0.0), bolt_count=8)
    _cylinder(bpy, "V101_Manway", (x, y - 0.84, 2.05), 0.31, 0.10,
              materials["steel_dark"], rotation=(math.pi / 2, 0.0, 0.0), vertices=48)
    _torus(bpy, "V101_ManwayRim", (x, y - 0.91, 2.05), 0.27, 0.035,
           materials["brass"], rotation=(math.pi / 2, 0.0, 0.0))
    _add_valve(bpy, "V101_SouthValve", (x, y - 1.28, 2.20), 0.14, materials,
               axis="y", wheel_material="warning", body_material="steel")
    _add_gauge(bpy, "V101_PressureGauge", (x, y - 1.36, 2.86), 0.28,
               materials, value=6.2)
    _pipe_between(bpy, "V101_Drain", (x + 0.36, y - 0.05, 0.92),
                  (x + 0.36, y - 0.05, 0.26), 0.055, materials["process_pipe"])
    _add_valve(bpy, "V101_DrainValve", (x + 0.36, y - 0.05, 0.25), 0.09,
               materials, axis="z", wheel_material="brass", body_material="steel")

    for side in (-1, 1):
        _pipe_between(bpy, f"V101_LadderRail_{side}",
                      (x + side * 0.42, y - 0.88, 0.55),
                      (x + side * 0.42, y - 0.88, 3.08), 0.026, materials["fence"])
    for rung in range(6):
        _pipe_between(bpy, f"V101_LadderRung_{rung}", (x - 0.42, y - 0.88, 0.76 + rung * 0.38),
                      (x + 0.42, y - 0.88, 0.76 + rung * 0.38), 0.022, materials["fence"])
    _box(bpy, "V101_Nameplate", (x, y - 0.88, 3.12),
         (0.34, 0.025, 0.075), materials["label_plate"], bevel=0.006)
    _text(bpy, "V101_Label", "V-101  SEPARATOR", (x, y - 0.918, 3.105),
          materials["ink"], size=0.050)


def _add_heat_exchanger(bpy, materials):
    """Add a shell-and-tube exchanger with saddles, tube sheet and piping."""
    x, y, z = 14.60, 5.20, 1.62
    _cylinder(bpy, "E201_Shell", (x, y, z), 0.56, 3.10, materials["stainless"],
              rotation=(0.0, math.pi / 2, 0.0), vertices=64, bevel=0.035)
    for end in (-1, 1):
        _sphere(bpy, f"E201_Head_{end}", (x + end * 1.55, y, z),
                (0.34, 0.56, 0.56), materials["stainless"], segments=40)
        _cylinder(bpy, f"E201_TubeSheet_{end}", (x + end * 1.48, y, z), 0.48, 0.10,
                  materials["steel_dark"], rotation=(0.0, math.pi / 2, 0.0), vertices=64)
        for bolt in range(10):
            angle = math.tau * bolt / 10
            _cylinder(bpy, f"E201_Bolt_{end}_{bolt}",
                      (x + end * 1.56, y + math.sin(angle) * 0.38,
                       z + math.cos(angle) * 0.38), 0.028, 0.035,
                      materials["brass"], rotation=(0.0, math.pi / 2, 0.0),
                      vertices=6, bevel=0.004)
    for ring in (x - 1.04, x - 0.50, x + 0.05, x + 0.60, x + 1.10):
        _torus(bpy, f"E201_ShellRing_{ring}", (ring, y, z), 0.56, 0.028,
               materials["steel_dark"], rotation=(0.0, math.pi / 2, 0.0))
    for saddle_x in (x - 0.95, x + 0.95):
        _box(bpy, f"E201_Saddle_{saddle_x}", (saddle_x, y, 0.76),
             (0.23, 0.65, 0.10), materials["steel_dark"], bevel=0.018)
        _box(bpy, f"E201_SaddleLeg_{saddle_x}", (saddle_x, y, 0.42),
             (0.10, 0.10, 0.27), materials["steel"], bevel=0.015)
        _box(bpy, f"E201_SaddleFoot_{saddle_x}", (saddle_x, y, 0.11),
             (0.27, 0.44, 0.05), materials["steel"], bevel=0.01)
    _pipe_between(bpy, "E201_TopNozzle", (x - 0.30, y, z + 0.48),
                  (x - 0.30, y, z + 1.05), 0.13, materials["process_pipe"])
    _add_valve(bpy, "E201_TopValve", (x - 0.30, y, z + 1.17), 0.14, materials,
               axis="z", wheel_material="warning", body_material="steel")
    _pipe_between(bpy, "E201_SouthNozzle", (x + 0.72, y - 0.48, z),
                  (x + 0.72, y - 0.98, z), 0.13, materials["process_pipe"])
    _add_flange(bpy, "E201_SouthFlange", (x + 0.72, y - 1.00, z), 0.20, 0.09,
                materials, rotation=(math.pi / 2, 0.0, 0.0), bolt_count=8)
    _add_gauge(bpy, "E201_TempGauge", (x + 0.35, y - 0.62, z + 0.58), 0.22,
               materials, value=4.8)
    _box(bpy, "E201_Nameplate", (x, y - 0.61, 2.30),
         (0.42, 0.024, 0.075), materials["label_plate"], bevel=0.006)
    _text(bpy, "E201_Label", "E-201  HEAT EXCHANGER", (x, y - 0.642, 2.285),
          materials["ink"], size=0.046)


def _add_background_filter_skid(bpy, materials):
    """Add a smaller filter/pump skid to give the east bay a working context."""
    x, y = 15.05, -2.65
    _box(bpy, "F301_Skid", (x, y, 0.20), (1.35, 0.70, 0.20),
         materials["concrete"], bevel=0.05)
    _box(bpy, "F301_SkidPlate", (x, y, 0.43), (1.18, 0.58, 0.035),
         materials["steel"], bevel=0.01)
    _cylinder(bpy, "F301_FilterBody", (x - 0.45, y, 1.18), 0.42, 1.40,
              materials["tank_coat"], vertices=48, bevel=0.025)
    _sphere(bpy, "F301_FilterTop", (x - 0.45, y, 1.90), (0.42, 0.42, 0.18),
            materials["tank_coat"], segments=32)
    _torus(bpy, "F301_FilterRing", (x - 0.45, y, 1.16), 0.41, 0.028,
           materials["steel_dark"])
    _pipe_between(bpy, "F301_Inlet", (x - 0.45, y + 0.42, 1.45),
                  (x - 0.45, y + 0.95, 1.45), 0.11, materials["process_pipe"])
    _pipe_between(bpy, "F301_OutletRise", (x + 0.30, y, 0.72),
                  (x + 0.30, y, 2.35), 0.11, materials["process_pipe"])
    _add_valve(bpy, "F301_OutletValve", (x + 0.30, y, 2.47), 0.12, materials,
               axis="z", wheel_material="warning", body_material="steel")
    _cylinder(bpy, "F301_Motor", (x + 0.72, y, 0.96), 0.34, 0.78,
              materials["motor"], rotation=(0.0, math.pi / 2, 0.0), vertices=48)
    for index in range(7):
        _torus(bpy, f"F301_MotorFin_{index}", (x + 0.42 + index * 0.10, y, 0.96),
               0.30, 0.016, materials["steel"], rotation=(0.0, math.pi / 2, 0.0))
    _box(bpy, "F301_Nameplate", (x - 0.45, y - 0.45, 2.10),
         (0.34, 0.022, 0.07), materials["label_plate"], bevel=0.005)
    _text(bpy, "F301_Label", "F-301  FILTER", (x - 0.45, y - 0.478, 2.085),
          materials["ink"], size=0.052)
    _add_flat_stain(bpy, "F301_Dust", (x + 0.85, y - 0.65, 0.02),
                    (0.45, 0.22), materials["dust"])


def _add_inspection_node(bpy, waypoint, materials):
    """Mark a configured background asset without duplicating its geometry."""
    x, y = _equipment_position(waypoint)
    device = waypoint["device_id"]
    _box(bpy, f"{device}_InspectionPlate", (x, y - 0.42, 0.07),
         (0.30, 0.18, 0.035), materials["label_plate"], bevel=0.012)
    _text(bpy, f"{device}_InspectionLabel", waypoint.get("waypoint_id", device),
          (x, y - 0.61, 0.082), materials["ink"], size=0.045,
          rotation=(0, 0, 0))


def _add_pipe_rack_and_crane(bpy, bounds, materials):
    """Fill the upper bay with layered utilities, supports, and a service crane."""
    min_x, max_x, min_y, max_y = bounds
    rack_y = max_y - 2.25
    for index, (y, z, radius, material_key) in enumerate((
        (rack_y - 0.62, 4.25, 0.075, "pipe"),
        (rack_y - 0.10, 4.58, 0.09, "process_pipe"),
        (rack_y + 0.44, 4.92, 0.08, "steam_pipe"),
    ), start=1):
        start_x, end_x = min_x + 0.8, max_x - 0.8
        _pipe_path(bpy, f"PipeRack_Header_{index}",
                   ((start_x, y, z), (end_x - 1.3, y, z),
                    (end_x - 1.0, y - 0.30, z), (end_x, y - 0.30, z)),
                   radius, materials[material_key])
        _add_insulation_seams(bpy, f"PipeRack_Header_{index}",
                              (start_x, y, z), (end_x - 1.3, y, z), radius,
                              materials["insulation_seam"], count=5)
        for x in range(math.ceil(start_x) + 1, math.floor(end_x), 4):
            _add_pipe_support(bpy, f"PipeRack_Support_{index}_{x}", x, y, z,
                              0.72, materials, height=max(0.55, z - 3.62))
    for x in (0.0, 4.5, 9.0, 13.5, 17.0):
        _pipe_path(bpy, f"PipeRack_Drop_{x}",
                   ((x, rack_y - 0.10, 4.58), (x, rack_y - 0.10, 3.88),
                    (x + 0.32, rack_y - 0.42, 3.88)),
                   0.045, materials["process_pipe"])
        _box(bpy, f"PipeRack_DropBracket_{x}", (x, rack_y - 0.18, 3.88),
             (0.20, 0.12, 0.035), materials["steel_dark"], bevel=0.008)
    _box(bpy, "Crane_Runway_South", ((min_x + max_x) / 2, 5.25, 5.25),
         ((max_x - min_x) / 2 - 0.9, 0.09, 0.09), materials["steel_dark"], bevel=0.018)
    _box(bpy, "Crane_Runway_North", ((min_x + max_x) / 2, 6.25, 5.25),
         ((max_x - min_x) / 2 - 0.9, 0.09, 0.09), materials["steel_dark"], bevel=0.018)
    trolley_x, trolley_y = 6.0, 5.75
    _box(bpy, "Crane_Trolley", (trolley_x, trolley_y, 5.43), (0.56, 0.72, 0.12),
         materials["crane_yellow"], bevel=0.025)
    for side in (-1, 1):
        _cylinder(bpy, f"Crane_Wheel_{side}", (trolley_x, trolley_y + side * 0.62, 5.27),
                  0.14, 0.16, materials["steel_dark"], rotation=(math.pi / 2, 0.0, 0.0),
                  vertices=32, bevel=0.012)
    _cylinder(bpy, "Crane_Hoist", (trolley_x, trolley_y, 5.03), 0.18, 0.38,
              materials["crane_yellow"], bevel=0.018)
    _pipe_between(bpy, "Crane_Chain", (trolley_x, trolley_y, 4.84),
                  (trolley_x, trolley_y, 3.02), 0.018, materials["chain"])
    _torus(bpy, "Crane_Hook", (trolley_x, trolley_y, 2.92), 0.14, 0.028,
           materials["crane_yellow"], rotation=(math.pi / 2, 0.0, 0.0))


def _add_wall_and_safety_facilities(bpy, bounds, materials):
    """Add the small but legible fixtures that make the bay operational."""
    min_x, max_x, min_y, max_y = bounds
    # Axial exhaust fan on the north wall, with a visible guard and blades.
    fan_x, fan_y, fan_z = 2.8, max_y - 0.22, 3.35
    _cylinder(bpy, "HVAC_AxialFanCase", (fan_x, fan_y, fan_z), 0.72, 0.18,
              materials["steel_dark"], rotation=(math.pi / 2, 0.0, 0.0), vertices=48)
    _torus(bpy, "HVAC_AxialFanGuard", (fan_x, fan_y - 0.13, fan_z), 0.62, 0.035,
           materials["steel"], rotation=(math.pi / 2, 0.0, 0.0))
    for blade in range(5):
        angle = math.tau * blade / 5
        blade_obj = _box(bpy, f"HVAC_FanBlade_{blade}",
                         (fan_x + math.sin(angle) * 0.27, fan_y - 0.19,
                          fan_z + math.cos(angle) * 0.27),
                         (0.055, 0.025, 0.24), materials["fan_blade"], bevel=0.018)
        blade_obj.rotation_euler[1] = angle
    _cylinder(bpy, "HVAC_FanHub", (fan_x, fan_y - 0.22, fan_z), 0.10, 0.08,
              materials["brass"], rotation=(math.pi / 2, 0.0, 0.0), vertices=24)

    # East-wall louver bank and fire cabinet.
    louver_x = max_x - 0.20
    for index, y in enumerate((-5.0, -4.2, -3.4), start=1):
        _box(bpy, f"East_Louver_{index}", (louver_x, y, 3.05),
             (0.08, 0.26, 0.62), materials["louver"], bevel=0.015)
        for slot in range(7):
            _box(bpy, f"East_LouverSlot_{index}_{slot}", (louver_x - 0.09, y - 0.20 + slot * 0.067, 3.05),
                 (0.025, 0.018, 0.47), materials["steel_dark"], bevel=0.004)
    cabinet_y = -1.65
    _box(bpy, "FireCabinet_Body", (louver_x - 0.12, cabinet_y, 1.50),
         (0.15, 0.62, 0.88), materials["fire_red"], bevel=0.035)
    _box(bpy, "FireCabinet_Door", (louver_x - 0.30, cabinet_y, 1.50),
         (0.025, 0.53, 0.76), materials["fire_glass"], bevel=0.008)
    _torus(bpy, "FireHoseReel", (louver_x - 0.36, cabinet_y, 1.52), 0.36, 0.035,
           materials["hose_red"], rotation=(0.0, math.pi / 2, 0.0))
    _pipe_between(bpy, "FireHoseTail", (louver_x - 0.38, cabinet_y - 0.30, 1.44),
                  (louver_x - 0.65, cabinet_y - 0.30, 1.10), 0.022, materials["hose_red"])
    _box(bpy, "FireCabinetSign", (louver_x - 0.34, cabinet_y, 2.30),
         (0.035, 0.22, 0.12), materials["fire_red"], bevel=0.005)
    _text(bpy, "FireCabinetText", "FIRE", (louver_x - 0.38, cabinet_y, 2.29),
          materials["label_plate"], size=0.085, rotation=(math.pi / 2, 0.0, math.pi / 2))

    # Emergency shower / eyewash station beside the service aisle.
    shower_x, shower_y = -0.10, max_y - 0.80
    _pipe_between(bpy, "EmergencyShower_Post", (shower_x, shower_y, 0.14),
                  (shower_x, shower_y, 2.55), 0.045, materials["safety_green"])
    _pipe_between(bpy, "EmergencyShower_Arm", (shower_x, shower_y, 2.55),
                  (shower_x + 0.65, shower_y, 2.55), 0.045, materials["safety_green"])
    _cylinder(bpy, "EmergencyShower_Head", (shower_x + 0.65, shower_y, 2.45),
              0.22, 0.10, materials["safety_green"], bevel=0.012)
    _box(bpy, "EmergencyEyewash_Bowl", (shower_x + 0.42, shower_y - 0.32, 1.18),
         (0.30, 0.18, 0.035), materials["safety_green"], bevel=0.02)
    _pipe_between(bpy, "EmergencyEyewash_Riser", (shower_x + 0.42, shower_y - 0.32, 1.20),
                  (shower_x + 0.42, shower_y - 0.32, 1.52), 0.028, materials["safety_green"])

    # Maintenance bay: workbench, tool cart, drums and a parts rack.
    base_x, base_y = -2.35, -4.55
    _box(bpy, "MaintenanceWorkbenchTop", (base_x, base_y, 1.08),
         (1.18, 0.48, 0.08), materials["steel_dark"], bevel=0.02)
    for side in (-1, 1):
        _box(bpy, f"MaintenanceWorkbenchLeg_{side}", (base_x + side * 0.92, base_y, 0.54),
             (0.08, 0.30, 0.47), materials["steel"], bevel=0.012)
    for drawer in range(3):
        _box(bpy, f"MaintenanceDrawer_{drawer}", (base_x - 0.48, base_y - 0.04, 0.42 + drawer * 0.20),
             (0.34, 0.34, 0.07), materials["cabinet"], bevel=0.012)
        _cylinder(bpy, f"MaintenanceDrawerHandle_{drawer}", (base_x - 0.48, base_y - 0.39, 0.42 + drawer * 0.20),
                  0.025, 0.12, materials["brass"], rotation=(math.pi / 2, 0.0, 0.0), vertices=16)
    for tool_x, tool_z in ((base_x - 0.35, 1.38), (base_x + 0.12, 1.28), (base_x + 0.52, 1.36)):
        _pipe_between(bpy, f"WorkbenchTool_{tool_x}", (tool_x, base_y - 0.05, 1.14),
                      (tool_x, base_y - 0.05, tool_z), 0.018, materials["brass"])
    _box(bpy, "PartsRackFrame", (base_x + 1.95, base_y + 0.06, 1.32),
         (0.10, 0.38, 1.20), materials["steel_dark"], bevel=0.015)
    for shelf in range(4):
        _box(bpy, f"PartsRackShelf_{shelf}", (base_x + 1.95, base_y + 0.06, 0.40 + shelf * 0.60),
             (0.68, 0.40, 0.045), materials["steel"], bevel=0.008)
        _box(bpy, f"PartsRackBin_{shelf}", (base_x + 1.95, base_y - 0.10, 0.54 + shelf * 0.60),
             (0.50, 0.18, 0.14), materials["parts_bin"], bevel=0.012)
    for drum_x, drum_y, drum_mat in ((base_x - 1.55, base_y - 0.12, "drum_blue"),
                                     (base_x - 1.55, base_y + 0.55, "drum_yellow")):
        _cylinder(bpy, f"Drum_{drum_x}_{drum_y}", (drum_x, drum_y, 0.52), 0.34, 0.86,
                  materials[drum_mat], vertices=48, bevel=0.025)
        for ring_z in (0.24, 0.80):
            _torus(bpy, f"DrumRing_{drum_x}_{drum_y}_{ring_z}", (drum_x, drum_y, ring_z),
                   0.34, 0.025, materials["steel_dark"])
    _box(bpy, "WoodenPallet", (base_x + 1.35, base_y - 0.60, 0.08),
         (0.78, 0.52, 0.08), materials["wood"], bevel=0.015)
    for plank in range(5):
        _box(bpy, f"PalletPlank_{plank}", (base_x + 0.72 + plank * 0.32, base_y - 0.60, 0.17),
             (0.12, 0.54, 0.035), materials["wood"], bevel=0.008)
    _torus(bpy, "MaintenanceHoseCoil", (base_x + 0.55, base_y - 0.52, 0.34),
           0.28, 0.035, materials["hose_red"], rotation=(math.pi / 2, 0.0, 0.0))


def _equipment_position(waypoint):
    return float(waypoint["x"]), float(waypoint["y"]) + 2.2


def _add_gauge(bpy, name, center, radius, materials, *, value=6.8, maximum=10.0):
    """Build a readable analog gauge facing toward the open south aisle (-Y)."""
    from mathutils import Vector

    x, y, z = center
    face_y = y - 0.20
    rotation = (math.pi / 2, 0.0, 0.0)
    _cylinder(bpy, f"{name}_Case", (x, y, z), radius * 1.12, 0.13,
              materials["steel"], rotation=rotation, vertices=64)
    _torus(bpy, f"{name}_Bezel", (x, face_y, z), radius * 0.99, radius * 0.09,
           materials["brass"], rotation=rotation)
    _cylinder(bpy, f"{name}_Dial", (x, face_y - 0.012, z), radius * 0.91, 0.025,
              materials["dial"], rotation=rotation, vertices=64, bevel=0.003)
    _cylinder(bpy, f"{name}_Glass", (x, face_y - 0.082, z), radius * 0.92, 0.014,
              materials["gauge_glass"], rotation=rotation, vertices=64, bevel=0.004)

    def point(angle, distance):
        return (x + math.sin(angle) * distance, face_y - 0.035,
                z + math.cos(angle) * distance)

    start, end = math.radians(-135), math.radians(135)
    for tick in range(51):
        angle = start + (end - start) * tick / 50
        major = tick % 5 == 0
        inner = radius * (0.75 if major else 0.81)
        outer = radius * 0.87
        _pipe_between(bpy, f"{name}_Tick_{tick:02d}", point(angle, inner),
                      point(angle, outer), radius * (0.012 if major else 0.007),
                      materials["ink"])

    for number in range(11):
        angle = start + (end - start) * number / 10
        label = _text(bpy, f"{name}_Scale_{number}", str(number),
                      point(angle, radius * 0.62), materials["ink"], size=radius * 0.19)
        label.location.y = face_y - 0.044

    warning_start = start + (end - start) * 0.78
    for part in range(8):
        angle_a = warning_start + (end - start) * 0.018 * part
        angle_b = angle_a + (end - start) * 0.012
        _pipe_between(bpy, f"{name}_Warning_{part}", point(angle_a, radius * 0.91),
                      point(angle_b, radius * 0.91), radius * 0.035,
                      materials["warning"])

    reading_angle = start + (end - start) * max(0.0, min(1.0, value / maximum))
    tip = point(reading_angle, radius * 0.67)
    _pipe_between(bpy, f"{name}_Needle", (x, face_y - 0.06, z), tip,
                  radius * 0.018, materials["needle"])
    _cylinder(bpy, f"{name}_Hub", (x, face_y - 0.065, z), radius * 0.055,
              radius * 0.025, materials["brass"], rotation=rotation, vertices=24,
              bevel=0.003)
    _text(bpy, f"{name}_Unit", "bar", (x, face_y - 0.048, z - radius * 0.37),
          materials["ink"], size=radius * 0.16)
    _cylinder(bpy, f"{name}_Stem", (x, y + 0.12, z - radius * 1.22), radius * 0.09,
              radius * 0.38, materials["steel"], vertices=24)
    for side in (-1, 1):
        _pipe_between(bpy, f"{name}_Mount_{side}",
                      (x + side * radius * 0.45, y + 0.12, z - radius * 1.42),
                      (x + side * radius * 0.45, y + 0.12, z - radius * 1.75),
                      radius * 0.045, materials["steel"])


def _pipe_between(bpy, name: str, start, end, radius: float, material, *, parent=None):
    from mathutils import Vector

    start_vector = Vector(start)
    end_vector = Vector(end)
    direction = end_vector - start_vector
    midpoint = (start_vector + end_vector) / 2
    obj = _cylinder(bpy, name, midpoint, radius, direction.length, material,
                    bevel=0.015, parent=parent)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(direction.normalized())
    return obj


def _text(bpy, name: str, body: str, location, material, *, size=0.22,
          rotation=(math.pi / 2, 0, 0), parent=None):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.align_x = "CENTER"
    curve.size = size
    curve.extrude = 0.006
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = rotation
    _assign(obj, material)
    if parent is not None:
        obj.parent = parent
    return obj


def _look_at(camera, location, target):
    from mathutils import Vector

    camera.location = location
    direction = Vector(target) - Vector(location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _camera(bpy, name: str, location, target, lens: float = 35, *, dof_fstop=None):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.sensor_width = 36
    if dof_fstop is not None:
        data.dof.use_dof = True
        data.dof.focus_distance = math.dist(location, target)
        data.dof.aperture_fstop = dof_fstop
    camera = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(camera)
    _look_at(camera, location, target)
    return camera


def _add_robot(bpy, root, materials):
    """Create a stylized quadruped sensor platform with an animated root."""
    _box(bpy, "Robot_Body", (0, 0, 0.48), (0.42, 0.27, 0.16),
         materials["robot"], bevel=0.08, parent=root)
    _box(bpy, "Robot_SensorHead", (0.38, 0, 0.60), (0.16, 0.22, 0.13),
         materials["robot_dark"], bevel=0.05, parent=root)
    _box(bpy, "Robot_TopBatteryLid", (0.02, 0, 0.675),
         (0.28, 0.19, 0.028), materials["robot_panel"], bevel=0.012, parent=root)
    for screw_index, (screw_x, screw_y) in enumerate(((-0.18, -0.13), (-0.18, 0.13),
                                                       (0.20, -0.13), (0.20, 0.13)), start=1):
        _cylinder(bpy, f"Robot_BatteryScrew_{screw_index}",
                  (screw_x, screw_y, 0.708), 0.012, 0.012, materials["fastener"],
                  vertices=6, bevel=0.002, parent=root)
    for vent_index, vent_x in enumerate((-0.18, -0.06, 0.06, 0.18), start=1):
        _box(bpy, f"Robot_BatteryVent_{vent_index}", (vent_x, -0.198, 0.62),
             (0.035, 0.006, 0.012), materials["robot_dark"], bevel=0.002, parent=root)
    _box(bpy, "Robot_StatusBar", (0.20, -0.24, 0.57),
         (0.10, 0.008, 0.018), materials["sensor"], bevel=0.003, parent=root)
    _cylinder(bpy, "Robot_RGB_Camera", (0.54, 0, 0.62), 0.065, 0.08,
              materials["sensor"], rotation=(0, math.pi / 2, 0), parent=root)
    _torus(bpy, "Robot_RGB_Camera_Bezel", (0.585, 0, 0.62), 0.074, 0.012,
           materials["steel_dark"], rotation=(0, math.pi / 2, 0), parent=root)
    _cylinder(bpy, "Robot_RGB_Camera_Lens", (0.635, 0, 0.62), 0.043, 0.012,
              materials["lens"], rotation=(0, math.pi / 2, 0), vertices=32,
              bevel=0.003, parent=root)
    _cylinder(bpy, "Robot_Lidar", (0.02, 0, 0.71), 0.08, 0.05,
              materials["sensor"], parent=root)
    _torus(bpy, "Robot_Lidar_Ring", (0.02, 0, 0.738), 0.072, 0.010,
           materials["steel_dark"], parent=root)
    _box(bpy, "Robot_Front_Bumper", (0.45, 0, 0.43), (0.045, 0.25, 0.06),
         materials["rubber_wear"], bevel=0.018, parent=root)
    _box(bpy, "Robot_Side_ServicePanel", (-0.10, -0.275, 0.50),
         (0.22, 0.012, 0.10), materials["robot_panel"], bevel=0.012, parent=root)
    for screw in (-0.20, 0.02):
        _cylinder(bpy, f"Robot_ServiceScrew_{screw}", (screw, -0.292, 0.50),
                  0.012, 0.010, materials["brass"],
                  rotation=(math.pi / 2, 0, 0), vertices=6, bevel=0.002, parent=root)
    for index, (x, y) in enumerate(((-0.28, -0.20), (-0.28, 0.20),
                                    (0.28, -0.20), (0.28, 0.20)), start=1):
        _sphere(bpy, f"Robot_Hip_{index}", (x, y, 0.43), (0.09, 0.09, 0.09),
                materials["steel"], parent=root, segments=20)
        _torus(bpy, f"Robot_HipSeal_{index}", (x, y, 0.43), 0.074, 0.012,
               materials["rubber_wear"], parent=root)
        upper = _pipe_between(bpy, f"Robot_Leg_{index}_Upper", (x, y, 0.43),
                              (x * 1.16, y, 0.22), 0.047, materials["robot_dark"],
                              parent=root)
        _sphere(bpy, f"Robot_Knee_{index}", (x * 1.16, y, 0.22),
                (0.065, 0.065, 0.065), materials["robot"], parent=root, segments=16)
        lower = _pipe_between(bpy, f"Robot_Leg_{index}_Lower",
                              (x * 1.16, y, 0.22), (x * 1.08, y, 0.07),
                              0.032, materials["steel"], parent=root)
        _cylinder(bpy, f"Robot_Actuator_{index}", (x * 1.14, y, 0.29),
                  0.045, 0.16, materials["robot_dark"], vertices=20, bevel=0.006,
                  parent=root)
        foot = _box(bpy, f"Robot_Foot_{index}", (x, y, 0.07), (0.12, 0.09, 0.045),
                    materials["rubber"], bevel=0.025, parent=root)
        _box(bpy, f"Robot_FootTread_{index}", (x, y - 0.092, 0.07),
             (0.08, 0.012, 0.018), materials["rubber_wear"], bevel=0.004, parent=root)
        foot.rotation_euler[2] = math.radians(8 if y > 0 else -8)
    _text(bpy, "Robot_Label", "SIM-QUADRUPED", (0, -0.285, 0.47),
          materials["label"], size=0.12, parent=root)


def _add_route(bpy, scene, materials):
    points = [(0.0, 0.0, 0.025)]
    points.extend((float(item["x"]), float(item["y"]), 0.025)
                  for item in scene.get("trajectory", []))
    if len(points) < 2:
        return
    curve = bpy.data.curves.new("RobotInspectionRoute", type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.010
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1.0)
    route = bpy.data.objects.new("RobotInspectionRoute", curve)
    bpy.context.collection.objects.link(route)
    _assign(route, materials["route"])

    for index, waypoint in enumerate(scene["waypoints"], start=1):
        x, y = float(waypoint["x"]), float(waypoint["y"])
        _torus(bpy, f"Waypoint_StopRing_{index}", (x, y, 0.025), 0.27, 0.012,
               materials["marker"])
        _box(bpy, f"Waypoint_Cross_X_{index}", (x, y, 0.012), (0.34, 0.008, 0.006),
             materials["marker"], bevel=0)
        _box(bpy, f"Waypoint_Cross_Y_{index}", (x, y, 0.012), (0.008, 0.34, 0.006),
             materials["marker"], bevel=0)
        yaw = math.radians(float(waypoint.get("yaw_deg", 0.0)))
        _text(bpy, f"WaypointHeading_{index}", "INSPECT",
              (x + math.cos(yaw) * 0.42, y + math.sin(yaw) * 0.42, 0.040),
              materials["marker_text"], size=0.075, rotation=(0, 0, 0))
        _text(bpy, f"WaypointLabel_{index}", f"WP {index:02d}",
              (x, y - 0.48, 0.030), materials["label"], size=0.10,
              rotation=(0, 0, 0))

    travel = 1.8
    for segment, (start, end) in enumerate(zip(points, points[1:]), start=1):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1e-4:
            continue
        while travel < length:
            px = start[0] + dx * travel / length
            py = start[1] + dy * travel / length
            verts = ((0.23, 0.0, 0.0), (-0.13, 0.14, 0.0),
                     (-0.045, 0.0, 0.0), (-0.13, -0.14, 0.0))
            mesh = bpy.data.meshes.new(f"RouteArrowMesh_{segment}_{travel:.1f}")
            mesh.from_pydata(verts, [], ((0, 1, 2), (0, 2, 3)))
            mesh.materials.append(materials["route_arrow"])
            arrow = bpy.data.objects.new(mesh.name, mesh)
            bpy.context.collection.objects.link(arrow)
            arrow.location = (px, py, 0.036)
            arrow.rotation_euler[2] = math.atan2(dy, dx)
            travel += 3.0
        travel -= length


def _set_navigation_overlay_render_visibility(bpy, *, render_overlays: bool) -> None:
    """Keep navigation graphics in the interactive scene, not in camera photos."""
    if render_overlays:
        return
    prefixes = ("RobotInspectionRoute", "Waypoint_", "RouteArrowMesh")
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(prefixes):
            obj.hide_render = True


def _add_factory_shell(bpy, bounds, materials):
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    width, depth = max_x - min_x, max_y - min_y
    _box(bpy, "FactoryFloor", (center_x, center_y, -0.12), (width / 2, depth / 2, 0.12),
         materials["floor"], bevel=0.02)
    for wall_name, location, scale in (
        ("North_ConcreteWainscot", (center_x, max_y, 1.55), (width / 2, 0.16, 1.55)),
        ("East_ConcreteWainscot", (max_x, center_y, 1.55), (0.16, depth / 2, 1.55)),
        ("West_CutawayWainscot", (min_x, center_y, 1.25), (0.16, depth / 2, 1.25)),
    ):
        _box(bpy, wall_name, location, scale, materials["concrete"], bevel=0.02)

    for x in range(math.ceil(min_x) + 1, math.floor(max_x), 2):
        _box(bpy, f"North_CladdingPanel_{x}", (x, max_y, 4.15),
             (0.94, 0.10, 2.30), materials["wall"], bevel=0.015)
        _box(bpy, f"North_Window_{x}", (x, max_y - 0.12, 2.85),
             (0.91, 0.035, 0.48), materials["window"], bevel=0.005)
        _box(bpy, f"North_WindowSill_{x}", (x, max_y - 0.20, 2.32),
             (0.98, 0.12, 0.045), materials["steel"], bevel=0.01)
    for y in range(math.ceil(min_y) + 1, math.floor(max_y), 2):
        _box(bpy, f"East_CladdingPanel_{y}", (max_x, y, 4.15),
             (0.10, 0.94, 2.30), materials["wall"], bevel=0.015)
        _box(bpy, f"East_Window_{y}", (max_x - 0.12, y, 2.85),
             (0.035, 0.91, 0.48), materials["window"], bevel=0.005)

    for x in range(math.ceil(min_x) + 1, math.floor(max_x), 4):
        for y in (min_y + 0.35, max_y - 0.35):
            _box(bpy, f"PortalColumn_{x}_{round(y, 1)}", (x, y, 3.25),
                 (0.12, 0.12, 3.25), materials["steel"], bevel=0.025)
        _box(bpy, f"RoofTrussTopChord_{x}", (x, center_y, 6.55),
             (0.10, depth / 2, 0.09), materials["steel"], bevel=0.02)
        _box(bpy, f"RoofTrussBottomChord_{x}", (x, center_y, 5.95),
             (0.065, depth / 2, 0.065), materials["steel"], bevel=0.015)
        for y in range(math.ceil(min_y) + 1, math.floor(max_y), 2):
            _pipe_between(bpy, f"RoofTrussWeb_{x}_{y}",
                          (x, y, 5.98), (x, min(max_y, y + 2), 6.52),
                          0.035, materials["steel"])
        _box(bpy, f"RoofPurlin_{x}", (x, center_y, 6.78),
             (0.045, depth / 2, 0.045), materials["steel"], bevel=0.01)

    _box(bpy, "North_RingBeam", (center_x, max_y - 0.28, 6.70),
         (width / 2, 0.10, 0.12), materials["steel"], bevel=0.02)
    _box(bpy, "East_RingBeam", (max_x - 0.28, center_y, 6.70),
         (0.10, depth / 2, 0.12), materials["steel"], bevel=0.02)

    for y in (-5.0, -1.0, 3.0, 6.0):
        if min_y < y < max_y:
            for x in (min_x + 0.45, max_x - 0.45):
                _box(bpy, f"AisleYellow_{x}_{y}", (center_x, y, 0.014),
                     (width / 2 - 0.6, 0.035, 0.012), materials["lane"], bevel=0.006)
    _box(bpy, "PedestrianLaneWest", (min_x + 0.72, center_y, 0.014),
         (0.035, depth / 2 - 0.55, 0.012), materials["lane_white"], bevel=0.005)
    _box(bpy, "PedestrianLaneEast", (max_x - 0.72, center_y, 0.014),
         (0.035, depth / 2 - 0.55, 0.012), materials["lane_white"], bevel=0.005)

    for x in range(math.ceil(min_x) + 2, math.floor(max_x), 4):
        _box(bpy, f"CableTrayMain_{x}", (x, max_y - 1.15, 5.35),
             (0.24, 0.20, 0.08), materials["cable"], bevel=0.025)
        for side in (-1, 1):
            _box(bpy, f"CableTrayLip_{x}_{side}", (x + side * 0.22, max_y - 1.15, 5.48),
                 (0.035, 0.20, 0.11), materials["steel"], bevel=0.008)
    for offset, material_key in ((-0.22, "pipe"), (0.0, "steam_pipe"), (0.22, "pipe")):
        _pipe_between(bpy, f"OverheadProcessLine_{offset}",
                      (min_x + 1.0, max_y - 2.1 + offset, 5.70),
                      (max_x - 1.0, max_y - 2.1 + offset, 5.70), 0.075,
                      materials[material_key])
        _add_insulation_seams(
            bpy, f"OverheadProcessLine_{offset}",
            (min_x + 1.0, max_y - 2.1 + offset, 5.70),
            (max_x - 1.0, max_y - 2.1 + offset, 5.70),
            0.075, materials["insulation_seam"], count=6)

    # A small maintenance catwalk and handrail give the upper pipe rack a
    # plausible service relationship instead of leaving it as floating lines.
    catwalk_y = max_y - 1.15
    _box(bpy, "North_ServiceCatwalk", (center_x, catwalk_y, 3.72),
         (width / 2 - 1.1, 0.42, 0.055), materials["grating"], bevel=0.012)
    for x in range(math.ceil(min_x) + 2, math.floor(max_x), 1):
        _box(bpy, f"North_CatwalkGrate_{x}", (x, catwalk_y, 3.79),
             (0.018, 0.40, 0.012), materials["steel"], bevel=0.004)
    _add_guardrail(
        bpy, "North_ServiceRail",
        list(range(math.ceil(min_x) + 2, math.floor(max_x), 2)),
        catwalk_y + 0.38, 4.26, materials)

    # Subtle stains and impact marks break up the perfect cladding without
    # turning the factory into a heavily stylized scene.
    for index, x in enumerate((min_x + 2.1, center_x - 2.8, center_x + 3.2, max_x - 1.7), start=1):
        _box(bpy, f"North_WallStain_{index}", (x, max_y - 0.168, 1.34 + index * 0.15),
             (0.10 + index * 0.015, 0.012, 0.42 + index * 0.08),
             materials["wall_stain"], bevel=0.02)
    for index, x in enumerate((min_x + 1.4, center_x + 1.6, max_x - 1.2), start=1):
        _add_flat_stain(bpy, f"FloorDustPatch_{index}", (x, min_y + 1.05 + index * 0.9, 0.01),
                        (0.42 + index * 0.09, 0.18 + index * 0.04), materials["dust"])

    for index, x in enumerate(range(math.ceil(min_x) + 2, math.floor(max_x), 5), start=1):
        _box(bpy, f"HighBayLuminaire_{index}", (x, center_y, 5.62),
             (0.72, 0.16, 0.06), materials["light_housing"], bevel=0.025)
        _box(bpy, f"HighBayDiffuser_{index}", (x, center_y, 5.54),
             (0.64, 0.12, 0.018), materials["luminaire"], bevel=0.01)
        bpy.ops.object.light_add(type="AREA", location=(x, center_y, 5.42))
        light = bpy.context.object
        light.name = f"HighBayLight_{index}"
        light.data.energy = 410
        light.data.shape = "RECTANGLE"
        light.data.size = 2.0
        light.data.size_y = 1.2
        _look_at(light, (x, center_y, 5.42), (x, center_y, 0.0))

    for x in range(math.ceil(min_x) + 1, math.floor(max_x), 2):
        for y in range(math.ceil(min_y) + 1, math.floor(max_y), 2):
            _box(bpy, f"FloorExpansionJointX_{x}_{y}", (x, y, 0.004),
                 (0.012, 0.98, 0.004), materials["floor_joint"], bevel=0)
    for x in range(math.ceil(min_x) + 1, math.floor(max_x), 2):
        _box(bpy, f"FloorDrain_{x}", (x, max_y - 1.6, 0.012),
             (0.32, 0.22, 0.012), materials["drain"], bevel=0.01)
        for stripe in range(5):
            _box(bpy, f"FloorDrainSlot_{x}_{stripe}",
                 (x - 0.24 + stripe * 0.12, max_y - 1.6, 0.028),
                 (0.018, 0.17, 0.008), materials["steel"], bevel=0.004)

    _box(bpy, "RollUpDoorPanel", (min_x + 0.18, center_y, 2.10),
         (0.06, 2.2, 2.10), materials["door"], bevel=0.02)
    for height in range(1, 8):
        _box(bpy, f"RollUpDoorRib_{height}", (min_x + 0.10, center_y, height * 0.52),
             (0.025, 2.18, 0.018), materials["steel"], bevel=0.006)
    _box(bpy, "FactoryIdentificationPlate", (center_x, max_y - 0.18, 4.92),
         (1.18, 0.025, 0.20), materials["label_plate"], bevel=0.012)
    _text(bpy, "FactoryIdentificationText", "PROCESS HALL A-C",
          (center_x, max_y - 0.214, 4.90), materials["ink"], size=0.105)


def _add_pipe_station(bpy, waypoint, materials):
    x, y = _equipment_position(waypoint)
    device = waypoint["device_id"]
    z = 2.55
    _box(bpy, f"{device}_Skid", (x, y, 0.20), (1.48, 0.88, 0.20),
         materials["concrete"], bevel=0.06)
    _box(bpy, f"{device}_SkidSteel", (x, y, 0.43), (1.32, 0.72, 0.035),
         materials["steel"], bevel=0.012)
    _pipe_between(bpy, f"{device}_SteamMain", (x - 1.9, y, z), (x + 1.9, y, z),
                  0.20, materials["steam_pipe"])
    _add_insulation_seams(bpy, f"{device}_SteamMain", (x - 1.9, y, z),
                          (x + 1.9, y, z), 0.20, materials["insulation_seam"], count=7)
    _add_valve(bpy, f"{device}_IsolationValve", (x - 0.72, y, z), 0.25, materials,
               axis="x", wheel_material="warning", body_material="steel")
    _box(bpy, f"{device}_ValveTagPlate", (x - 0.72, y - 0.20, z + 0.38),
         (0.12, 0.012, 0.042), materials["label_plate"], bevel=0.003)
    _text(bpy, f"{device}_ValveTag", "XV-302", (x - 0.72, y - 0.217, z + 0.372),
          materials["ink"], size=0.032)

    for side in (-1, 1):
        flange_x = x + side * 1.46
        _torus(bpy, f"{device}_FlangeGasket_{side}", (flange_x, y, z), 0.235, 0.025,
               materials["gasket"], rotation=(0, math.pi / 2, 0))
        _cylinder(bpy, f"{device}_Flange_{side}", (flange_x, y, z), 0.30, 0.12,
                  materials["steel"], rotation=(0, math.pi / 2, 0), vertices=64)
        for bolt in range(8):
            angle = math.tau * bolt / 8
            _cylinder(bpy, f"{device}_FlangeBolt_{side}_{bolt}",
                      (flange_x + side * 0.075, y + math.sin(angle) * 0.25,
                       z + math.cos(angle) * 0.25), 0.038, 0.045,
                      materials["brass"], rotation=(0, math.pi / 2, 0), vertices=6,
                      bevel=0.006)

    for support_index, sx in enumerate((-1.18, 1.18), start=1):
        _box(bpy, f"{device}_PipeShoe_{support_index}", (x + sx, y, z - 0.29),
             (0.25, 0.34, 0.07), materials["steel"], bevel=0.015)
        _box(bpy, f"{device}_StanchionFoot_{support_index}", (x + sx, y, 0.52),
             (0.24, 0.22, 0.07), materials["steel"], bevel=0.015)
        _box(bpy, f"{device}_Stanchion_{support_index}", (x + sx, y, 1.43),
             (0.07, 0.07, 0.86), materials["steel"], bevel=0.02)
        for bolt_x in (-0.14, 0.14):
            for bolt_y in (-0.12, 0.12):
                _cylinder(bpy, f"{device}_AnchorBolt_{support_index}_{bolt_x}_{bolt_y}",
                          (x + sx + bolt_x, y + bolt_y, 0.60), 0.035, 0.06,
                          materials["brass"], vertices=6, bevel=0.004)

    _pipe_between(bpy, f"{device}_ImpulseRiser", (x, y - 0.22, z),
                  (x, y - 0.22, 3.25), 0.045, materials["process_pipe"])
    _sphere(bpy, f"{device}_ImpulseTee", (x, y - 0.22, z),
            (0.095, 0.095, 0.095), materials["steel"], segments=24)
    _sphere(bpy, f"{device}_Manifold", (x, y - 0.22, 3.20),
            (0.12, 0.12, 0.10), materials["steel"], segments=20)
    _cylinder(bpy, f"{device}_RootValve", (x, y - 0.22, 3.38), 0.045, 0.28,
              materials["steel"], vertices=24)
    _torus(bpy, f"{device}_RootValveWheel", (x, y - 0.22, 3.55), 0.13, 0.018,
           materials["warning"])
    _add_gauge(bpy, f"{device}_PressureGauge", (x, y - 0.25, 3.85), 0.38,
               materials, value=7.2)
    _pipe_between(bpy, f"{device}_DrainLeg", (x + 0.62, y + 0.02, z),
                  (x + 0.62, y + 0.02, 1.02), 0.065, materials["process_pipe"])
    _add_valve(bpy, f"{device}_DrainValve", (x + 0.62, y + 0.02, 0.90), 0.12,
               materials, axis="z", wheel_material="brass", body_material="steel")

    # Relief branch, steam trap and a visible flow arrow complete the local
    # valve station instead of leaving the header as a single decorative tube.
    relief_x = x + 0.95
    _pipe_path(bpy, f"{device}_ReliefBranch",
               ((relief_x, y, z), (relief_x, y, z + 0.78),
                (relief_x, y - 0.32, z + 0.78)),
               0.060, materials["process_pipe"])
    _add_valve(bpy, f"{device}_ReliefValve", (relief_x, y - 0.32, z + 0.92),
               0.105, materials, axis="z", wheel_material="warning", body_material="steel")
    _box(bpy, f"{device}_ReliefTagPlate", (relief_x, y - 0.40, z + 1.30),
         (0.17, 0.018, 0.045), materials["label_plate"], bevel=0.004)
    _text(bpy, f"{device}_ReliefTag", "PSV-302",
          (relief_x, y - 0.424, z + 1.288), materials["ink"], size=0.030)
    trap_x = x - 1.10
    _box(bpy, f"{device}_SteamTrapBody", (trap_x, y - 0.18, 1.55),
         (0.18, 0.14, 0.16), materials["steel_dark"], bevel=0.025)
    _pipe_between(bpy, f"{device}_SteamTrapInlet", (trap_x, y, z),
                  (trap_x, y - 0.18, 1.72), 0.045, materials["steam_pipe"])
    _pipe_between(bpy, f"{device}_SteamTrapDrain", (trap_x, y - 0.18, 1.38),
                  (trap_x, y - 0.18, 0.96), 0.035, materials["process_pipe"])
    _text(bpy, f"{device}_FlowArrow", ">>", (x + 1.72, y - 0.24, z + 0.08),
          materials["label_plate"], size=0.15, rotation=(math.pi / 2, 0, 0))
    _box(bpy, f"{device}_TagPlate", (x - 1.05, y - 0.25, 1.50),
         (0.27, 0.018, 0.065), materials["label_plate"], bevel=0.005)
    _text(bpy, f"{device}_Tag", "PI-302",
          (x - 1.05, y - 0.274, 1.488), materials["ink"], size=0.047)


def _add_cabinet_station(bpy, waypoint, materials):
    x, y = _equipment_position(waypoint)
    device = waypoint["device_id"]
    _box(bpy, f"{device}_Plinth", (x, y, 0.14), (0.92, 0.62, 0.14),
         materials["steel"], bevel=0.03)
    _box(bpy, f"{device}_Body", (x, y, 1.40), (0.92, 0.54, 1.26),
         materials["cabinet"], bevel=0.06)
    _box(bpy, f"{device}_DoorFrame", (x, y - 0.57, 1.40), (0.84, 0.025, 1.16),
         materials["cabinet_frame"], bevel=0.018)
    _box(bpy, f"{device}_DoorSeal", (x, y - 0.603, 1.40), (0.74, 0.012, 1.04),
         materials["rubber_seal"], bevel=0.008)
    _box(bpy, f"{device}_InnerBackplate", (x, y - 0.552, 1.43),
         (0.82, 0.025, 1.10), materials["panel"], bevel=0.012)
    bpy.ops.object.light_add(type="AREA", location=(x, y - 1.15, 1.55))
    cabinet_light = bpy.context.object
    cabinet_light.name = f"{device}_ServiceLight"
    cabinet_light.data.energy = 45
    cabinet_light.data.shape = "RECTANGLE"
    cabinet_light.data.size = 1.2
    cabinet_light.data.size_y = 1.4
    cabinet_light.data.color = (0.78, 0.88, 1.0)
    _look_at(cabinet_light, (x, y - 1.15, 1.55), (x, y - 0.45, 1.45))

    door = _box(bpy, f"{device}_OpenDoor", (x + 1.08, y - 0.30, 1.42),
                (0.56, 0.045, 1.16), materials["cabinet_door"], bevel=0.025)
    door.rotation_euler[2] = math.radians(-24)
    for hinge_index, height in enumerate((0.42, 1.38, 2.22), start=1):
        _box(bpy, f"{device}_Hinge_{hinge_index}", (x - 0.84, y - 0.58, height),
             (0.05, 0.08, 0.12), materials["brass"], bevel=0.01)

    for bus, bus_x in enumerate((x - 0.54, x - 0.29, x - 0.04, x + 0.21), start=1):
        _box(bpy, f"{device}_CopperBus_{bus}", (bus_x, y - 0.60, 1.75),
             (0.035, 0.025, 0.50), materials["copper"], bevel=0.008)
        for terminal in range(5):
            z = 1.50 + terminal * 0.12
            _box(bpy, f"{device}_Terminal_{bus}_{terminal}", (bus_x, y - 0.65, z),
                 (0.09, 0.055, 0.055), materials["breaker"], bevel=0.008)
            _cylinder(bpy, f"{device}_TerminalScrew_{bus}_{terminal}",
                      (bus_x, y - 0.69, z), 0.018, 0.012,
                      materials["steel"], rotation=(math.pi / 2, 0, 0), vertices=12,
                      bevel=0.002)

    for breaker in range(3):
        bx = x + 0.46
        bz = 1.20 + breaker * 0.42
        _box(bpy, f"{device}_Breaker_{breaker}", (bx, y - 0.62, bz),
             (0.20, 0.08, 0.16), materials["breaker"] if breaker else materials["warning"],
             bevel=0.015)
        _box(bpy, f"{device}_BreakerToggle_{breaker}", (bx, y - 0.71, bz),
             (0.05, 0.025, 0.08), materials["panel"], bevel=0.008)

    for index, (bx, color) in enumerate(((x - 0.60, "pilot_green"),
                                         (x - 0.34, "warning"),
                                         (x - 0.08, "pilot_red")), start=1):
        _cylinder(bpy, f"{device}_PilotLamp_{index}", (bx, y - 0.63, 2.25),
                  0.075, 0.055, materials[color], rotation=(math.pi / 2, 0, 0),
                  vertices=32, bevel=0.008)
    _box(bpy, f"{device}_Display", (x + 0.37, y - 0.62, 2.10),
         (0.25, 0.035, 0.18), materials["display"], bevel=0.015)
    _text(bpy, f"{device}_DisplayText", "415 V", (x + 0.37, y - 0.665, 2.08),
          materials["display_text"], size=0.10)

    for side in (-1, 1):
        for vent in range(6):
            _box(bpy, f"{device}_Vent_{side}_{vent}",
                 (x + side * 0.64, y - 0.595, 0.47 + vent * 0.09),
                 (0.10, 0.012, 0.018), materials["steel"], bevel=0.004)
    for run in range(4):
        _pipe_between(bpy, f"{device}_CableDrop_{run}",
                      (x - 0.50 + run * 0.33, y + 0.12, 0.22),
                      (x - 0.50 + run * 0.33, y + 0.12, 0.90), 0.028,
                      materials["copper"] if run % 2 else materials["cable"])
    _box(bpy, f"{device}_CableGlandPlate", (x, y + 0.55, 0.31),
         (0.62, 0.045, 0.16), materials["panel"], bevel=0.018)
    for gland in range(6):
        gx = x - 0.45 + gland * 0.18
        _cylinder(bpy, f"{device}_CableGland_{gland}", (gx, y + 0.61, 0.32),
                  0.045, 0.06, materials["rubber_seal"], rotation=(math.pi / 2, 0, 0),
                  vertices=24, bevel=0.006)
    # Hinged door stay and earth braid make the open electrical enclosure read
    # as a serviceable cabinet rather than a flat display board.
    _pipe_between(bpy, f"{device}_DoorStay", (x + 0.66, y - 0.64, 1.05),
                  (x + 1.02, y - 0.46, 1.05), 0.022, materials["steel"])
    _pipe_between(bpy, f"{device}_EarthBraid", (x - 0.82, y - 0.64, 0.62),
                  (x - 1.05, y - 0.41, 0.50), 0.018, materials["copper"])
    for index in range(4):
        _box(bpy, f"{device}_DoorStiffener_{index}",
             (x + 1.08, y - 0.32, 0.52 + index * 0.60),
             (0.40, 0.018, 0.018), materials["steel"], bevel=0.004)
    _box(bpy, f"{device}_Nameplate", (x, y - 0.60, 2.50),
         (0.40, 0.025, 0.13), materials["label_plate"], bevel=0.008)
    _text(bpy, f"{device}_Label", "MCC 04  /  415 V",
          (x, y - 0.638, 2.48), materials["ink"], size=0.075)


def _add_pump_station(bpy, waypoint, materials):
    x, y = _equipment_position(waypoint)
    device = waypoint["device_id"]
    _box(bpy, f"{device}_InertiaBase", (x, y, 0.18), (1.60, 0.93, 0.18),
         materials["concrete"], bevel=0.07)
    _box(bpy, f"{device}_CommonSkid", (x, y, 0.40), (1.48, 0.82, 0.07),
         materials["steel"], bevel=0.025)
    for bx in (-1.28, 1.28):
        for by in (-0.63, 0.63):
            _cylinder(bpy, f"{device}_Anchor_{bx}_{by}", (x + bx, y + by, 0.49),
                      0.045, 0.08, materials["brass"], vertices=6, bevel=0.006)

    motor_x = x - 0.74
    _cylinder(bpy, f"{device}_MotorFrame", (motor_x, y, 1.04), 0.42, 1.13,
              materials["motor"], rotation=(0, math.pi / 2, 0), vertices=64)
    for ring in range(15):
        fin_x = motor_x - 0.48 + ring * 0.068
        _torus(bpy, f"{device}_CoolingFin_{ring:02d}", (fin_x, y, 1.04),
               0.36, 0.018, materials["steel"], rotation=(0, math.pi / 2, 0))
    for foot_x in (motor_x - 0.36, motor_x + 0.36):
        _box(bpy, f"{device}_MotorFoot_{foot_x}", (foot_x, y, 0.53),
             (0.20, 0.34, 0.10), materials["steel"], bevel=0.02)
    _box(bpy, f"{device}_TerminalBox", (motor_x, y, 1.53),
         (0.31, 0.27, 0.16), materials["motor"], bevel=0.035)
    _box(bpy, f"{device}_TerminalCover", (motor_x, y - 0.28, 1.53),
         (0.24, 0.025, 0.10), materials["label_plate"], bevel=0.01)

    _cylinder(bpy, f"{device}_CouplingShaft", (x - 0.12, y, 1.04), 0.095, 0.28,
              materials["steel"], rotation=(0, math.pi / 2, 0), vertices=32)
    _box(bpy, f"{device}_CouplingGuard", (x - 0.12, y - 0.02, 1.04),
         (0.28, 0.30, 0.25), materials["warning"], bevel=0.06)
    for bolt in range(6):
        angle = math.tau * bolt / 6
        _cylinder(bpy, f"{device}_GuardBolt_{bolt}",
                  (x - 0.12, y + math.sin(angle) * 0.25, 1.04 + math.cos(angle) * 0.20),
                  0.022, 0.025, materials["brass"], rotation=(0, math.pi / 2, 0),
                  vertices=6, bevel=0.004)

    _sphere(bpy, f"{device}_VoluteCasing", (x + 0.40, y, 1.04),
            (0.58, 0.50, 0.57), materials["pump"], segments=48)
    _cylinder(bpy, f"{device}_VoluteCover", (x + 0.40, y - 0.52, 1.04),
              0.44, 0.08, materials["pump"], rotation=(math.pi / 2, 0, 0),
              vertices=64)
    _torus(bpy, f"{device}_VoluteCoverRim", (x + 0.40, y - 0.57, 1.04),
           0.39, 0.035, materials["brass"], rotation=(math.pi / 2, 0, 0))
    for bolt in range(10):
        angle = math.tau * bolt / 10
        _cylinder(bpy, f"{device}_CasingBolt_{bolt}",
                  (x + 0.40 + math.sin(angle) * 0.38, y - 0.60,
                   1.04 + math.cos(angle) * 0.38), 0.034, 0.035,
                  materials["steel"], rotation=(math.pi / 2, 0, 0), vertices=6,
                  bevel=0.004)

    _pipe_between(bpy, f"{device}_SuctionNozzle", (x + 0.40, y + 0.42, 1.04),
                  (x + 0.40, y + 1.24, 1.04), 0.18, materials["process_pipe"])
    _add_flange(bpy, f"{device}_SuctionFlange", (x + 0.40, y + 1.20, 1.04),
                0.28, 0.11, materials, rotation=(math.pi / 2, 0, 0), bolt_count=8)
    _pipe_between(bpy, f"{device}_SuctionElbowRise", (x + 0.40, y + 1.24, 1.04),
                  (x + 0.40, y + 1.24, 2.40), 0.18, materials["process_pipe"])
    _add_valve(bpy, f"{device}_SuctionIsolationValve", (x + 0.40, y + 1.24, 1.72),
               0.20, materials, axis="z", wheel_material="warning", body_material="steel")
    # A short rubber expansion joint sits between the pump discharge and the
    # rigid header, giving the assembly a mechanically credible transition.
    _pipe_between(bpy, f"{device}_DischargeFlexibleJoint", (x + 0.76, y, 1.72),
                  (x + 0.76, y, 2.20), 0.16, materials["rubber"])
    for seam in range(4):
        _torus(bpy, f"{device}_FlexibleJointRib_{seam}",
               (x + 0.76, y, 1.78 + seam * 0.12), 0.17, 0.018,
               materials["rubber"], rotation=(0.0, 0.0, 0.0))
    _pipe_between(bpy, f"{device}_DischargeRiserLower", (x + 0.76, y, 1.04),
                  (x + 0.76, y, 1.72), 0.16, materials["process_pipe"])
    _pipe_between(bpy, f"{device}_DischargeRiserUpper", (x + 0.76, y, 2.20),
                  (x + 0.76, y, 2.55), 0.16, materials["process_pipe"])
    _pipe_between(bpy, f"{device}_DischargeHeader", (x + 0.76, y, 2.55),
                  (x + 1.85, y, 2.55), 0.16, materials["process_pipe"])
    _add_flange(bpy, f"{device}_DischargeFlange", (x + 0.76, y, 2.52),
                0.27, 0.11, materials, rotation=(0, math.pi / 2, 0), bolt_count=8)
    _add_valve(bpy, f"{device}_DischargeCheckValve", (x + 1.32, y, 2.55),
               0.18, materials, axis="x", wheel_material="brass", body_material="steel")
    _pipe_between(bpy, f"{device}_VentBranch", (x + 1.10, y - 0.02, 2.55),
                  (x + 1.10, y - 0.02, 3.10), 0.045, materials["process_pipe"])
    _add_valve(bpy, f"{device}_VentValve", (x + 1.10, y - 0.02, 3.15),
               0.10, materials, axis="z", wheel_material="brass", body_material="steel")
    _add_gauge(bpy, f"{device}_DischargeGauge", (x + 0.98, y - 0.24, 2.98),
               0.30, materials, value=5.4)
    _box(bpy, f"{device}_EquipmentPlate", (x + 0.35, y - 0.58, 1.78),
         (0.22, 0.014, 0.055), materials["label_plate"], bevel=0.004)
    _text(bpy, f"{device}_EquipmentTag", "P-021  CW",
          (x + 0.35, y - 0.601, 1.765), materials["ink"], size=0.041)
    _box(bpy, f"{device}_MotorPlate", (motor_x, y - 0.39, 1.03),
         (0.32, 0.024, 0.085), materials["label_plate"], bevel=0.006)
    _text(bpy, f"{device}_MotorLabel", "MTR-021",
          (motor_x, y - 0.421, 1.02), materials["ink"], size=0.065)
    _torus(bpy, f"{device}_LeakRing", (x + 0.95, y - 0.96, 0.035),
           0.24, 0.018, materials["leak"])
    _sphere(bpy, f"{device}_OilSpot", (x + 0.95, y - 0.96, 0.025),
            (0.31, 0.18, 0.018), materials["leak"], segments=32)
    _box(bpy, f"{device}_MaintenanceTray", (x + 0.55, y - 0.86, 0.06),
         (0.62, 0.20, 0.035), materials["drain"], bevel=0.025)
    _add_guardrail(bpy, f"{device}_PumpGuard", (x - 1.45, x + 1.55), y + 0.78, 1.18, materials)


def _add_equipment(bpy, scene, materials):
    for waypoint in scene["waypoints"]:
        if "PIPE" in waypoint["waypoint_id"]:
            _add_pipe_station(bpy, waypoint, materials)
        elif "CABINET" in waypoint["waypoint_id"]:
            _add_cabinet_station(bpy, waypoint, materials)
        elif "PUMP" in waypoint["waypoint_id"]:
            _add_pump_station(bpy, waypoint, materials)
        else:
            _add_inspection_node(bpy, waypoint, materials)


def _bounds(scene):
    points = [(0.0, 0.0)]
    points.extend((float(item["x"]), float(item["y"])) for item in scene["waypoints"])
    points.extend((float(item["x"]), float(item["y"])) for item in scene.get("trajectory", []))
    xs, ys = zip(*points)
    return (min(-4.0, min(xs) - 4.0), max(18.0, max(xs) + 4.0),
            min(-8.0, min(ys) - 4.0), max(8.0, max(ys) + 5.0))


def _add_lighting(bpy, bounds, hdri_path: Path | None = None):
    min_x, max_x, min_y, max_y = bounds
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    world = bpy.context.scene.world or bpy.data.worlds.new("VirtualFactoryWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.16, 0.19, 0.20, 1.0)
        background.inputs["Strength"].default_value = 0.30
        if hdri_path is not None and hdri_path.is_file():
            image = bpy.data.images.load(str(hdri_path), check_existing=True)
            if not image.packed_file:
                image.pack()
            coordinates = world.node_tree.nodes.new("ShaderNodeTexCoord")
            coordinates.name = "IndustrialHDRICoordinates"
            mapping = world.node_tree.nodes.new("ShaderNodeMapping")
            mapping.name = "IndustrialHDRIRotation"
            mapping.inputs["Rotation"].default_value[2] = math.radians(28.0)
            environment = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
            environment.name = "IndustrialWorkshopFoundryHDRI"
            environment.image = image
            environment.interpolation = "Linear"
            world.node_tree.links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
            world.node_tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
            world.node_tree.links.new(environment.outputs["Color"], background.inputs["Color"])
            world["environment_asset"] = "industrial_workshop_foundry_2k.hdr"
            world["environment_license"] = "CC0 1.0"
    for index, (x, y, energy, size) in enumerate((
        (center_x - 5, center_y - 4, 760, 8),
        (center_x + 6, center_y + 3, 660, 7),
        (center_x - 8, max_y - 2, 560, 6),
    ), start=1):
        bpy.ops.object.light_add(type="AREA", location=(x, y, 6.2))
        light = bpy.context.object
        light.name = f"FactoryAreaLight_{index}"
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.data.size_y = size
        light.data.color = (0.84, 0.90, 0.86) if index != 2 else (1.0, 0.78, 0.52)
        _look_at(light, (x, y, 6.2), (center_x, center_y, 0))
    bpy.ops.object.light_add(type="SUN", location=(center_x, center_y, 7))
    sun = bpy.context.object
    sun.name = "FactorySun"
    sun.data.energy = 0.12
    sun.rotation_euler = (math.radians(24), math.radians(-18), math.radians(32))


def _robot_camera_target(waypoint):
    """Return a low-mounted RGB camera pose aimed at the inspected asset."""
    robot_x, robot_y = float(waypoint["x"]), float(waypoint["y"])
    equipment_x, equipment_y = _equipment_position(waypoint)
    waypoint_id = waypoint["waypoint_id"]
    if "PIPE" in waypoint_id:
        return (robot_x, robot_y, 0.82), (equipment_x + 0.38, equipment_y - 0.28, 3.72)
    elif "VESSEL" in waypoint_id:
        target_z = 2.15
    elif "CRANE" in waypoint_id:
        target_z = 2.30
    elif "HVAC" in waypoint_id:
        target_z = 1.90
    elif "PUMP" in waypoint_id:
        return (robot_x, robot_y, 0.82), (equipment_x + 0.45, equipment_y - 0.35, 2.98)
    else:
        target_z = 1.45
    return (robot_x, robot_y, 0.82), (equipment_x, equipment_y, target_z)


def _nearest_trajectory_frame(trajectory, waypoint):
    """Return the zero-based route frame closest to a configured waypoint."""
    if not trajectory:
        return 0
    return min(
        range(len(trajectory)),
        key=lambda frame: math.hypot(
            float(trajectory[frame]["x"]) - float(waypoint["x"]),
            float(trajectory[frame]["y"]) - float(waypoint["y"]),
        ),
    )


def _mark_synchronized_camera(camera, *, role, waypoint_id, trajectory_index):
    """Store the shared route clock on every camera that represents a waypoint."""
    camera["camera_role"] = role
    camera["sync_waypoint_id"] = waypoint_id
    camera["sync_trajectory_index"] = int(trajectory_index)
    camera["render_frame"] = int(trajectory_index) + 1


def _add_cameras(bpy, scene, bounds, orbit_count):
    min_x, max_x, min_y, max_y = bounds
    center = ((min_x + max_x) / 2, (min_y + max_y) / 2, 1.2)
    width, depth = max_x - min_x, max_y - min_y
    cameras = {}
    cameras["factory_overview.png"] = _camera(
        bpy, "CAM_OVERVIEW", (center[0] - 1.5, min_y - 11.5, 8.2),
        (center[0] + 0.4, center[1] + 0.35, 1.65), lens=36)
    cameras["factory_aerial.png"] = _camera(
        bpy, "CAM_AERIAL", (center[0] - 13.0, min_y - 12.0, 16.8),
        (center[0] + 0.7, center[1] + 0.55, 1.55), lens=34)
    cameras["factory_process_floor.png"] = _camera(
        bpy, "CAM_PROCESS_FLOOR", (center[0] + 1.0, min_y - 4.6, 3.0),
        (center[0] + 1.0, center[1] + 0.7, 1.45), lens=46, dof_fstop=6.3)
    cameras["factory_operator.png"] = _camera(
        bpy, "CAM_OPERATOR", (min_x - 1.0, min_y - 3.5, 2.65),
        (center[0] + 1.0, center[1] + 0.5, 1.55), lens=34)
    cameras["factory_low_operator.png"] = _camera(
        bpy, "CAM_LOW_OPERATOR", (center[0] - 7.5, min_y - 3.1, 1.35),
        (center[0] + 1.2, center[1] + 1.0, 1.45), lens=38)
    cameras["factory_pipe_rack_upward.png"] = _camera(
        bpy, "CAM_PIPE_RACK_UPWARD", (center[0] + 1.4, center[1] + 1.1, 1.15),
        (center[0] + 1.8, max_y - 1.9, 4.65), lens=32)
    cameras["factory_pump_maintenance.png"] = _camera(
        bpy, "CAM_PUMP_MAINTENANCE", (12.7, 3.0, 1.35),
        (11.5, 5.7, 1.35), lens=44, dof_fstop=4.5)
    cameras["factory_asset_map.png"] = _camera(
        bpy, "CAM_ASSET_MAP", (center[0] - 3.8, min_y - 10.5, 12.8),
        (center[0] + 0.4, center[1] + 0.25, 1.2), lens=30)
    cameras["factory_cable_tray.png"] = _camera(
        bpy, "CAM_CABLE_TRAY", (center[0] - 5.2, center[1] - 1.2, 2.45),
        (center[0] + 0.8, max_y - 1.1, 4.75), lens=38, dof_fstop=5.0)
    cameras["factory_instrument_air.png"] = _camera(
        bpy, "CAM_INSTRUMENT_AIR", (center[0] + 4.0, center[1] - 2.0, 2.8),
        (center[0] + 1.0, max_y - 2.72, 3.45), lens=44, dof_fstop=4.8)
    cameras["factory_floor_services.png"] = _camera(
        bpy, "CAM_FLOOR_SERVICES", (center[0] + 4.2, min_y + 1.0, 0.92),
        (center[0] + 4.5, center[1] + 0.2, 0.20), lens=46, dof_fstop=4.0)
    cameras["factory_valve_station.png"] = _camera(
        bpy, "CAM_VALVE_STATION", (2.6, -0.55, 2.65),
        (4.0, 3.2, 2.65), lens=50, dof_fstop=3.8)
    cameras["factory_electrical_boundary.png"] = _camera(
        bpy, "CAM_ELECTRICAL_BOUNDARY", (7.4, -3.65, 1.85),
        (8.0, 0.2, 1.45), lens=46, dof_fstop=4.0)
    # Dedicated presentation views keep the industrial evidence legible at
    # normal review distance. They are separate from the route cameras so the
    # operator can inspect a valve, MCC, pump, instrument and the full bay
    # without changing the synchronized playback clock.
    cameras["factory_hero_valve_station.png"] = _camera(
        bpy, "CAM_HERO_VALVE_STATION", (1.85, 0.42, 2.85),
        (4.0, 3.02, 2.62), lens=58, dof_fstop=4.8)
    cameras["factory_hero_mcc.png"] = _camera(
        bpy, "CAM_HERO_MCC", (6.25, -4.05, 1.82),
        (8.05, -0.02, 1.46), lens=52, dof_fstop=5.8)
    cameras["factory_hero_pump.png"] = _camera(
        bpy, "CAM_HERO_PUMP", (10.05, 2.62, 1.72),
        (11.55, 5.10, 1.35), lens=60, dof_fstop=4.6)
    cameras["factory_hero_instrument.png"] = _camera(
        bpy, "CAM_HERO_INSTRUMENT", (1.65, 0.20, 3.40),
        (5.10, 3.18, 2.78), lens=68, dof_fstop=5.6)
    cameras["factory_hero_valve_macro.png"] = _camera(
        bpy, "CAM_HERO_VALVE_MACRO", (2.10, 0.16, 2.96),
        (3.75, 2.90, 2.72), lens=74, dof_fstop=6.2)
    cameras["factory_hero_gauge_macro.png"] = _camera(
        bpy, "CAM_HERO_GAUGE_MACRO", (2.65, 1.72, 3.50),
        (4.02, 2.91, 3.84), lens=58, dof_fstop=11.0)
    cameras["factory_hero_mcc_macro.png"] = _camera(
        bpy, "CAM_HERO_MCC_MACRO", (6.30, -3.52, 1.68),
        (8.00, -0.18, 1.48), lens=62, dof_fstop=6.8)
    cameras["factory_hero_mcc_interior.png"] = _camera(
        bpy, "CAM_HERO_MCC_INTERIOR", (7.22, -3.08, 1.48),
        (8.00, 0.10, 1.50), lens=58, dof_fstop=7.4)
    cameras["factory_hero_pump_macro.png"] = _camera(
        bpy, "CAM_HERO_PUMP_MACRO", (9.84, 2.78, 1.58),
        (10.98, 4.98, 1.34), lens=76, dof_fstop=6.0)
    cameras["factory_hero_wide.png"] = _camera(
        bpy, "CAM_HERO_WIDE", (center[0] - 5.8, min_y - 6.2, 5.65),
        (center[0] + 1.2, center[1] + 0.15, 2.10), lens=42, dof_fstop=8.0)

    trajectory = scene.get("trajectory") or [{"x": 0.0, "y": 0.0, "yaw_deg": 0.0}]
    reference_waypoint = scene["waypoints"][0] if scene.get("waypoints") else {
        "waypoint_id": "WP_01", "x": trajectory[0]["x"], "y": trajectory[0]["y"],
    }
    reference_frame = _nearest_trajectory_frame(trajectory, reference_waypoint)
    robot_location, inspection_target = _robot_camera_target(reference_waypoint)
    first_person = _camera(
        bpy, "CAM_ROBOT_FIRST_PERSON", robot_location,
        inspection_target, lens=48)
    _mark_synchronized_camera(
        first_person, role="robot_first_person",
        waypoint_id=reference_waypoint["waypoint_id"],
        trajectory_index=reference_frame,
    )
    cameras["factory_robot_first_person.png"] = first_person

    # Keep one fixed warehouse camera for synchronized replay, but place it
    # off the central portal column so the MCC and process aisle remain
    # inspectable instead of being split by a structural post.
    cctv_position = (center[0] + width * 0.30, min_y - 3.2, 8.5)
    cctv_target = (center[0] - 0.8, center[1] + 0.2, 0.35)
    for index, waypoint in enumerate(scene["waypoints"], start=1):
        camera = _camera(
            bpy, f"CAM_WAREHOUSE_CCTV_{index:02d}",
            cctv_position, cctv_target, lens=38)
        waypoint_frame = _nearest_trajectory_frame(trajectory, waypoint)
        _mark_synchronized_camera(
            camera, role="warehouse_cctv",
            waypoint_id=waypoint["waypoint_id"],
            trajectory_index=waypoint_frame,
        )
        cameras[f"factory_cctv__{waypoint['waypoint_id']}.png"] = camera

    for index, waypoint in enumerate(scene["waypoints"], start=1):
        equipment_x, equipment_y = _equipment_position(waypoint)
        waypoint_id = waypoint["waypoint_id"]
        if "PIPE" in waypoint_id or "VESSEL" in waypoint_id:
            overview_z, detail_z = 3.25, 3.85
        elif any(token in waypoint_id for token in ("PUMP", "EXCHANGER", "FILTER")):
            overview_z, detail_z = 1.90, 2.25
        elif "CRANE" in waypoint_id:
            overview_z, detail_z = 4.15, 4.55
        else:
            overview_z, detail_z = 1.55, 1.70
        robot_location, inspection_target = _robot_camera_target(waypoint)
        robot_rgb = _camera(
            bpy, f"CAM_WP_{index:02d}",
            robot_location, inspection_target, lens=48)
        waypoint_frame = _nearest_trajectory_frame(trajectory, waypoint)
        _mark_synchronized_camera(
            robot_rgb, role="robot_rgb",
            waypoint_id=waypoint["waypoint_id"],
            trajectory_index=waypoint_frame,
        )
        cameras[f"virtual_world__{waypoint['waypoint_id']}__rgb_camera.png"] = robot_rgb
        detail_distance = 5.20 if any(token in waypoint_id for token in ("PIPE", "VESSEL")) else 4.75
        detail_target_z = 3.00 if any(token in waypoint_id for token in ("PIPE", "VESSEL")) else 1.35
        cameras[f"factory_detail_{waypoint['waypoint_id'].lower()}.png"] = _camera(
            bpy, f"CAM_DETAIL_{index:02d}",
            (equipment_x - 0.12, equipment_y - detail_distance, detail_z),
            (equipment_x, equipment_y - 0.25, detail_target_z),
            lens=45 if "PIPE" in waypoint["waypoint_id"] else 48,
            dof_fstop=4.0 if "PIPE" in waypoint["waypoint_id"] else 5.6)

    # Orbit cameras stay inside the shell. A radius based on the largest
    # dimension placed several cameras outside the west/back walls, producing
    # black frames when the camera looked through solid geometry.
    orbit_radius = min(width, depth) * 0.36
    for index in range(max(1, orbit_count)):
        angle = math.radians(index * 360.0 / max(1, orbit_count))
        name = f"factory_orbit_{index + 1:02d}.png"
        cameras[name] = _camera(
            bpy, f"CAM_ORBIT_{index + 1:02d}",
            (center[0] + math.cos(angle) * orbit_radius,
             center[1] + math.sin(angle) * orbit_radius,
             4.8 + 0.7 * math.sin(angle * 2)),
            center, lens=35)
    return cameras


def _animate_robot(root, trajectory):
    root.animation_data_clear()
    for frame, pose in enumerate(trajectory or [{"x": 0.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}], start=1):
        root.location = (float(pose["x"]), float(pose["y"]), float(pose.get("z", 0.0)))
        root.rotation_euler[2] = math.radians(float(pose.get("yaw_deg", 0.0)))
        root.keyframe_insert(data_path="location", frame=frame)
        root.keyframe_insert(data_path="rotation_euler", index=2, frame=frame)


def _render_synchronized_streams(bpy, scene, output_dir: Path, trajectory, *,
                                 quality: str, frame_count: int,
                                 stream_resolution: int,
                                 frame_duration_s: float = 0.36) -> dict:
    """Render a low-bandwidth, route-indexed robot/CCTV image stream.

    The stream intentionally samples the same kinematic timeline used by the
    waypoint stills. It is image evidence for a local simulation, not a live
    sensor transport. Keeping the stream at 16:9 and a modest resolution makes
    it useful in the browser without multiplying the heavy presentation render.
    """
    if frame_count <= 0 or not trajectory:
        return {}
    frame_count = max(2, min(int(frame_count), len(trajectory)))
    stream_resolution = max(256, int(stream_resolution))
    route_indices = sorted({
        round(index * (len(trajectory) - 1) / (frame_count - 1))
        for index in range(frame_count)
    })
    if len(route_indices) < 2:
        return {}

    cctv_base = bpy.data.objects.get("CAM_WAREHOUSE_CCTV_01")
    if cctv_base is None:
        return {}
    cctv_stream = cctv_base.copy()
    cctv_stream.data = cctv_base.data.copy()
    cctv_stream.name = "CAM_STREAM_WAREHOUSE_CCTV"
    bpy.context.collection.objects.link(cctv_stream)
    robot_stream = _camera(
        bpy, "CAM_STREAM_ROBOT_HEAD", (0.0, 0.0, 0.82), (2.0, 0.0, 1.35),
        lens=46,
    )

    scene.render.resolution_x = stream_resolution
    scene.render.resolution_y = max(144, int(stream_resolution * 9 / 16))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.compression = 18
    scene.render.use_persistent_data = True
    stream_frames = []
    frame_duration_s = max(0.001, float(frame_duration_s))
    for sequence_index, trajectory_index in enumerate(route_indices):
        pose = trajectory[trajectory_index]
        x, y = float(pose["x"]), float(pose["y"])
        yaw = math.radians(float(pose.get("yaw_deg", 0.0)))
        scene.frame_set(trajectory_index + 1)

        robot_location = (x, y, 0.82 + float(pose.get("z", 0.0)))
        robot_target = (
            x + math.cos(yaw) * 3.6,
            y + math.sin(yaw) * 3.6,
            1.38 + float(pose.get("z", 0.0)),
        )
        _look_at(robot_stream, robot_location, robot_target)
        robot_name = f"robot_rgb_stream__F{sequence_index + 1:04d}.png"
        robot_path = output_dir / robot_name
        scene.camera = robot_stream
        scene.render.filepath = str(robot_path)
        if not robot_path.is_file():
            bpy.ops.render.render(write_still=True)

        cctv_name = f"warehouse_cctv_stream__F{sequence_index + 1:04d}.png"
        cctv_path = output_dir / cctv_name
        scene.camera = cctv_stream
        scene.render.filepath = str(cctv_path)
        if not cctv_path.is_file():
            bpy.ops.render.render(write_still=True)

        stream_frames.append({
            "sequence_index": sequence_index,
            "trajectory_index": trajectory_index,
            "render_frame": trajectory_index + 1,
            "robot_artifact": robot_name,
            "cctv_artifact": cctv_name,
            "same_route_frame": True,
        })

    manifest = {
        "schema_version": 1,
        "stream_type": "synthetic_synchronized_image_stream",
        "frame_count": len(stream_frames),
        "route_frame_count": len(trajectory),
        "frame_duration_s": frame_duration_s,
        "recommended_playback_speed": 0.5,
        "resolution": {
            "width": stream_resolution,
            "height": max(144, int(stream_resolution * 9 / 16)),
        },
        "robot_sensor": "virtual_world/base_link/rgb_camera",
        "fixed_sensor": "warehouse/cctv/01",
        "frames": stream_frames,
        "limitations": [
            "Frames are rendered from a local Blender scene.",
            "The robot and CCTV are simulated viewpoints, not live sensors.",
            "The route is kinematic and does not model contact dynamics.",
        ],
    }
    (output_dir / "synchronized_video_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


_CAMERA_FILTER: tuple[str, ...] = ()


def _set_property(target, name: str, value) -> bool:
    """Set a Blender RNA property only when the current build exposes it."""
    if not hasattr(target, name):
        return False
    try:
        setattr(target, name, value)
    except (TypeError, ValueError, RuntimeError):
        return False
    return True


def _configure_render_quality(scene, quality: str) -> dict:
    """Apply version-aware EEVEE settings and report what actually took effect."""
    profiles = {
        "preview": {
            "samples": 32,
            "shadow_pool_size": "512",
            "shadow_ray_count": 1,
            "fast_gi_quality": 0.35,
            "fast_gi_ray_count": 2,
            "ray_resolution_scale": "2",
            "ray_quality": 0.35,
        },
        "production": {
            "samples": 128,
            "shadow_pool_size": "1024",
            "shadow_ray_count": 2,
            "fast_gi_quality": 0.65,
            "fast_gi_ray_count": 4,
            "ray_resolution_scale": "2",
            "ray_quality": 0.65,
        },
        "ultra": {
            "samples": 256,
            "shadow_pool_size": "2048",
            "shadow_ray_count": 4,
            "fast_gi_quality": 0.90,
            "fast_gi_ray_count": 8,
            "ray_resolution_scale": "4",
            "ray_quality": 0.90,
        },
    }
    profile = profiles.get(quality, profiles["production"])
    engine = scene.render.engine
    settings = {
        "profile": quality,
        "engine": engine,
        "samples": None,
        "ray_tracing": False,
        "ray_tracing_method": None,
        "ray_tracing_resolution_scale": None,
        "ray_tracing_denoise": None,
        "shadow_pool_size": None,
        "shadow_ray_count": None,
        "fast_gi_quality": None,
        "fast_gi_ray_count": None,
    }
    # Blender 5.2 exposes these settings through Scene.eevee even though the
    # engine identifier is the legacy BLENDER_EEVEE string.
    eevee = getattr(scene, "eevee", None)
    if eevee is None or engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
        return settings

    if _set_property(eevee, "taa_render_samples", profile["samples"]):
        settings["samples"] = int(eevee.taa_render_samples)
    _set_property(eevee, "use_shadows", True)
    if _set_property(eevee, "shadow_pool_size", profile["shadow_pool_size"]):
        settings["shadow_pool_size"] = str(eevee.shadow_pool_size)
    if _set_property(eevee, "shadow_ray_count", profile["shadow_ray_count"]):
        settings["shadow_ray_count"] = int(eevee.shadow_ray_count)
    _set_property(eevee, "shadow_resolution_scale", 1.25 if quality == "ultra" else 1.0)
    _set_property(eevee, "use_fast_gi", True)
    if _set_property(eevee, "fast_gi_quality", profile["fast_gi_quality"]):
        settings["fast_gi_quality"] = float(eevee.fast_gi_quality)
    if _set_property(eevee, "fast_gi_ray_count", profile["fast_gi_ray_count"]):
        settings["fast_gi_ray_count"] = int(eevee.fast_gi_ray_count)
    _set_property(eevee, "fast_gi_step_count", 16 if quality == "ultra" else 10)
    _set_property(eevee, "gi_visibility_resolution", "64" if quality == "ultra" else "32")
    _set_property(eevee, "gi_cubemap_resolution", "1024" if quality == "ultra" else "512")
    _set_property(eevee, "use_gtao", True)
    _set_property(eevee, "gtao_distance", 3.0 if quality == "ultra" else 2.2)
    _set_property(eevee, "gtao_factor", 1.35 if quality == "ultra" else 1.10)

    ray_options = getattr(eevee, "ray_tracing_options", None)
    if _set_property(eevee, "use_raytracing", True):
        settings["ray_tracing"] = bool(eevee.use_raytracing)
    if _set_property(eevee, "ray_tracing_method", "SCREEN"):
        settings["ray_tracing_method"] = str(eevee.ray_tracing_method)
    if ray_options is not None:
        if _set_property(ray_options, "resolution_scale", profile["ray_resolution_scale"]):
            settings["ray_tracing_resolution_scale"] = str(ray_options.resolution_scale)
        if _set_property(ray_options, "use_denoise", True):
            settings["ray_tracing_denoise"] = bool(ray_options.use_denoise)
        _set_property(ray_options, "denoise_spatial", True)
        _set_property(ray_options, "denoise_temporal", True)
        _set_property(ray_options, "denoise_bilateral", True)
        _set_property(ray_options, "screen_trace_quality", profile["ray_quality"])
        _set_property(ray_options, "screen_trace_thickness", 0.18 if quality == "ultra" else 0.12)
        _set_property(ray_options, "trace_max_roughness", 0.72 if quality == "ultra" else 0.60)
    return settings


def _configure_render_effects(scene, quality: str):
    """Add restrained camera-like glow without flattening inspection detail."""
    if not hasattr(scene, "use_nodes"):
        return
    try:
        scene.use_nodes = True
        nodes = scene.node_tree.nodes
        links = scene.node_tree.links
        nodes.clear()
        render_layers = nodes.new("CompositorNodeRLayers")
        render_layers.name = "V23_RenderLayers"
        glare = nodes.new("CompositorNodeGlare")
        glare.name = "V23_SubtleHighBayGlow"
        glare.glare_type = "FOG_GLOW"
        glare.quality = "HIGH" if quality != "preview" else "MEDIUM"
        glare.threshold = 1.25 if quality == "ultra" else 1.45
        glare.size = 7 if quality == "ultra" else 6
        glare.mix = -0.94
        composite = nodes.new("CompositorNodeComposite")
        composite.name = "V23_Composite"
        links.new(render_layers.outputs["Image"], glare.inputs["Image"])
        links.new(glare.outputs["Image"], composite.inputs["Image"])
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Optional effect only: keep the scene renderable across Blender builds
        # with different compositor sockets.
        return


def _render(bpy, scene, output_dir: Path, resolution: int, cameras, quality: str):
    available_engines = {
        item.identifier
        for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    }
    scene.render.engine = (
        "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available_engines
        else "BLENDER_EEVEE" if "BLENDER_EEVEE" in available_engines
        else "BLENDER_WORKBENCH"
    )
    scene.render.resolution_x = resolution
    scene.render.resolution_y = max(480, int(resolution * 9 / 16))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.compression = 15
    scene.render.threads_mode = "FIXED"
    scene.render.threads = max(2, min(12, __import__("os").cpu_count() or 4))
    scene.render.use_high_quality_normals = True
    scene.render.use_persistent_data = True
    render_settings = _configure_render_quality(scene, quality)
    _configure_render_effects(scene, quality)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Keep a filtered/resumed render honest: existing PNGs in this versioned
    # output directory remain part of the completed camera set.
    rendered_cameras = [
        filename for filename in cameras
        if (output_dir / filename).is_file()
    ]
    for filename, camera in cameras.items():
        if _CAMERA_FILTER and not any(token in filename for token in _CAMERA_FILTER):
            continue
        scene.camera = camera
        scene.render.filepath = str(output_dir / filename)
        scene.frame_set(int(camera.get("render_frame", 1)))
        bpy.ops.render.render(write_still=True)
        if filename not in rendered_cameras:
            rendered_cameras.append(filename)
    return render_settings, rendered_cameras


def _write_scene_manifest(output_dir: Path, scene, cameras, bounds, *, quality: str,
                          resolution: int, render_settings: dict,
                          navigation_overlays_rendered: bool,
                          rendered_cameras: list[str], hdri_path: Path | None):
    camera_metadata = {}
    for filename, camera in cameras.items():
        camera_metadata[filename] = {
            "camera_role": camera.get("camera_role", "scene_camera"),
            "render_frame": int(camera.get("render_frame", 1)),
            "rendered": filename in rendered_cameras,
        }
        if "sync_waypoint_id" in camera:
            camera_metadata[filename].update({
                "sync_waypoint_id": camera["sync_waypoint_id"],
                "sync_trajectory_index": int(camera["sync_trajectory_index"]),
            })
    synchronized_captures = []
    for waypoint in scene.get("waypoints", []):
        waypoint_id = waypoint["waypoint_id"]
        robot_name = f"virtual_world__{waypoint_id}__rgb_camera.png"
        cctv_name = f"factory_cctv__{waypoint_id}.png"
        robot_meta = camera_metadata[robot_name]
        cctv_meta = camera_metadata[cctv_name]
        synchronized_captures.append({
            "waypoint_id": waypoint_id,
            "trajectory_index": robot_meta["sync_trajectory_index"],
            "render_frame": robot_meta["render_frame"],
            "robot_rgb_artifact": robot_name,
            "warehouse_cctv_artifact": cctv_name,
            "same_route_frame": (
                robot_meta["render_frame"] == cctv_meta["render_frame"]
                and robot_meta["sync_trajectory_index"] == cctv_meta["sync_trajectory_index"]
            ),
        })
    (output_dir / "factory_camera_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "site_id": scene["site_id"],
            "unit_scale": "1 Blender unit = 1 metre",
            "factory_bounds_m": {
                "min_x": bounds[0], "max_x": bounds[1],
                "min_y": bounds[2], "max_y": bounds[3],
            },
            "cameras": sorted(cameras),
            "rendered_cameras": rendered_cameras,
            "camera_metadata": camera_metadata,
            "synchronized_captures": synchronized_captures,
            "rendered_locally": True,
            "environment_asset": (
                hdri_path.name if hdri_path is not None and hdri_path.is_file() else None
            ),
            "environment_asset_license": "CC0 1.0" if hdri_path is not None and hdri_path.is_file() else None,
            "render_quality": quality,
            "render_resolution": {
                "width": resolution,
                "height": max(480, int(resolution * 9 / 16)),
            },
            "render_engine": render_settings.get("engine"),
            "render_samples": render_settings.get("samples"),
            "render_settings": render_settings,
            "navigation_overlays_rendered": navigation_overlays_rendered,
            "robot_asset": "procedural_virtual_quadruped",
            "limitations": [
                "No official Unitree asset is included.",
                "The robot uses a kinematic route and does not model contact dynamics.",
                "Synthetic sensor values are attached to the inspection workflow.",
                "The factory is a procedural virtual environment, not a scan of a real facility.",
            ],
            "scene_detail_level": "factory_environment_v35_premium_manufacturing_realism",
            "environment_layers": [
            "background process vessels and exchanger",
            "layered pipe rack with supports and overhead crane",
            "HVAC, fire protection, emergency shower and maintenance bay",
            "field junction boxes, impulse tubing, cable conduits and access platforms",
            "pipe clamps, branch manifolds, hazard zones and service signage",
            "ladder cable trays with hangers and field cable drops",
            "instrument-air header with branch isolation valves",
            "portal-frame base plates, anchor nuts, floor trenches and cleanouts",
            "relief branch, steam trap, flow marking and secondary valve accessories",
            "robot-height RGB inspection cameras with asset-directed framing",
            "separate navigation overlay and photographic render layers",
            "production material roughness variation and restrained industrial lighting",
            "high-frequency manufactured-surface microfinish and roughness breakup",
            "condensate streaks, floor oil halos, paint loss and weld witness marks",
            "robot camera bezel, lens, lidar ring, service panel, seals and foot tread",
            "dedicated hero inspection views for valve, MCC, pump and field instrumentation",
            "close-range washer/nut stacks, packing rings, enclosure latches and service loops",
            "gauge glass covers, brushed rating plates, motor end bell and grease points",
            "occupied cable trays with field bundles, clips and strain-relief loops",
            "portal-frame gusset plates, anchor bolts, cladding fasteners and service plates",
            "instrument-air regulator, bowl, isolation valve and riveted tag",
            "floor drain grates, cleanout collars, overhead junction cabinet and conduit drops",
            "mid-scale substrate finish for painted steel, concrete, pipework, cabinets and labels",
            "restrained clear-coat response on painted and brushed manufactured surfaces",
            "muted painted-steel palette with substrate-specific roughness and transmission details",
            "cladding gasket joints, wall-foot grime and concrete-to-slab moisture patches",
            "equipment plinth dust envelopes and offset floor shadow evidence",
            "weld heat-affected bands, local bare-metal impact wear and service-height chips",
            "MCC and pump sensor cable bundles with geometric service loops",
            "version-aware EEVEE samples, ray tracing, fast GI and shadow pool configuration",
            "directional brushed and rolled manufacturing marks on steel and stainless substrates",
            "irregular layered floor oil, dust, condensate and forklift scuff evidence",
            "paint edge strikes, faded cladding bands, exposed substrate and rust scale",
            "individually routed MCC control wires, ferrule tags and termination details",
            "barcode-like asset identification plates and lockout-readable label faces",
            "compressed gasket contact rings and maintenance-height coating scratches",
            "balanced high-bay exposure with subdued diffuser emission and mixed industrial fill",
            "installed access covers with separate bolt and slot geometry",
            "process flow labels, directional bands and short service identifiers",
            "field cable-entry plates with glands and conduit continuity",
            "physical fixed-CCTV housings, service loops and status indicators",
            "robot docking point with pad, status lamps and local identifier",
            "overhead conduit drops with saddle clamps and roll-up door hardware",
            "subtle compositor fog glow and version-aware ambient occlusion",
            "independent multi-color tray conductors with tie-down clips and field harness drops",
            "MCC terminal rail with ferrules, colored control wires and earth-bond continuity",
            "weld beads, heat-affected bands and discrete bead texture at service joints",
            "physical LOTO and line-service plates with short asset identifiers",
            "cladding captive fasteners, seal beads, cross-direction floor joints and anchor sockets",
            "CCTV gland plates, armored tails and wall-entry termination hardware",
            "localized valve, MCC, pump and instrument task lighting",
            "physical calibration witness plates, rivets and instrument service loops",
            "service-height dust envelopes grounded under illuminated inspection assets",
            "MCC interior service-face with separated electrical bays and DIN rails",
            "slotted vertical and horizontal wiring ducts with controlled conductor routing",
            "field terminal strip, ferrule markers, phase busbars and protective earth bar",
            "cabinet gasket witnesses, breaker state windows, service labels and coating wear",
            "open MCC sheet-metal enclosure with recessed rear panel and front service frame",
            "three-phase busbar chamber with insulating stand-offs and guarded service edge",
            "molded-case breaker, motor starter, DIN modules and individually marked terminal blocks",
            "slotted cable ducts, routed multi-color control conductors, door hinges and earth bond",
            "high-bay luminaire housings, diffusers, hangers and mixed-color local task lights",
            "wall-mounted junction boxes with latches, asset tags and conduit drops",
            "raised floor service boxes with anchor bolts, access covers and warning stripes",
            "fixed PPE, arc-flash and eyewash safety signage on the plant boundary",
            "robot docking and charging station with display, pilot lamps and service cable",
            "short process identification tags for steam, cooling-water return and instrument air",
            "v28 cladding seams, captive fasteners and wall panel anchors",
            "v28 field service plates, cable glands and strain-relief tails",
            "v28 floor joint inserts and waypoint calibration witness plates",
            "route-indexed sampled robot RGB and fixed CCTV image stream",
            "v35 multi-scale noise and cellular coating breakup for steel, concrete, powder coat and stainless surfaces",
            "v35 flange gasket compression, washer and nut stacks, threaded take-offs and localized weld witness bands",
            "v35 gauge anti-glare glass, bezel screws, calibration sticker and pressure fitting hierarchy",
            "v35 pump bearing housing, split-line fasteners, grout cracks, grease nipple and irregular oil film",
            "v35 MCC sheet-metal folds, captive screws, gland locknuts, terminal markers and isolation label",
            "v35 vessel and exchanger circumferential welds, tube-sheet gasket compression and inspection witness stamps",
            "v35 localized substrate moisture, impact wear and roof-joint fastener evidence",
            "v35 asset-specific micro task lights with preserved aisle shadow depth",
        ],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _add_scene(bpy, scene_data: dict, output_dir: Path, resolution: int, orbit_count: int,
               camera_filter: tuple[str, ...] = (), *, quality: str = "production",
               hdri_path: Path | None = None,
               render_navigation_overlays: bool = False,
               skip_glb_export: bool = False, stream_frames: int = 0,
               stream_resolution: int = 512):
    global _CAMERA_FILTER
    _CAMERA_FILTER = camera_filter
    bpy.ops.wm.read_factory_settings(use_empty=True)
    materials = {
        "floor": _material(bpy, "FactoryFloor", (0.29, 0.32, 0.29, 1), roughness=0.88,
                           texture_scale=11, bump_distance=0.045),
        "wall": _material(bpy, "FactoryCladding", (0.47, 0.52, 0.49, 1), roughness=0.74,
                          texture_scale=42, bump_distance=0.018),
        "window": _material(bpy, "FactoryGlass", (0.21, 0.38, 0.43, 1), metallic=0.34,
                            roughness=0.2),
        "steel": _material(bpy, "StructuralSteel", (0.31, 0.36, 0.38, 1), metallic=0.82,
                           roughness=0.28, texture_scale=150, bump_distance=0.008),
        "steel_dark": _material(bpy, "StructuralSteelDark", (0.18, 0.22, 0.23, 1), metallic=0.84,
                                 roughness=0.34, texture_scale=115, bump_distance=0.010),
        "concrete": _material(bpy, "Concrete", (0.39, 0.41, 0.38, 1), roughness=0.93,
                               texture_scale=18, bump_distance=0.075),
        "floor_joint": _material(bpy, "FloorJoint", (0.16, 0.18, 0.17, 1), roughness=0.92),
        "dust": _material(bpy, "FloorDust", (0.18, 0.17, 0.14, 1), roughness=0.96,
                          texture_scale=18, bump_distance=0.01),
        "dust_edge": _material(bpy, "DustEdge", (0.12, 0.105, 0.082, 1), roughness=0.98,
                               texture_scale=36, bump_distance=0.004),
        "floor_scuff": _material(bpy, "FloorScuff", (0.10, 0.095, 0.080, 1), roughness=0.88,
                                  texture_scale=46, bump_distance=0.003),
        "oil_sheen": _material(bpy, "OilSheen", (0.018, 0.016, 0.012, 1), metallic=0.12,
                                roughness=0.10, texture_scale=28, bump_distance=0.001),
        "drain": _material(bpy, "DrainCastIron", (0.22, 0.25, 0.25, 1), metallic=0.68,
                           roughness=0.58),
        "pipe": _material(bpy, "UtilityPipe", (0.43, 0.48, 0.46, 1), metallic=0.74,
                          roughness=0.27),
        "steam_pipe": _material(bpy, "SteamLineAluminium", (0.48, 0.53, 0.49, 1),
                                metallic=0.72, roughness=0.34),
        "process_pipe": _material(bpy, "ProcessPipe", (0.42, 0.48, 0.44, 1), metallic=0.60,
                                  roughness=0.36),
        "instrument": _material(bpy, "InstrumentEnclosure", (0.34, 0.42, 0.42, 1),
                                 metallic=0.32, roughness=0.30, texture_scale=80,
                                 bump_distance=0.006),
        "instrument_door": _material(bpy, "InstrumentDoor", (0.47, 0.53, 0.51, 1),
                                     metallic=0.25, roughness=0.32),
        "instrument_tube": _material(bpy, "InstrumentTube", (0.69, 0.73, 0.69, 1),
                                      metallic=0.72, roughness=0.22),
        "instrument_air": _material(bpy, "InstrumentAir", (0.36, 0.54, 0.43, 1),
                                     metallic=0.42, roughness=0.31),
        "conduit": _material(bpy, "ElectricalConduit", (0.10, 0.14, 0.14, 1),
                              metallic=0.62, roughness=0.34),
        "insulation_seam": _material(bpy, "InsulationSeam", (0.34, 0.37, 0.34, 1),
                                      roughness=0.78),
        "gasket": _material(bpy, "FlangeGasket", (0.045, 0.055, 0.05, 1), roughness=0.82),
        "gasket_compressed": _material(bpy, "CompressedGasketContact", (0.020, 0.024, 0.022, 1),
                                        roughness=0.68, texture_scale=90, bump_distance=0.002),
        "brass": _material(bpy, "InstrumentBrass", (0.58, 0.39, 0.13, 1), metallic=0.78,
                           roughness=0.24),
        "copper": _material(bpy, "CopperBusbar", (0.65, 0.30, 0.12, 1), metallic=0.82,
                            roughness=0.26),
        "cable": _material(bpy, "CableTray", (0.16, 0.19, 0.20, 1), metallic=0.62,
                           roughness=0.37),
        "lane": _material(bpy, "SafetyLane", (0.91, 0.60, 0.08, 1), roughness=0.53),
        "lane_white": _material(bpy, "LaneWhite", (0.75, 0.79, 0.74, 1), roughness=0.7),
        "door": _material(bpy, "RollUpDoor", (0.32, 0.38, 0.39, 1), metallic=0.43,
                          roughness=0.42),
        "cabinet": _material(bpy, "Cabinet", (0.30, 0.39, 0.39, 1), metallic=0.28,
                             roughness=0.32),
        "cabinet_door": _material(bpy, "CabinetDoor", (0.39, 0.46, 0.44, 1), metallic=0.24,
                                  roughness=0.31),
        "cabinet_frame": _material(bpy, "CabinetDoorFrame", (0.18, 0.22, 0.22, 1),
                                    metallic=0.30, roughness=0.38),
        "rubber_seal": _material(bpy, "RubberSeal", (0.025, 0.030, 0.028, 1), roughness=0.78),
        "panel": _material(bpy, "ElectricalPanel", (0.14, 0.17, 0.17, 1), roughness=0.42),
        "breaker": _material(bpy, "Breaker", (0.58, 0.60, 0.56, 1), roughness=0.44),
        "warning": _material(bpy, "Warning", (0.73, 0.40, 0.025, 1), metallic=0.16,
                             roughness=0.38),
        "warning_black": _material(bpy, "WarningBlack", (0.04, 0.045, 0.038, 1),
                                    metallic=0.10, roughness=0.44),
        "safety_yellow": _material(bpy, "SafetyYellow", (0.90, 0.54, 0.04, 1),
                                    metallic=0.16, roughness=0.34),
        "pilot_green": _material(bpy, "PilotGreen", (0.05, 0.52, 0.22, 1), roughness=0.2,
                                 emission=(0.03, 0.28, 0.08, 1)),
        "pilot_red": _material(bpy, "PilotRed", (0.72, 0.035, 0.025, 1), roughness=0.2,
                               emission=(0.38, 0.015, 0.01, 1)),
        "display": _material(bpy, "Display", (0.018, 0.048, 0.046, 1), metallic=0.12,
                             roughness=0.12),
        "display_text": _material(bpy, "DisplayText", (0.18, 0.9, 0.61, 1), roughness=0.24,
                                  emission=(0.08, 0.8, 0.48, 1)),
        "label_plate": _material(bpy, "LabelPlate", (0.58, 0.61, 0.56, 1), metallic=0.42,
                                 roughness=0.38, texture_scale=120, bump_distance=0.003),
        "pump": _material(bpy, "PumpHousing", (0.40, 0.075, 0.018, 1), metallic=0.48,
                          roughness=0.38, texture_scale=90, bump_distance=0.008),
        "tank_coat": _material(bpy, "TankCoating", (0.38, 0.43, 0.40, 1), metallic=0.48,
                                roughness=0.40, texture_scale=75, bump_distance=0.010),
        "stainless": _material(bpy, "StainlessSteel", (0.61, 0.66, 0.65, 1), metallic=0.86,
                                roughness=0.25, texture_scale=125, bump_distance=0.006),
        "crane_yellow": _material(bpy, "CraneSafetyYellow", (0.84, 0.49, 0.045, 1), metallic=0.22,
                                   roughness=0.36, texture_scale=42, bump_distance=0.006),
        "chain": _material(bpy, "HoistChain", (0.12, 0.14, 0.14, 1), metallic=0.82,
                            roughness=0.30),
        "fan_blade": _material(bpy, "FanBlade", (0.34, 0.40, 0.39, 1), metallic=0.65,
                                roughness=0.30),
        "louver": _material(bpy, "VentLouver", (0.28, 0.34, 0.34, 1), metallic=0.48,
                             roughness=0.38),
        "fire_red": _material(bpy, "FireEquipmentRed", (0.68, 0.045, 0.025, 1), metallic=0.12,
                               roughness=0.34, texture_scale=55, bump_distance=0.006),
        "fire_glass": _material(bpy, "FireCabinetGlass", (0.25, 0.08, 0.055, 1), metallic=0.08,
                                 roughness=0.18),
        "hose_red": _material(bpy, "FireHose", (0.42, 0.035, 0.018, 1), roughness=0.60),
        "safety_green": _material(bpy, "SafetyGreen", (0.08, 0.48, 0.22, 1), metallic=0.12,
                                   roughness=0.38),
        "parts_bin": _material(bpy, "PartsBin", (0.12, 0.28, 0.33, 1), metallic=0.08,
                                roughness=0.44),
        "drum_blue": _material(bpy, "DrumBlue", (0.08, 0.23, 0.35, 1), metallic=0.32,
                                roughness=0.40),
        "drum_yellow": _material(bpy, "DrumYellow", (0.72, 0.42, 0.045, 1), metallic=0.20,
                                  roughness=0.42),
        "wood": _material(bpy, "PalletWood", (0.45, 0.27, 0.12, 1), roughness=0.72,
                           texture_scale=18, bump_distance=0.035),
        "motor": _material(bpy, "Motor", (0.22, 0.29, 0.30, 1), metallic=0.76, roughness=0.25),
        "dial": _material(bpy, "GaugeDial", (0.88, 0.88, 0.79, 1), roughness=0.2),
        "ink": _material(bpy, "GaugeInk", (0.025, 0.035, 0.03, 1), roughness=0.52),
        "needle": _material(bpy, "GaugeNeedle", (0.73, 0.075, 0.025, 1), metallic=0.25,
                            roughness=0.25),
        "gauge": _material(bpy, "Gauge", (0.76, 0.86, 0.85, 1), roughness=0.2),
        "gauge_glass": _set_transmission(
            _material(bpy, "GaugeGlass", (0.19, 0.28, 0.27, 1), metallic=0.05,
                      roughness=0.06),
            0.78,
        ),
        "fastener": _material(bpy, "FastenerSteel", (0.18, 0.21, 0.20, 1), metallic=0.86,
                               roughness=0.26, texture_scale=160, bump_distance=0.004),
        "insulation": _material(bpy, "InsulationJacket", (0.34, 0.38, 0.34, 1), roughness=0.72,
                                 texture_scale=70, bump_distance=0.012),
        "leak": _material(bpy, "LeakIndicator", (0.05, 0.22, 0.30, 1), metallic=0.36,
                          roughness=0.18),
        "light_housing": _material(bpy, "LuminaireHousing", (0.46, 0.50, 0.49, 1),
                                   metallic=0.45, roughness=0.35),
        "grating": _material(bpy, "MaintenanceGrating", (0.16, 0.19, 0.19, 1),
                             metallic=0.70, roughness=0.46),
        "fence": _material(bpy, "SafetyFence", (0.82, 0.50, 0.05, 1), metallic=0.22,
                           roughness=0.42),
        "wall_stain": _material(bpy, "WallStain", (0.24, 0.25, 0.23, 1), roughness=0.98,
                                texture_scale=8, bump_distance=0.015),
        "wall_joint": _material(bpy, "WallPanelJoint", (0.13, 0.16, 0.15, 1), roughness=0.98),
        "base_dust": _material(bpy, "EquipmentBaseDust", (0.11, 0.095, 0.075, 1), roughness=0.99,
                                texture_scale=28, bump_distance=0.004),
        "bare_steel": _material(bpy, "BareSteelWear", (0.25, 0.29, 0.28, 1), metallic=0.76,
                                 roughness=0.34, texture_scale=90, bump_distance=0.005),
        "heat_affected": _material(bpy, "WeldHeatAffectedZone", (0.16, 0.18, 0.17, 1), metallic=0.42,
                                    roughness=0.48, texture_scale=48, bump_distance=0.006),
        "luminaire": _material(bpy, "LuminaireDiffuser", (0.82, 0.88, 0.80, 1), roughness=0.18,
                               emission=(0.72, 0.86, 0.70, 1)),
        "robot": _material(bpy, "RobotBlue", (0.035, 0.25, 0.45, 1), metallic=0.58,
                           roughness=0.24),
        "robot_dark": _material(bpy, "RobotDark", (0.045, 0.065, 0.07, 1), metallic=0.72,
                                roughness=0.24),
        "rubber": _material(bpy, "RobotRubber", (0.025, 0.032, 0.03, 1), roughness=0.86),
        "sensor": _material(bpy, "RobotSensor", (0.25, 0.85, 0.95, 1), metallic=0.1, roughness=0.15,
                             emission=(0.02, 0.22, 0.30, 1)),
        "route": _material(bpy, "InspectionRoute", (0.045, 0.25, 0.10, 1), roughness=0.46,
                            emission=(0.003, 0.012, 0.004, 1)),
        "route_arrow": _material(bpy, "RouteDirectionArrow", (0.08, 0.34, 0.16, 1),
                                 roughness=0.44),
        "marker": _material(bpy, "WaypointMarker", (0.63, 0.16, 0.035, 1), roughness=0.44,
                            emission=(0.012, 0.001, 0.0003, 1)),
        "marker_text": _material(bpy, "WaypointText", (0.58, 0.20, 0.035, 1), roughness=0.52),
        "label": _material(bpy, "Labels", (0.86, 0.92, 0.84, 1), roughness=0.42),
        "lens": _material(bpy, "RobotLens", (0.015, 0.055, 0.070, 1), metallic=0.42,
                          roughness=0.08, emission=(0.005, 0.035, 0.05, 1)),
        "rubber_wear": _material(bpy, "RubberWear", (0.018, 0.022, 0.020, 1), roughness=0.92,
                                 texture_scale=24, bump_distance=0.012),
        "robot_panel": _material(bpy, "RobotServicePanel", (0.10, 0.15, 0.17, 1), metallic=0.46,
                                  roughness=0.38, texture_scale=60, bump_distance=0.006),
        "rust_streak": _material(bpy, "RustStreak", (0.28, 0.08, 0.025, 1), metallic=0.08,
                                 roughness=0.86, texture_scale=18, bump_distance=0.010),
        "grime": _material(bpy, "PlantGrime", (0.12, 0.11, 0.09, 1), roughness=0.97,
                           texture_scale=24, bump_distance=0.006),
        "floor_oil": _material(bpy, "FloorOilHalo", (0.12, 0.10, 0.07, 1), metallic=0.05,
                               roughness=0.68, texture_scale=14, bump_distance=0.002),
        "oil_wet": _material(bpy, "WetOilCore", (0.025, 0.022, 0.016, 1), metallic=0.16,
                             roughness=0.24, texture_scale=22, bump_distance=0.002),
        "paint_chip": _material(bpy, "PaintChip", (0.08, 0.09, 0.085, 1), metallic=0.42,
                                roughness=0.46, texture_scale=45, bump_distance=0.008),
        "paint_fade": _material(bpy, "PaintFade", (0.22, 0.24, 0.22, 1), metallic=0.28,
                                roughness=0.58, texture_scale=55, bump_distance=0.004),
        "rust_scale": _material(bpy, "RustScale", (0.20, 0.055, 0.018, 1), metallic=0.08,
                                roughness=0.90, texture_scale=30, bump_distance=0.010),
        "label_white": _material(bpy, "LabelWhite", (0.78, 0.80, 0.74, 1), roughness=0.46,
                                 texture_scale=65, bump_distance=0.002),
        "wire_red": _material(bpy, "ControlWireRed", (0.58, 0.035, 0.020, 1), roughness=0.40,
                               texture_scale=70, bump_distance=0.002),
        "wire_blue": _material(bpy, "ControlWireBlue", (0.035, 0.17, 0.42, 1), roughness=0.42,
                                texture_scale=70, bump_distance=0.002),
        "wire_yellow": _material(bpy, "ControlWireYellow", (0.78, 0.48, 0.035, 1), roughness=0.42,
                                  texture_scale=70, bump_distance=0.002),
        "wire_black": _material(bpy, "ControlWireBlack", (0.025, 0.030, 0.028, 1), roughness=0.54,
                                 texture_scale=70, bump_distance=0.002),
        "warning_plate": _material(bpy, "WarningPlate", (0.94, 0.72, 0.10, 1), metallic=0.10,
                                    roughness=0.34, texture_scale=16, bump_distance=0.004),
        "warning_ink": _material(bpy, "WarningInk", (0.035, 0.028, 0.018, 1), roughness=0.48),
        "weld_bead": _material(bpy, "WeldBead", (0.42, 0.45, 0.43, 1), metallic=0.66,
                                roughness=0.39, texture_scale=80, bump_distance=0.012),
        "mcc_shell": _material(bpy, "MCCShellPaint", (0.105, 0.145, 0.15, 1), metallic=0.64,
                                roughness=0.42, texture_scale=105, bump_distance=0.006),
        "mcc_back": _material(bpy, "MCCBackplate", (0.040, 0.060, 0.065, 1), metallic=0.52,
                               roughness=0.52, texture_scale=85, bump_distance=0.006),
        "mcc_plastic": _material(bpy, "MCCMoldedPlastic", (0.19, 0.23, 0.23, 1), metallic=0.12,
                                  roughness=0.44, texture_scale=48, bump_distance=0.004),
        "mcc_insulator": _material(bpy, "MCCBusInsulator", (0.23, 0.31, 0.29, 1), metallic=0.05,
                                    roughness=0.50, texture_scale=32, bump_distance=0.004),
        "mcc_guard": _material(bpy, "MCCBusGuard", (0.08, 0.13, 0.14, 1), metallic=0.42,
                                roughness=0.38),
        "mcc_duct": _material(bpy, "MCCCableDuct", (0.075, 0.10, 0.105, 1), metallic=0.34,
                               roughness=0.48, texture_scale=60, bump_distance=0.004),
        "v35_coating": _material(bpy, "V35PowderCoat", (0.13, 0.17, 0.17, 1), metallic=0.42,
                                  roughness=0.48, texture_scale=80, bump_distance=0.005),
        "v35_weld": _material(bpy, "V35WeldBead", (0.24, 0.27, 0.26, 1), metallic=0.58,
                               roughness=0.47, texture_scale=70, bump_distance=0.010),
        "v35_gasket": _material(bpy, "V35CompressedGasket", (0.022, 0.028, 0.025, 1),
                                 roughness=0.76, texture_scale=95, bump_distance=0.003),
        "v35_glass": _set_transmission(
            _material(bpy, "V35AntiGlareGlass", (0.05, 0.09, 0.085, 1), metallic=0.04,
                      roughness=0.045, texture_scale=42, bump_distance=0.001),
            0.78, ior=1.46,
        ),
        "v35_oxide": _material(bpy, "V35LocalizedOxide", (0.16, 0.045, 0.014, 1),
                                 metallic=0.06, roughness=0.91, texture_scale=36,
                                 bump_distance=0.008),
        "v35_oil": _material(bpy, "V35OilFilm", (0.022, 0.019, 0.014, 1), metallic=0.12,
                              roughness=0.20, texture_scale=22, bump_distance=0.002),
        "v35_concrete_chip": _material(bpy, "V35ConcreteChip", (0.23, 0.22, 0.18, 1),
                                        roughness=0.92, texture_scale=52, bump_distance=0.006),
    }
    # Keep the layered gauge covers physically present while reducing the
    # milky alpha that made the earlier macro frame lose its scale markings.
    for key, alpha in (("gauge_glass", 0.20), ("v35_glass", 0.10)):
        shader = materials[key].node_tree.nodes.get("Principled BSDF")
        if shader is not None and shader.inputs.get("Alpha") is not None:
            shader.inputs["Alpha"].default_value = alpha
        if shader is not None and shader.inputs.get("Roughness") is not None:
            shader.inputs["Roughness"].default_value = 0.045 if key == "v35_glass" else 0.08
    # Apply a restrained second-scale finish to manufactured surfaces. The
    # profiles vary by substrate so concrete does not read like polished steel.
    for key, profile in {
        "steel": (190.0, 0.13, 0.006, 0.20, 0.38),
        "steel_dark": (155.0, 0.12, 0.007, 0.24, 0.43),
        "concrete": (95.0, 0.17, 0.022, 0.84, 0.98),
        "floor": (120.0, 0.10, 0.012, 0.78, 0.93),
        "wall": (110.0, 0.08, 0.009, 0.66, 0.82),
        "pipe": (180.0, 0.10, 0.005, 0.20, 0.36),
        "steam_pipe": (220.0, 0.08, 0.004, 0.18, 0.32),
        "process_pipe": (185.0, 0.10, 0.005, 0.20, 0.37),
        "instrument": (150.0, 0.09, 0.004, 0.24, 0.40),
        "instrument_door": (130.0, 0.08, 0.004, 0.26, 0.42),
        "stainless": (210.0, 0.07, 0.003, 0.18, 0.31),
        "tank_coat": (135.0, 0.09, 0.005, 0.26, 0.43),
        "pump": (155.0, 0.11, 0.005, 0.23, 0.40),
        "cabinet": (125.0, 0.08, 0.004, 0.27, 0.43),
        "cabinet_door": (125.0, 0.08, 0.004, 0.28, 0.44),
        "mcc_shell": (130.0, 0.08, 0.004, 0.30, 0.48),
        "mcc_back": (95.0, 0.07, 0.004, 0.42, 0.60),
        "mcc_plastic": (95.0, 0.07, 0.004, 0.34, 0.54),
        "mcc_insulator": (70.0, 0.06, 0.004, 0.40, 0.60),
        "mcc_duct": (90.0, 0.07, 0.004, 0.38, 0.58),
        "crane_yellow": (100.0, 0.08, 0.004, 0.28, 0.45),
        "grating": (170.0, 0.11, 0.006, 0.32, 0.52),
        "label_plate": (120.0, 0.06, 0.003, 0.28, 0.48),
        "fastener": (170.0, 0.08, 0.004, 0.20, 0.36),
        "insulation": (85.0, 0.10, 0.010, 0.62, 0.82),
    }.items():
        _microfinish(materials[key], scale=profile[0], bump_strength=profile[1],
                     bump_distance=profile[2], roughness_min=profile[3],
                     roughness_max=profile[4])

    # The v19 layer sits between broad material noise and microfinish. This
    # scale is large enough to remain legible in the robot and CCTV views,
    # while keeping labels, gauge faces and emissive indicators clean.
    for key, profile in {
        "steel": (30.0, 0.040, 0.0025, 0.22, 0.40),
        "steel_dark": (26.0, 0.045, 0.0028, 0.26, 0.45),
        "concrete": (18.0, 0.060, 0.0080, 0.86, 0.99),
        "floor": (22.0, 0.035, 0.0040, 0.80, 0.95),
        "wall": (24.0, 0.030, 0.0035, 0.68, 0.84),
        "pipe": (32.0, 0.034, 0.0022, 0.22, 0.38),
        "steam_pipe": (36.0, 0.030, 0.0018, 0.20, 0.34),
        "process_pipe": (32.0, 0.034, 0.0022, 0.22, 0.40),
        "instrument": (28.0, 0.030, 0.0020, 0.26, 0.42),
        "instrument_door": (26.0, 0.028, 0.0020, 0.28, 0.44),
        "stainless": (34.0, 0.026, 0.0015, 0.19, 0.33),
        "tank_coat": (28.0, 0.032, 0.0023, 0.28, 0.45),
        "pump": (29.0, 0.040, 0.0025, 0.24, 0.42),
        "cabinet": (25.0, 0.030, 0.0020, 0.28, 0.45),
        "cabinet_door": (25.0, 0.030, 0.0020, 0.29, 0.46),
        "crane_yellow": (22.0, 0.028, 0.0020, 0.30, 0.46),
        "grating": (30.0, 0.040, 0.0025, 0.34, 0.54),
        "label_plate": (24.0, 0.022, 0.0015, 0.29, 0.50),
        "fastener": (34.0, 0.028, 0.0016, 0.22, 0.38),
        "insulation": (20.0, 0.038, 0.0045, 0.64, 0.84),
    }.items():
        _add_midscale_surface_finish(
            materials[key], scale=profile[0], bump_strength=profile[1],
            bump_distance=profile[2], roughness_min=profile[3],
            roughness_max=profile[4],
        )

    for key, profile in {
        "dust_edge": (42.0, 0.028, 0.0030, 0.76, 0.98),
        "floor_scuff": (54.0, 0.026, 0.0022, 0.72, 0.92),
        "oil_sheen": (34.0, 0.018, 0.0010, 0.08, 0.22),
        "gasket_compressed": (80.0, 0.024, 0.0015, 0.58, 0.82),
        "paint_fade": (58.0, 0.030, 0.0020, 0.48, 0.72),
        "rust_scale": (32.0, 0.050, 0.0030, 0.74, 0.98),
        "label_white": (70.0, 0.018, 0.0012, 0.34, 0.58),
        "wire_red": (72.0, 0.018, 0.0012, 0.30, 0.48),
        "wire_blue": (72.0, 0.018, 0.0012, 0.30, 0.48),
        "wire_yellow": (72.0, 0.018, 0.0012, 0.30, 0.48),
        "wire_black": (72.0, 0.018, 0.0012, 0.42, 0.62),
    }.items():
        _add_midscale_surface_finish(
            materials[key], scale=profile[0], bump_strength=profile[1],
            bump_distance=profile[2], roughness_min=profile[3],
            roughness_max=profile[4],
        )

    for key in (
        "steel", "steel_dark", "pipe", "steam_pipe", "process_pipe",
        "instrument", "instrument_door", "stainless", "tank_coat", "pump",
        "cabinet", "cabinet_door", "crane_yellow", "grating", "label_plate",
        "fastener",
    ):
        _set_coat_weight(materials[key], weight=0.10 if key != "stainless" else 0.06,
                         roughness=0.24 if key not in {"grating", "fastener"} else 0.30)

    for key, strength in {
        "steel": 0.16,
        "steel_dark": 0.12,
        "pipe": 0.22,
        "steam_pipe": 0.28,
        "process_pipe": 0.20,
        "stainless": 0.34,
        "fastener": 0.18,
    }.items():
        _set_anisotropy(materials[key], strength=strength)

    for key, scale in {
        "steel": 175.0,
        "pipe": 210.0,
        "steam_pipe": 230.0,
        "process_pipe": 205.0,
        "stainless": 260.0,
        "fastener": 190.0,
        "pump": 135.0,
    }.items():
        _add_directional_finish(materials[key], scale=scale)

    # v35 adds a distinct coating signal on the surfaces that dominate the
    # close-up cameras. It is intentionally kept off gauges, labels and lights.
    for key, profile in {
        "steel": (68.0, 0.84, 1.10, 0.055, 0.0028, 0.20, 0.42),
        "steel_dark": (74.0, 0.80, 1.12, 0.060, 0.0032, 0.24, 0.46),
        "steam_pipe": (92.0, 0.86, 1.08, 0.048, 0.0022, 0.19, 0.37),
        "process_pipe": (86.0, 0.83, 1.10, 0.052, 0.0025, 0.21, 0.42),
        "stainless": (115.0, 0.90, 1.05, 0.040, 0.0018, 0.17, 0.34),
        "pump": (62.0, 0.78, 1.13, 0.060, 0.0030, 0.25, 0.46),
        "tank_coat": (58.0, 0.80, 1.12, 0.058, 0.0032, 0.27, 0.48),
        "mcc_shell": (72.0, 0.78, 1.12, 0.060, 0.0030, 0.30, 0.54),
        "mcc_back": (52.0, 0.82, 1.10, 0.048, 0.0024, 0.40, 0.64),
        "cabinet": (66.0, 0.80, 1.10, 0.052, 0.0026, 0.27, 0.48),
        "concrete": (44.0, 0.82, 1.10, 0.072, 0.0080, 0.84, 1.00),
        "floor": (52.0, 0.86, 1.08, 0.052, 0.0048, 0.78, 0.96),
        "wall": (48.0, 0.84, 1.10, 0.046, 0.0040, 0.66, 0.86),
    }.items():
        _add_v35_material_breakup(
            materials[key], scale=profile[0], dark_factor=profile[1],
            light_factor=profile[2], bump_strength=profile[3],
            bump_distance=profile[4], roughness_min=profile[5],
            roughness_max=profile[6],
        )
    for key, profile in {
        "v35_coating": (74.0, 0.78, 1.14, 0.060, 0.0032, 0.30, 0.56),
        "v35_weld": (96.0, 0.76, 1.12, 0.070, 0.0040, 0.32, 0.58),
        "v35_gasket": (105.0, 0.72, 1.12, 0.048, 0.0022, 0.58, 0.84),
        "v35_oxide": (28.0, 0.64, 1.18, 0.060, 0.0040, 0.78, 0.99),
        "v35_oil": (24.0, 0.70, 1.18, 0.030, 0.0012, 0.10, 0.30),
        "v35_concrete_chip": (46.0, 0.72, 1.12, 0.056, 0.0040, 0.76, 0.98),
    }.items():
        _add_v35_material_breakup(
            materials[key], scale=profile[0], dark_factor=profile[1],
            light_factor=profile[2], bump_strength=profile[3],
            bump_distance=profile[4], roughness_min=profile[5],
            roughness_max=profile[6],
        )

    # High-bay diffusers should glow, but not clip every white surface in a
    # close-up. Keep instrument indicators brighter than the fixtures.
    _set_emission_strength(materials["luminaire"], 1.35)
    _set_emission_strength(materials["display_text"], 2.10)
    _set_emission_strength(materials["pilot_green"], 2.20)
    _set_emission_strength(materials["pilot_red"], 2.20)
    _set_emission_strength(materials["sensor"], 1.40)

    bounds = _bounds(scene_data)
    _add_factory_shell(bpy, bounds, materials)
    _add_vertical_vessel(bpy, materials)
    _add_heat_exchanger(bpy, materials)
    _add_background_filter_skid(bpy, materials)
    _add_pipe_rack_and_crane(bpy, bounds, materials)
    _add_pipe_rack_detail(bpy, bounds, materials)
    _add_utility_layers(bpy, scene_data, bounds, materials)
    _add_wall_and_safety_facilities(bpy, bounds, materials)
    _add_factory_service_details(bpy, bounds, materials)
    _add_weathering_and_field_evidence(bpy, bounds, materials)
    _add_equipment(bpy, scene_data, materials)
    _add_v18_asset_microdetails(bpy, scene_data, materials)
    _add_v19_factory_detail_layer(bpy, scene_data, bounds, materials)
    _add_v20_field_realism_layer(bpy, scene_data, bounds, materials)
    _add_v21_realism_layer(bpy, scene_data, bounds, materials)
    _add_v22_industrial_completion_layer(bpy, scene_data, bounds, materials)
    _add_v23_high_granularity_layer(bpy, scene_data, bounds, materials)
    _add_v24_operational_finish(bpy, scene_data, bounds, materials)
    _add_v25_mcc_detail_layer(bpy, scene_data, bounds, materials)
    _add_v26_mcc_realism_layer(bpy, scene_data, bounds, materials)
    _add_v27_global_presentation_layer(bpy, scene_data, bounds, materials)
    _add_v28_micro_geometry_layer(bpy, scene_data, bounds, materials)
    _add_v35_deep_realism_layer(bpy, scene_data, bounds, materials)
    _add_plant_instrumentation(bpy, scene_data, materials)
    _add_access_platforms_and_stairs(bpy, scene_data, materials)
    _add_route(bpy, scene_data, materials)
    _set_navigation_overlay_render_visibility(
        bpy, render_overlays=render_navigation_overlays,
    )
    root = bpy.data.objects.new("VirtualInspectionRobot", None)
    bpy.context.collection.objects.link(root)
    _add_robot(bpy, root, materials)
    _animate_robot(root, scene_data.get("trajectory", []))
    _add_lighting(bpy, bounds, hdri_path)
    cameras = _add_cameras(bpy, scene_data, bounds, orbit_count)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(1, len(scene_data.get("trajectory", [])))
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        try:
            scene.view_settings.look = "AgX - Very High Contrast"
        except TypeError:
            pass
    scene.view_settings.exposure = -0.22 if quality == "ultra" else -0.34
    scene.view_settings.gamma = 1.0
    render_settings, rendered_cameras = _render(
        bpy, scene, output_dir, resolution, cameras, quality,
    )
    _render_synchronized_streams(
        bpy, scene, output_dir, scene_data.get("trajectory", []),
        quality=quality, frame_count=stream_frames,
        stream_resolution=stream_resolution,
    )

    # Keep the saved project and exported GLB at a deterministic opening pose;
    # rendered stills may have advanced the animated robot to a later frame.
    scene.frame_set(1)
    scene.camera = cameras.get("factory_overview.png", scene.camera)
    blend_path = output_dir / "factory_scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    glb_path = output_dir / "factory_scene.glb"
    if not skip_glb_export:
        try:
            flattened_materials = _prepare_glb_export_materials(bpy)
            merged_objects = _join_static_meshes_for_glb(bpy)
            print(
                f"Prepared {flattened_materials} PBR materials and merged "
                f"{merged_objects} static objects for portable GLB export"
            )
            bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", export_apply=True)
        except Exception as exc:
            print(f"GLB export unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
            glb_path.unlink(missing_ok=True)
    _write_scene_manifest(
        output_dir, scene_data, cameras, bounds,
        quality=quality,
        resolution=resolution,
        render_settings=render_settings,
        navigation_overlays_rendered=render_navigation_overlays,
        rendered_cameras=rendered_cameras,
        hdri_path=hdri_path,
    )


def main() -> int:
    args = _arguments()
    try:
        import bpy
    except ImportError as exc:
        print("This script must be launched by Blender's Python runtime.", file=sys.stderr)
        raise SystemExit(2) from exc
    scene = json.loads(args.scene_input.read_text(encoding="utf-8"))
    _add_scene(
        bpy, scene, args.output_dir, args.resolution, args.orbit_cameras,
        tuple(args.camera_filter), quality=args.quality, hdri_path=args.hdri,
        render_navigation_overlays=args.render_navigation_overlays,
        skip_glb_export=args.skip_glb_export,
        stream_frames=args.stream_frames,
        stream_resolution=args.stream_resolution,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
