"""
The reader inside ParaView: loads the plugin, opens conformance files and a sequence, checks their blocks, arrays and
time steps, and renders a picture of each; then a frame with views (one block per layer, the configurations'
drop-down) and the macros applying and saving them.

    pvpython paraview/check_in_paraview.py conformance [output folder]
"""
import os
import sys

from paraview import simple

HERE = os.path.dirname(os.path.abspath(__file__))
conformance = sys.argv[1]
output = sys.argv[2] if len(sys.argv) > 2 else None

simple.LoadPlugin(os.path.join(HERE, "fspm_tf_reader.py"), ns=globals())


def arrays(source) -> set:
    information = source.GetDataInformation().DataInformation
    names = set()
    for association in (0, 1):                          # points, cells
        field = source.GetDataInformation().GetPointDataInformation() if association == 0 \
            else source.GetDataInformation().GetCellDataInformation()
        for number in range(field.GetNumberOfArrays()):
            names.add(field.GetArrayInformation(number).GetName())
    del information
    return names


def picture(source, name, colour_by, side=False):
    if output is None:
        return
    os.makedirs(output, exist_ok=True)
    view = simple.CreateView("RenderView")
    view.ViewSize = [800, 600]
    display = simple.Show(source, view)
    simple.ColorBy(display, ("CELLS", colour_by))
    display.RescaleTransferFunctionToDataRange(True)
    if side:                                            # seen from the side: z up
        view.CameraPosition, view.CameraFocalPoint, view.CameraViewUp = [0., -1., 0.], [0., 0., 0.], [0., 0., 1.]
    view.ResetCamera()
    simple.SaveScreenshot(os.path.join(output, f"{name}.png"), view)
    simple.Delete(view)


roots = fspmTFreader(FileName=os.path.join(conformance, "soil_and_roots.glb"))  # noqa: F821
roots.UpdatePipeline()
found = arrays(roots)
for name in ("SubOrgan.water_potential", "Axis.branching_order", "Voxel.soil_water_potential"):
    assert name in found, (name, sorted(found))
roots_only = fspmTFreader(FileName=os.path.join(conformance, "root_system.glb"))  # noqa: F821
picture(roots_only, "root_system", "SubOrgan.water_potential", side=True)

shoot = fspmTFreader(FileName=os.path.join(conformance, "wheat_shoot.glb"))  # noqa: F821
shoot.UpdatePipeline()
assert "SubOrgan.PARa" in arrays(shoot)
picture(shoot, "wheat_shoot", "SubOrgan.PARa")

sequence = fspmTFreader(FileName=os.path.join(conformance, "growing_sequence", "scene.fspm.json"))  # noqa: F821
sequence.UpdatePipelineInformation()
assert list(sequence.TimestepValues) == [0., 1., 2.], list(sequence.TimestepValues)
cells = []
for time in sequence.TimestepValues:
    sequence.UpdatePipeline(time)
    cells.append(sequence.GetDataInformation().GetNumberOfCells())
assert cells[0] < cells[1] < cells[2], cells                # the root system grows
print("cells per time step", cells)

# Without the plugin: ParaView's own glTF reader shows the geometry and the display copies (float32 point data)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bindings", "python", "src"))
import tempfile  # noqa: E402

from openalea import fspm_tf  # noqa: E402
from openalea.fspm_tf.display import add_display  # noqa: E402

with tempfile.TemporaryDirectory() as directory:
    copied = os.path.join(directory, "roots_display.glb")
    fspm_tf.write(copied, add_display(fspm_tf.read(os.path.join(conformance, "root_system.glb")), ["water_potential"]))
    plain = simple.glTFReader(FileName=copied)          # ParaView's own reader, not the plugin
    plain.UpdatePipeline()
    names = set()
    point_data = plain.GetDataInformation().GetPointDataInformation()
    for number in range(point_data.GetNumberOfArrays()):
        names.add(point_data.GetArrayInformation(number).GetName())
    print("glTF reader", type(plain).__name__, "point data", sorted(names))
    assert any("WATER_POTENTIAL" in name for name in names), sorted(names)

# Views: a views.json next to the frame gives one block per layer; the macros make and save the layers' items
import runpy  # noqa: E402
import shutil  # noqa: E402

from openalea.fspm_tf import views  # noqa: E402

with tempfile.TemporaryDirectory() as directory:
    shutil.copy(os.path.join(conformance, "root_system.glb"), directory)
    layers = [{"name": "roots",
               "source": {"data_structure": "root_system", "kind": "segments", "entity_set": "SubOrgan"},
               "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}, "tube": {"radius": "radius"}},
              {"name": "mesh", "source": {"data_structure": "root_system", "kind": "mesh", "mesh": "roots"},
               "color_by": None, "opacity": 0.3, "visible": False}]
    path = os.path.join(directory, views.VIEWS_FILE)
    views.write_views(path, {"fspm_tf_views": 1, "active": "default",
                             "configurations": {"default": {"layers": layers}, "mesh only": {"layers": layers[1:]}}})
    viewed = fspmTFreader(FileName=os.path.join(directory, "root_system.glb"))  # noqa: F821
    viewed.UpdatePropertyInformation()
    assert list(viewed.ConfigurationNames) == ["default", "mesh only"], list(viewed.ConfigurationNames)
    viewed.UpdatePipeline()
    assert viewed.GetDataInformation().DataInformation.GetNumberOfLeaves() == 2
    simple.SetActiveSource(viewed)
    runpy.run_path(os.path.join(HERE, "apply_fspm_tf_views.py"))
    tube = simple.FindSource("roots")
    assert tube is not None and simple.FindSource("mesh") is not None
    simple.GetDisplayProperties(tube).Opacity = 0.5
    simple.SetActiveSource(viewed)
    runpy.run_path(os.path.join(HERE, "save_fspm_tf_views.py"))
    assert views.read_views(path)["configurations"]["default"]["layers"][0]["opacity"] == 0.5
    picture(tube, "root_system_views", "SubOrgan.water_potential", side=True)
    viewed.Configuration = "mesh only"
    viewed.UpdatePipeline()
    assert viewed.GetDataInformation().DataInformation.GetNumberOfLeaves() == 1
print("fspm-TF reader: ok")
