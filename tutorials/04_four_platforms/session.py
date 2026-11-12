"""
Tutorial 4: the session. encoding3d's coordinator launches the four platforms' models, each in its own process, and
runs ten daily steps: CPlantBox grows the roots, then GroIMP the shoot, then metafspm (root water uptake) and
VirtualPlantLab (light and photosynthesis) compute together. The shared plant is recorded at each step in
outputs/record (an encoding3d sequence).

    python session.py CPLANTBOX JAVA_CLASSPATH JULIA METAFSPM_PYTHON
"""
import os
import sys

from openalea.encoding3d import read_index, read
from openalea.encoding3d.coupling import Coordinator, Link
from openalea.encoding3d.views import VIEWS_FILE, check_views, write_views

here = os.path.dirname(os.path.abspath(__file__))
cplantbox, classpath, julia, python = sys.argv[1:5]

coordinator = Coordinator(
    "tcp://127.0.0.1:*", steps=10, interval=1., time_unit="d", timeout=600,
    stages=[["cplantbox"], ["groimp"], ["metafspm", "virtualplantlab"]],
    links=[Link("metafspm", "plant_assimilation", "virtualplantlab", "plant_assimilation", aggregation="copy"),
           Link("groimp", "water_uptake", "metafspm", "water_uptake", aggregation="sum")],
    record=os.path.join(here, "outputs", "record"))
coordinator.launch("cplantbox", [cplantbox])
coordinator.launch("groimp", ["java", "-cp", classpath, "tutorial.Shoot"])
coordinator.launch("virtualplantlab", [julia, f"--project={os.path.join(here, 'virtualplantlab')}",
                                       os.path.join(here, "virtualplantlab", "light.jl")])
coordinator.launch("metafspm", [python, os.path.join(here, "metafspm", "uptake.py")])
store = coordinator.run()
for coupling in coordinator.couplings:
    source = f"{coupling.provider}.{coupling.source.name}" if coupling.source else "-"
    print(f"  {coupling.receiver}.{coupling.variable.name} <- {source} ({coupling.how}"
          f"{', ' + coupling.aggregation if coupling.aggregation else ''}, factor {coupling.factor:g})")
# how to look at the record: the roots (CPlantBox's segments) as tubes, coloured by metafspm's uptake
record = os.path.join(here, "outputs", "record")
views = {"encoding3d_views": 1, "active": "uptake", "configurations": {"uptake": {"layers": [
    {"name": "roots", "source": {"data_structure": "plant", "kind": "segments", "entity_set": "SubOrgan"},
     "color_by": {"entity_set": "SubOrgan", "variable": "water_uptake"}, "colormap": "Viridis (matplotlib)",
     "tube": {"radius": "radius", "scale": 1}}]}}}
write_views(os.path.join(record, VIEWS_FILE), views)
last = read(read_index(os.path.join(record, "scene.fspm.json"))["frames"][-1]["path"])
print(check_views(views, last))
print("recorded in", record)
