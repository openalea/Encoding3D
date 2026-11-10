"""
The conformance files of encoding3d: small reference scenes covering the specification, each written as a GLB with its
expected values as JSON (openalea.encoding3d.dump). A reader in any language passes when what it reads from each GLB equals the
JSON; a writer passes when the validator accepts what it writes for the same scenes.

    python conformance/generate.py          (re)writes the files next to this script

The scenes are built from fixed numbers only, so the files are the same byte for byte on every run (a test checks
it); the archives (archives/*.fspm.zip) hold the same members once read, and are rewritten only when those change (a
compressor of another version may compress the same bytes otherwise).
"""
import io
import json
import os
import struct
import sys
import zipfile
import zlib

import numpy as np

from openalea.encoding3d import (DataStructure, DerivedField, EntitySet, Frame, Grid, InstanceSet, Mapping, Mesh, NO_ID,
                     Operator, Ragged, Relation, Table, Template, Variable, column_major, evaluate, part_bytes,
                     to_bytes, write_index)
from openalea.encoding3d.codec import _encode, _part_data
from openalea.encoding3d.glb import pack
from openalea.encoding3d.dump import frame_to_dict, part_to_dict
from openalea.encoding3d.parts import Parts, part_file

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
WRITER = {"platform": "encoding3d", "model": "conformance"}


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
                                   platform="encoding3d", model="toy root system")
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
                                   platform="encoding3d", model="toy shoot",
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
                                   platform="encoding3d", model="toy cell network",
                                   extras={"encoding3d": {"note": "extras are the writer's, kept by readers"}})
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
                         platform="encoding3d", model="toy soil")
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
                                   cells="Cell"), platform="encoding3d", model="toy adaptive soil")
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
                                   platform="encoding3d", model="RootArchitecture parameters")
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
        sibling_order=np.array([0, 1, 0, 0, 0, 0, 1], dtype=np.int64),
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
                                   platform="encoding3d", model="toy plant with per-class fields",
                                   labels={"Internode": "StemInternode", "Leaf": "Leaf", "Bud": "Meristem",
                                           "Root": "RootAxis", "Axis": "ShootAxis"})
    return Frame([data_structure], time=3., time_unit="d", step=72, writer=WRITER, vocabulary_version="0.2")


def growing_sequence() -> list:
    """Three frames of a growing root system: segments are added, ids never reused."""
    return [root_system(n_segments=n, time=day, step=24 * int(day)) for n, day in ((3, 0.), (5, 1.), (8, 2.))]


def section_template(sides: int) -> Template:
    """A cross-section of *sides* cells, each a triangle from the centre to the unit polygon (z = 0, the section's
    plane): the entity set Cell (label, area), one mesh."""
    angles = 2 * np.pi * np.arange(sides + 1) / sides
    ring = np.round(np.c_[np.cos(angles), np.sin(angles), np.zeros(sides + 1)], 12)
    positions = np.concatenate([[[0., 0., 0.], ring[k], ring[k + 1]] for k in range(sides)])
    labels = np.array(["epidermis" if k % 2 == 0 else "cortex" for k in range(sides)], dtype=object)
    cells = EntitySet("Cell", columns=dict(id=np.arange(sides, dtype=np.int64), label=labels,
                                           area=np.full(sides, 0.5 * np.sin(2 * np.pi / sides))),
                      variables=_declare(area=dict(unit="m2", kind="extensive", description="area in the unit section")))
    return Template(entity_sets=[cells], meshes=[Mesh("section", positions=positions,
                                                      feature_rows={"Cell": np.repeat(np.arange(sides), 3)})])


SQUARE, HEXAGON = section_template(4), section_template(6)
# The operators of the sections' water potential (Cell rows) from the potentials at the segment's two ends: a dense
# interpolation, a sparse copy, and a sparse system solved when evaluated (S^-1 R)
INTERPOLATION = Operator.dense(np.array([[1., 0.], [0.75, 0.25], [0.5, 0.5], [0.25, 0.75]]))
ALTERNATE = Operator.sparse(np.array([[1., 0.], [0., 1.], [1., 0.], [0., 1.]]))
_RING = 2. * np.eye(6) - 0.5 * (np.eye(6, k=1) + np.eye(6, k=-1))
DIFFUSION = Operator.solve(_RING, np.array([[0.5, 0.5], [1., 0.], [0.5, 0.5], [0., 1.], [0.5, 0.5], [0.25, 0.75]]))


def _placement(start, end, radius) -> np.ndarray:
    """The 4×4 placing a unit section at the middle of a segment from *start* to *end*, across it, scaled by
    *radius*."""
    axis = (np.asarray(end, dtype=float) - np.asarray(start, dtype=float))
    axis /= np.linalg.norm(axis)
    helper = np.array([1., 0., 0.]) if abs(axis[0]) < 0.9 else np.array([0., 1., 0.])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    matrix = np.eye(4)
    matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = radius * u, radius * v, radius * axis
    matrix[:3, 3] = 0.5 * (np.asarray(start) + np.asarray(end))
    return np.round(matrix, 12)


def instanced_roots(n_sections: int, time: float, step: int) -> Frame:
    """A root system whose first *n_sections* segments are drawn by sections, instances of two templates: an
    instance set "sections" (owner: the segment), its own variable age, the vectors "ends" (the potentials at the
    segment's two ends) and "sources" (an offset on the cells, or none), the derived field water_potential on the
    templates' Cell rows: one term (dense, or solved), or two weighted terms (an interpolation between two operators)
    with an offset."""
    frame = root_system(n_segments=4, time=time, step=step)
    data_structure = frame.data_structures[0]
    segments = data_structure.entity_set("SubOrgan")
    rows = np.arange(n_sections)
    columns = segments.columns
    placements = [_placement((columns["x1"][row], columns["y1"][row], columns["z1"][row]),
                             (columns["x2"][row], columns["y2"][row], columns["z2"][row]), columns["radius"][row])
                  for row in rows]
    parts = [SQUARE, HEXAGON, INTERPOLATION, ALTERNATE, DIFFUSION]
    templates = np.array([0, 0, 1, 1][:n_sections], dtype=np.int64)
    operators = np.array([[2, NO_ID], [2, 3], [4, NO_ID], [4, NO_ID]][:n_sections], dtype=np.int64)
    weights = np.array([[1., 0.], [0.25, 0.75], [1., 0.], [1., 0.]][:n_sections])
    potential = columns["water_potential"]
    ends = [[potential[row], potential[row] - 0.005] for row in rows]
    sources = [[], [], [0.01, 0., -0.01, 0., 0.01, 0.], []][:n_sections]
    sections = InstanceSet("sections", owners="SubOrgan", parts=parts, columns=dict(
        id=np.arange(500, 500 + n_sections, dtype=np.int64), owner=columns["id"][rows], template=templates,
        transform=column_major(placements), age=time - 0.5 * rows),
        variables=_declare(age=dict(unit="d", kind="intensive", description="the section's age")),
        vectors={"ends": Ragged.of(ends), "sources": Ragged.of(sources)},
        derived=[DerivedField("water_potential", entity_set="Cell", input="ends", operators=operators, weights=weights,
                              offsets=("sources", None),
                              variable=Variable(unit="MPa", standard_name="water_potential", kind="intensive",
                                                role="derived", description="the cells' water potential"))])
    data_structure.instance_sets = [sections]
    return frame


def instances_files() -> dict:
    """The instances case (specification §12): a sequence of two frames whose sections are instances, its parts
    (parts/<key>.glb, each with its expected values), the values the derived field evaluates to, and the last frame
    with its parts embedded."""
    out, entries, keys = {}, [], set()
    frames = [instanced_roots(3, 0., 0), instanced_roots(4, 1., 24)]
    for number, frame in enumerate(frames):
        file_name = f"frame_{number:06d}.glb"
        document, buffers, used = _encode(frame)
        data = pack(document, buffers)
        keys |= set(used)
        out[f"instances/{file_name}"] = data
        out[f"instances/frame_{number:06d}.expected.json"] = _json(frame_to_dict(frame))
        frame.parts = Parts({key: _part_data(part) for key, part in used.items()})
        out[f"instances/frame_{number:06d}.evaluated.json"] = _json(_evaluated(frame))
        entries.append({"time": frame.time, "step": frame.step, "file": file_name})
    for part in (SQUARE, HEXAGON, INTERPOLATION, ALTERNATE, DIFFUSION):
        out[f"instances/{part_file(part.key)}"] = part_bytes(part)
        out[f"instances/expected/{part.key}.json"] = _json(part_to_dict(part))
    out["instances/scene.fspm.json"] = _index(entries, parts=sorted(keys))
    out["instances/embedded.glb"] = to_bytes(frames[-1], embed_parts=True)
    return out


def _evaluated(frame) -> dict:
    """{derived field: one list of values per instance} of a frame's instance sets: what evaluate gives."""
    from openalea.encoding3d.dump import _column
    return {f"{data_structure.id}/{instance_set.name}/{derived.name}":
            [_column(values) for values in evaluate(frame, derived.name, data_structure=data_structure.id,
                                                    instance_set=instance_set.name)]
            for data_structure in frame.data_structures for instance_set in data_structure.instance_sets
            for derived in instance_set.derived}


ARCHIVE_COMPRESSIONS = {"stored": zipfile.ZIP_STORED, "deflate": zipfile.ZIP_DEFLATED, "lzma": zipfile.ZIP_LZMA}
_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def archives_files(instances: dict) -> dict:
    """The instances sequence packed into .fspm.zip archives (specification §8.2): one per compression (ZIP's methods
    stored, deflate and lzma), and one written with every ZIP64 record (stored), as a sequence of any size would be:
    archives/instances_<compression>.fspm.zip and archives/instances_zip64.fspm.zip. Their members are the sequence's
    files, unchanged: the index, the frames, the parts."""
    prefix = "instances/"
    members = ["scene.fspm.json"] + sorted(name[len(prefix):] for name in instances
                                           if name.startswith(prefix + "frame_") and name.endswith(".glb")) \
        + sorted(name[len(prefix):] for name in instances if name.startswith(prefix + "parts/"))
    contents = [(member, instances[prefix + member]) for member in members]
    out = {f"archives/instances_{name}.fspm.zip": _zip(contents, method)
           for name, method in ARCHIVE_COMPRESSIONS.items()}
    out["archives/instances_zip64.fspm.zip"] = _zip64(contents)
    return out


def _zip(contents: list, method: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", allowZip64=True) as archive:
        for member, data in contents:
            archive.writestr(zipfile.ZipInfo(member, date_time=_ZIP_DATE_TIME), data, compress_type=method)
    return buffer.getvalue()


def _zip64(contents: list) -> bytes:
    """A ZIP archive of stored members whose every size and offset is in ZIP64 records (the local and central headers'
    ZIP64 extra fields, the ZIP64 end of central directory and its locator), as a writer of a sequence over 4 GB or
    65,535 members writes them."""
    version, date, full = 45, 0x0021, 0xFFFFFFFF                  # ZIP64's version; 1980-01-01; "in the ZIP64 field"
    local, central = bytearray(), bytearray()
    for member, data in contents:
        name = member.encode("ascii")
        crc = zlib.crc32(data)
        offset = len(local)
        local += struct.pack("<IHHHHHIIIHH", 0x04034B50, version, 0, 0, 0, date, crc, full, full, len(name), 20)
        local += name + struct.pack("<HHQQ", 0x0001, 16, len(data), len(data)) + data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, version, version, 0, 0, 0, date, crc, full, full,
                               len(name), 28, 0, 0, 0, 0, full)
        central += name + struct.pack("<HHQQQ", 0x0001, 24, len(data), len(data), offset)
    end = len(local) + len(central)
    record = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, version, version, 0, 0, len(contents), len(contents),
                         len(central), len(local))
    locator = struct.pack("<IIQI", 0x07064B50, 0, end, 1)
    final = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, full, full, 0)
    return bytes(local + central + record + locator + final)


def same_archive(path: str, data: bytes) -> bool:
    """Whether the archive at *path* holds the members of *data*, with the same methods and bytes once read: a
    compressor of another version may compress the same bytes otherwise, so an archive is rewritten only when what it
    holds changes."""
    if not os.path.exists(path):
        return False
    with zipfile.ZipFile(path) as existing, zipfile.ZipFile(io.BytesIO(data)) as written:
        if [(info.filename, info.compress_type) for info in existing.infolist()] != \
                [(info.filename, info.compress_type) for info in written.infolist()]:
            return False
        return all(existing.read(name) == written.read(name) for name in written.namelist())


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
    instances = instances_files()
    out.update(instances)
    out.update(archives_files(instances))
    return out


def _json(value) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _index(entries, parts=()) -> bytes:
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "scene.fspm.json")
        write_index(path, entries, time_unit="d", parts=parts)
        with open(path, "rb") as file:
            return file.read()


def main() -> int:
    for relative, data in files().items():
        path = os.path.join(DIRECTORY, relative)
        if relative.endswith(".fspm.zip") and same_archive(path, data):
            print(relative, "unchanged")
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(data)
        print(relative, len(data), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
