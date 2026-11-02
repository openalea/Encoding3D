"""
The conformance files of fspm-TF: small reference scenes covering the specification, each written as a GLB with its
expected values as JSON (openalea.fspm_tf.dump). A reader in any language passes when what it reads from each GLB equals the
JSON; a writer passes when the validator accepts what it writes for the same scenes.

    python conformance/generate.py          (re)writes the files next to this script

The scenes are built from fixed numbers only, so the files are the same byte for byte on every run (a test checks
it).
"""
import json
import os
import sys

import numpy as np

from openalea.fspm_tf import (DataStructure, EntitySet, Frame, Grid, Mapping, Mesh, NO_ID, Relation, Table, Variable,
                     to_bytes, write_index)
from openalea.fspm_tf.dump import frame_to_dict

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
WRITER = {"platform": "fspm-tf", "model": "conformance"}


def _segment_triangles(start, end, radius, sides: int = 6):
    """The lateral triangles of a cylinder from *start* to *end*: (2 * sides * 3, 3) vertices."""
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    axis = end - start
    helper = np.array([1., 0., 0.]) if abs(axis[0]) < 0.9 * np.linalg.norm(axis) else np.array([0., 1., 0.])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis / np.linalg.norm(axis), u)
    angles = np.arange(sides) * 2 * np.pi / sides
    ring = radius * (np.cos(angles)[:, None] * u + np.sin(angles)[:, None] * v)
    vertices = []
    for k in range(sides):
        a0, a1 = start + ring[k], start + ring[(k + 1) % sides]
        b0, b1 = end + ring[k], end + ring[(k + 1) % sides]
        vertices += [a0, b0, a1, a1, b0, b1]
    return np.array(vertices)


def _declare(**declarations):
    return {name: Variable(**declaration) for name, declaration in declarations.items()}


SEGMENT_VARIABLES = dict(
    length=dict(unit="m", standard_name="length", kind="extensive", description="length of the segment"),
    radius=dict(unit="m", standard_name="radius", kind="intensive"),
    x1=dict(unit="m", standard_name="proximal_end_x", kind="descriptor"),
    y1=dict(unit="m", standard_name="proximal_end_y", kind="descriptor"),
    z1=dict(unit="m", standard_name="proximal_end_z", kind="descriptor"),
    x2=dict(unit="m", standard_name="distal_end_x", kind="descriptor"),
    y2=dict(unit="m", standard_name="distal_end_y", kind="descriptor"),
    z2=dict(unit="m", standard_name="distal_end_z", kind="descriptor"),
    struct_mass=dict(unit="g", standard_name="structural_mass", kind="extensive"),
    water_potential=dict(unit="MPa", standard_name="water_potential", kind="intensive"),
    emerged=dict(unit="1", kind="descriptor", role="derived", description="the segment has emerged"),
)


def root_system(n_segments: int = 6, lateral_from: int = 2, ids_from: int = 10, time: float = 0., step: int = 0,
                plant_id: str = "root_system", origin=(0., 0., 0.)) -> Frame:
    """A tap root of *n_segments* segments and an apex, with a lateral root of 2 segments and an apex branching on
    segment *lateral_from*: scales Plant, Axis, SubOrgan; the MTG relations; segment variables; a mesh."""
    main = n_segments + 1
    ids = np.concatenate([np.arange(ids_from, ids_from + main),                 # the lateral's ids stay the same
                          np.arange(ids_from + 50, ids_from + 53)]).astype(np.int64)  # as the tap root grows
    axis_of = np.array([0] * main + [1] * 3)
    parent = np.concatenate([[NO_ID], ids[:main - 1], [ids[lateral_from], ids[main], ids[main + 1]]])
    edge_type = np.array(["none"] + ["successor"] * (main - 1) + ["branch", "successor", "successor"], dtype=object)
    label = np.array(["RootSegment"] * (main - 1) + ["RootApex"] + ["RootSegment"] * 2 + ["RootApex"], dtype=object)
    length = np.concatenate([np.full(main - 1, 0.01), [0.002], [0.008, 0.006], [0.002]])
    radius = np.concatenate([np.full(main, 4e-4), np.full(3, 2e-4)])
    starts, ends = np.zeros((ids.size, 3)), np.zeros((ids.size, 3))
    for row in range(ids.size):
        if parent[row] == NO_ID:
            starts[row] = origin
        else:
            starts[row] = ends[int(np.flatnonzero(ids == parent[row])[0])]
        direction = np.array([0., 0., -1.]) if axis_of[row] == 0 else np.array([0.6, 0., -0.8])
        ends[row] = starts[row] + length[row] * direction
    segments = EntitySet("SubOrgan", rank=6, columns=dict(
        id=ids, label=label, complex=np.array([100, 101])[axis_of], parent=parent, edge_type=edge_type,
        length=length, radius=radius, x1=starts[:, 0], y1=starts[:, 1], z1=starts[:, 2], x2=ends[:, 0],
        y2=ends[:, 1], z2=ends[:, 2], struct_mass=length * np.pi * radius ** 2 * 1e5,
        water_potential=-0.1 - 0.01 * np.arange(ids.size), emerged=label != "RootApex"),
        variables=_declare(**SEGMENT_VARIABLES))
    axes = EntitySet("Axis", rank=2, columns=dict(
        id=np.array([100, 101], dtype=np.int64), label=np.array(["RootAxis", "RootAxis"], dtype=object),
        complex=np.array([1000, 1000], dtype=np.int64), parent=np.array([NO_ID, 100], dtype=np.int64),
        edge_type=np.array(["none", "branch"], dtype=object), branching_order=np.array([1, 2], dtype=np.int64)),
        variables=_declare(branching_order=dict(unit="1", standard_name="branching_order", kind="descriptor")))
    plants = EntitySet("Plant", rank=1, columns=dict(
        id=np.array([1000], dtype=np.int64), label=np.array(["Wheat"], dtype=object),
        total_struct_mass=np.array([segments.columns["struct_mass"].sum()])),
        variables=_declare(total_struct_mass=dict(unit="g", standard_name="structural_mass", kind="extensive")))
    vertices, rows = [], []
    for row in range(ids.size):
        if label[row] == "RootApex":
            continue                                    # apices drawn by no triangle: scales may lack geometry
        triangles = _segment_triangles(starts[row], ends[row], radius[row])
        vertices.append(triangles)
        rows.append(np.full(len(triangles), row))
    rows = np.concatenate(rows)
    mesh = Mesh("roots", positions=np.concatenate(vertices),
                feature_rows={"SubOrgan": rows, "Axis": axis_of[rows], "Plant": np.zeros(rows.size)})
    data_structure = DataStructure(plant_id, kind="graph", entity_sets=[plants, axes, segments], meshes=[mesh],
                                   scalars=Table("scalars", columns=dict(time_step=[3600.]),
                                                 variables=_declare(time_step=dict(unit="s", role="setting"))),
                                   platform="fspm-tf", model="toy root system")
    return Frame([data_structure], time=time, time_unit="d", step=step, writer=WRITER, vocabulary_version="0.2")


def wheat_shoot() -> Frame:
    """A shoot: Plant, Axis, Organ (an internode, a sheath and a blade), SubOrgan (the blade's 3 elements and the
    stem element), with a leaf mesh (one quad, two triangles, per element) and the light absorbed."""
    organs = EntitySet("Organ", rank=5, columns=dict(
        id=np.array([20, 21, 22], dtype=np.int64),
        label=np.array(["StemInternode", "Sheath", "Blade"], dtype=object),
        complex=np.full(3, 10, dtype=np.int64), parent=np.array([NO_ID, 20, 21], dtype=np.int64),
        edge_type=np.array(["none", "branch", "successor"], dtype=object),
        length=np.array([0.02, 0.05, 0.15])),
        variables=_declare(length=dict(unit="m", standard_name="length", kind="extensive")))
    element_ids = np.array([30, 31, 32, 33], dtype=np.int64)
    elements = EntitySet("SubOrgan", rank=6, columns=dict(
        id=element_ids, label=np.array(["StemElement", "LeafElement", "LeafElement", "LeafElement"], dtype=object),
        complex=np.array([20, 22, 22, 22], dtype=np.int64), parent=np.array([NO_ID, NO_ID, 31, 32], dtype=np.int64),
        edge_type=np.array(["none", "none", "successor", "successor"], dtype=object),
        area=np.array([0., 1.5e-4, 1.4e-4, 0.9e-4]), green_area=np.array([0., 1.5e-4, 1.4e-4, 0.5e-4]),
        PARa=np.array([np.nan, 812.5, 640.25, 301.0]), inclination=np.array([0., 35., 50., 70.])),
        variables=_declare(
            area=dict(unit="m2", standard_name="surface_area", kind="extensive"),
            green_area=dict(unit="m2", standard_name="green_area", kind="extensive"),
            PARa=dict(unit="umol/(m2.s)", standard_name="absorbed_par_photon_flux_density", kind="intensive",
                      role="input", description="absorbed PAR (NaN: an element without a surface to light)"),
            inclination=dict(unit="deg", standard_name="inclination", kind="descriptor")))
    axes = EntitySet("Axis", rank=2, columns=dict(id=np.array([10], dtype=np.int64),
                                                   label=np.array(["ShootAxis"], dtype=object),
                                                   complex=np.array([1], dtype=np.int64)))
    plants = EntitySet("Plant", rank=1, columns=dict(id=np.array([1], dtype=np.int64),
                                                      label=np.array(["Wheat"], dtype=object)))
    quads, rows = [], []
    for element in (1, 2, 3):
        x0, x1 = 0.05 * (element - 1), 0.05 * element
        width = 0.01 - 0.002 * element
        a, b = [x0, -width / 2, 0.1 + x0 / 2], [x1, -width / 2, 0.1 + x1 / 2]
        c, d = [x1, width / 2, 0.1 + x1 / 2], [x0, width / 2, 0.1 + x0 / 2]
        quads += [a, b, c, a, c, d]
        rows += [element] * 6
    rows = np.array(rows)
    organ_rows = np.full(rows.size, 2)
    mesh = Mesh("leaves", positions=quads, feature_rows={"SubOrgan": rows, "Organ": organ_rows})
    data_structure = DataStructure("shoot", entity_sets=[plants, axes, organs, elements], meshes=[mesh],
                                   platform="fspm-tf", model="toy shoot",
                                   origin=np.array([[1., 0., 0., 0.5], [0., 1., 0., 0.25], [0., 0., 1., 0.],
                                                    [0., 0., 0., 1.]]))
    return Frame([data_structure], time=12.5, step=300, writer=WRITER, vocabulary_version="0.2")


def section_cells() -> Frame:
    """A root cross section as a cell network (MECHA-like): 4 cells (Compartment scale) and 5 connections (an edge
    table with ids, a relation label and a conductance), the cells drawn as squares; extras for the writer."""
    cells = EntitySet("Compartment", rank=9, columns=dict(
        id=np.arange(4, dtype=np.int64),
        label=np.array(["SymplasticNode", "SymplasticNode", "SymplasticNode", "ApoplasticNode"], dtype=object),
        layer=np.array(["Endodermis", "CorticalParenchyma", "CorticalParenchyma", "Epidermis"], dtype=object),
        cell_area=np.array([2.0e-10, 3.1e-10, 3.0e-10, 0.5e-10]),
        water_potential=np.array([-0.32e6, -0.30e6, -0.29e6, -0.25e6]),
        centre=np.array([[0., 0.], [1e-5, 0.], [0., 1e-5], [1e-5, 1e-5]])),
        variables=_declare(cell_area=dict(unit="m2", standard_name="cell_area", kind="extensive"),
                           water_potential=dict(unit="Pa", standard_name="water_potential", kind="intensive"),
                           centre=dict(unit="m", kind="descriptor", description="the cell's centre (x, y)"),
                           layer=dict(unit="1", kind="descriptor", description="the cell's tissue")))
    connections = Relation("Connection", source_set="Compartment", target_set="Compartment", columns=dict(
        id=np.arange(10, 15, dtype=np.int64), source=np.array([0, 1, 0, 1, 2], dtype=np.int64), target=np.array([1, 2, 2, 3, 3], dtype=np.int64),
        relation=np.array(["SymplasticEdge", "SymplasticEdge", "SymplasticEdge", "ApoplasticEdge",
                           "ApoplasticEdge"], dtype=object),
        conductance=np.array([1e-18, 2e-18, 1.5e-18, 4e-17, 3e-17])),
        variables=_declare(conductance=dict(unit="m3/(s.Pa)", standard_name="hydraulic_conductance",
                                            kind="intensive")))
    squares, rows = [], []
    for row, (x, y) in enumerate(cells.columns["centre"]):
        h = 4e-6
        a, b, c, d = [x - h, y - h, 0.], [x + h, y - h, 0.], [x + h, y + h, 0.], [x - h, y + h, 0.]
        squares += [a, b, c, a, c, d]
        rows += [row] * 6
    mesh = Mesh("cells", positions=squares, feature_rows={"Compartment": rows})
    data_structure = DataStructure("section", entity_sets=[cells], relations=[connections], meshes=[mesh],
                                   platform="fspm-tf", model="toy cell network",
                                   extras={"fspm-tf": {"note": "extras are the writer's, kept by readers"}})
    return Frame([data_structure], time=0., step=0, writer=WRITER, vocabulary_version="0.2")


def soil_and_roots() -> Frame:
    """A root system in a 2 × 2 × 3 regular soil grid (z pointing down, periodic in x and y), with the mapping of
    the segments to the voxels they lie in."""
    frame = root_system()
    roots = frame.data_structures[0]
    shape = (2, 2, 3)
    count = int(np.prod(shape))
    voxels = EntitySet("Voxel", columns=dict(
        soil_water_potential=-0.01e6 - 1e3 * np.arange(count, dtype=float),
        soil_temperature=np.round(285.15 - 0.5 * (np.arange(count) % 3), 6),
        water_content=np.full(count, 0.25)),
        variables=_declare(
            soil_water_potential=dict(unit="Pa", standard_name="soil_water_potential", kind="intensive"),
            soil_temperature=dict(unit="K", standard_name="soil_temperature", kind="intensive", role="input"),
            water_content=dict(unit="m3/m3", standard_name="soil_volumetric_water_content", kind="intensive")))
    soil = DataStructure("soil", kind="regular_grid", entity_sets=[voxels],
                         grid=Grid(kind="regular", shape=shape, origin=(-0.02, -0.02, 0.), spacing=(0.02, 0.02, 0.02),
                                   axes=("x", "y", "z"), periodic=(True, True, False), z_up=False, cells="Voxel"),
                         platform="fspm-tf", model="toy soil")
    segments = roots.entity_set("SubOrgan")
    middle_depth = -(segments.columns["z1"] + segments.columns["z2"]) / 2
    middle_x = (segments.columns["x1"] + segments.columns["x2"]) / 2
    layer = np.clip((middle_depth // 0.02).astype(int), 0, 2)
    column = np.clip(((middle_x + 0.02) // 0.02).astype(int), 0, 1)
    target = np.ravel_multi_index((column, np.ones_like(column), layer), shape).astype(np.int64)
    mapping = Mapping("roots_in_soil", source=("root_system", "SubOrgan"), target=("soil", "Voxel"),
                      method="barycentre", columns=dict(source=segments.columns["id"], target=target,
                                                        weight=np.ones(segments.count)))
    frame.data_structures.append(soil)
    frame.mappings.append(mapping)
    return frame


def adaptive_soil() -> Frame:
    """An adaptive grid: a 2 × 1 × 1 base refined once in its first cell (8 leaves at level 1) and the second cell
    left at level 0."""
    levels = np.array([1] * 8 + [0], dtype=np.int64)
    index = np.array([[i, j, k] for i in range(2) for j in range(2) for k in range(2)] + [[1, 0, 0]], dtype=np.int64)
    cells = EntitySet("Cell", columns=dict(
        id=np.arange(9, dtype=np.int64), level=levels, index=index,
        soil_water_potential=-0.02e6 + 100. * np.arange(9)),
        variables=_declare(soil_water_potential=dict(unit="Pa", standard_name="soil_water_potential",
                                                     kind="intensive")))
    soil = DataStructure("soil", kind="adaptive_grid", entity_sets=[cells],
                         grid=Grid(kind="adaptive", shape=(2, 1, 1), origin=(0., 0., 0.), spacing=(0.1, 0.1, 0.1),
                                   axes=("x", "y", "z"), periodic=(False, False, False), z_up=False, max_level=1,
                                   cells="Cell"), platform="fspm-tf", model="toy adaptive soil")
    return Frame([soil], time=0., step=0, writer=WRITER, vocabulary_version="0.2")


def parameter_set() -> Frame:
    """A parameter set: no geometry, scalars shared by every plant and one parameter value per plant (an infinite
    one among them)."""
    plants = EntitySet("Plant", rank=1, columns=dict(
        id=np.array([1, 2], dtype=np.int64), label=np.array(["Wheat", "Wheat"], dtype=object),
        EL=np.array([6.5e-4, 8.0e-4]), n_seminal_roots=np.array([5, 3], dtype=np.int64),
        offered_mass=np.array([np.inf, 2.5e-3])),
        variables=_declare(
            EL=dict(unit="m/(s.m)", role="parameter", kind="intensive", description="elongation rate per tip "
                    "diameter", references=("Pagès et al. 2014",), doi=("10.1093/aob/mct302",)),
            n_seminal_roots=dict(unit="1", role="parameter", kind="descriptor"),
            offered_mass=dict(unit="g/d", role="input", kind="extensive",
                              description="structural mass offered to the roots per day (inf: unlimited)")))
    scalars = Table("scalars", columns=dict(D_ini=[1.2e-3], T_ref=[293.15], method=np.array(["euler"], dtype=object)),
                    variables=_declare(D_ini=dict(unit="m", role="parameter", standard_name="radius",
                                                  kind="intensive", minimum=1e-4, maximum=5e-3,
                                                  description="initial tip diameter, as a radius"),
                                       T_ref=dict(unit="K", role="parameter", kind="intensive"),
                                       method=dict(unit="1", role="setting")))
    data_structure = DataStructure("archisimple_parameters", kind="table", entity_sets=[plants], scalars=scalars,
                                   platform="fspm-tf", model="RootArchitecture parameters")
    return Frame([data_structure], time=0., step=0, writer=WRITER, vocabulary_version="0.2")


def missing_values() -> Frame:
    """A plant as platforms with per-class fields write it (MTG.jl, PlantGraphs, GroIMP): integer, text, boolean and
    float columns with missing values, a date column, an edge type the writer does not know, the order of children,
    an entity set mixing base scales (a whole root axis among organs), the platform's labels mapped to the
    vocabulary's, a branch's first internode whose parent is in another axis, bearer relations between two pairs of
    sets."""
    plant = EntitySet("Plant", rank=1, scale="Plant", columns=dict(id=np.array([0], dtype=np.int64),
                                                                     label=np.array(["Wheat"], dtype=object)))
    axes = EntitySet("Axis", rank=2, scale="Axis", columns=dict(
        id=np.array([1, 2], dtype=np.int64), label=np.array(["Axis", "Axis"], dtype=object),
        complex=np.array([0, 0], dtype=np.int64), parent=np.array([-1, -1], dtype=np.int64),
        edge_type=np.array(["none", "none"], dtype=object)))
    organs = EntitySet("Organ", rank=5, scale="mixed", columns=dict(
        id=np.arange(10, 17, dtype=np.int64),
        label=np.array(["Internode", "Internode", "Leaf", "Leaf", "Internode", "Bud", "Root"], dtype=object),
        complex=np.array([1, 1, 1, 1, 2, 2, 0], dtype=np.int64),
        parent=np.array([-1, 10, 10, 11, 11, 14, -1], dtype=np.int64),
        edge_type=np.array(["none", "successor", "branch", "unknown", "branch", "successor", "none"], dtype=object),
        order=np.array([0, 1, 0, 0, 0, 0, 1], dtype=np.int64),
        length=np.array([0.12, 0.08, 0.2, 0.15, 0.05, np.nan, 0.3]),
        rank=np.ma.MaskedArray(np.array([1, 2, 1, 2, 1, 0, 0], dtype=np.int32),
                               mask=[False, False, False, False, False, True, True]),
        tissue=np.array(["stem", "stem", "blade", None, "stem", None, "root"], dtype=object),
        alive=np.ma.MaskedArray(np.array([True, True, True, False, True, False, False]),
                                mask=[False, False, False, False, False, True, False]),
        emergence=np.array(["2026-03-01", "2026-03-04", "2026-03-02", "2026-03-06", None, None, "2026-02-28"],
                           dtype=object)),
        variables=_declare(length=dict(unit="m", standard_name="length", kind="extensive"),
                           rank=dict(unit="1", kind="descriptor", description="the organ's rank on its axis"),
                           tissue=dict(unit="1", kind="descriptor"),
                           alive=dict(unit="1", kind="descriptor"),
                           emergence=dict(unit="1", kind="descriptor", format="date",
                                          description="the organ's emergence date")))
    bearer_axes = Relation("bearer_Axis_Organ", source_set="Axis", target_set="Organ", columns=dict(
        source=np.array([2], dtype=np.int64), target=np.array([11], dtype=np.int64),
        relation=np.array(["branch"], dtype=object)))
    bearer_buds = Relation("bearer_Organ_Axis", source_set="Organ", target_set="Axis", columns=dict(
        source=np.array([15], dtype=np.int64), target=np.array([1], dtype=np.int64),
        relation=np.array(["decomposition"], dtype=object)))
    data_structure = DataStructure("plant", entity_sets=[plant, axes, organs], relations=[bearer_axes, bearer_buds],
                                   platform="fspm-tf", model="toy plant with per-class fields",
                                   labels={"Internode": "StemInternode", "Leaf": "Leaf", "Bud": "Meristem",
                                           "Root": "RootAxis", "Axis": "ShootAxis"})
    return Frame([data_structure], time=3., time_unit="d", step=72, writer=WRITER, vocabulary_version="0.2")


def growing_sequence() -> list:
    """Three frames of a growing root system: segments are added, ids never reused."""
    return [root_system(n_segments=n, time=day, step=24 * int(day)) for n, day in ((3, 0.), (5, 1.), (8, 2.))]


SCENES = {"root_system": root_system, "wheat_shoot": wheat_shoot, "section_cells": section_cells,
          "soil_and_roots": soil_and_roots, "adaptive_soil": adaptive_soil, "parameter_set": parameter_set,
          "missing_values": missing_values}


def files() -> dict:
    """{relative path: bytes} of every conformance file."""
    out = {}
    for name, build in SCENES.items():
        frame = build()
        out[f"{name}.glb"] = to_bytes(frame)
        out[f"{name}.expected.json"] = _json(frame_to_dict(frame))
    entries = []
    for number, frame in enumerate(growing_sequence()):
        file_name = f"frame_{number:06d}.glb"
        out[f"growing_sequence/{file_name}"] = to_bytes(frame)
        out[f"growing_sequence/frame_{number:06d}.expected.json"] = _json(frame_to_dict(frame))
        entries.append({"time": frame.time, "step": frame.step, "file": file_name})
    out["growing_sequence/scene.fspm.json"] = _index(entries)
    return out


def _json(value) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _index(entries) -> bytes:
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "scene.fspm.json")
        write_index(path, entries, time_unit="d")
        with open(path, "rb") as file:
            return file.read()


def main() -> int:
    for relative, data in files().items():
        path = os.path.join(DIRECTORY, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(data)
        print(relative, len(data), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
