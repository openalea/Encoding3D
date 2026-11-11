"""
Tutorial 4, metafspm's side: root water uptake (functional, a toy). metafspm has no plant of its own here: it joins
the session and builds its data structure from the roots CPlantBox grows (RemoteComponent.join), then its component
computes each segment's uptake from its surface and the plant's carbon status (the more the leaves assimilate, the more
the roots take up), at each step.
"""
from dataclasses import dataclass

import numpy as np

from openalea.metafspm import actual, FunctionalComponent, input_variable, state_variable
from openalea.metafspm.data_structure.configs import ScalesConfig as scales
from openalea.metafspm.io.coupling import RemoteComponent

UNIT = dict(unit_comment="", value_comment="", references="", DOI=[], min_value=None, max_value=None)
CONDUCTANCE = 0.5                # cm3 of water per cm2 of root surface per day, at full carbon status (a toy)
HALF_ASSIMILATION = 5.           # umol/s of assimilation for half the full uptake


def segment(variable, unit, description, kind):
    return variable(unit=unit, description=description, default=0., scale=scales.SubOrgan, kind=kind, **UNIT)


@dataclass
class OtherPlatforms(RemoteComponent):
    """The other platforms' models, as seen from metafspm: CPlantBox's roots (followed: their segments' sizes) and
    VirtualPlantLab's photosynthesis (the plant's assimilation, copied to each segment); metafspm's uptake sent."""
    participant = "metafspm"
    rights = {"Plant": "follows", "Organ": "follows", "SubOrgan": "follows"}
    length: float = segment(state_variable, "cm", "the segment's length (CPlantBox's)", "extensive")
    radius: float = segment(state_variable, "cm", "the segment's radius (CPlantBox's)", "intensive")
    plant_assimilation: float = segment(state_variable, "umol/s", "the plant's assimilation (VirtualPlantLab's)",
                                        "extensive")
    water_uptake: float = segment(input_variable, "cm3/d", "the segment's water uptake (metafspm's)", "extensive")


@dataclass
class RootWaterUptake(FunctionalComponent):
    """Each segment takes up water through its surface, more when the plant has more carbon."""
    length: float = segment(input_variable, "cm", "the segment's length", "extensive")
    radius: float = segment(input_variable, "cm", "the segment's radius", "intensive")
    plant_assimilation: float = segment(input_variable, "umol/s", "the plant's assimilation", "extensive")
    water_uptake: float = segment(state_variable, "cm3/d", "the segment's water uptake", "extensive")

    @actual
    def _water_uptake(self, length, radius, plant_assimilation):
        carbon_status = plant_assimilation / (plant_assimilation + HALF_ASSIMILATION)
        return CONDUCTANCE * 2 * np.pi * radius * length * np.nan_to_num(carbon_status)


if __name__ == "__main__":
    data_structure = OtherPlatforms.join()           # the session's address from the coordinator, which launched it
    uptake = RootWaterUptake(data_structure=data_structure)
    others = OtherPlatforms(data_structure=data_structure)
    others.start()
    while others.stopped is None:
        uptake()
        print(f"metafspm: {data_structure.n_nodes()} segments, uptake {np.sum(data_structure.get('water_uptake')):.4f} "
              "cm3/d", flush=True)
        others()
    print(f"metafspm: the session ended ({others.stopped})")
