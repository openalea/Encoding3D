"""
A session's resolution: from the participants' declarations and the links, each input's provider (Coupling), the
stages, and the checks that make a session run (one provider per input, convertible units, one owner per entity
set, no two participants changing one entity set's topology in the same stage).
"""
from dataclasses import dataclass
from typing import Optional

from openalea.fspm_tf.coupling.messages import CouplingError, Declaration, Link, VariableSpec
from openalea.fspm_tf.ucum import UnitError, conversion_factor


@dataclass
class Coupling:
    """An input and its provider: *factor* converts the source's unit to the input's (times the link's factor);
    *aggregation* changes its scale (None: the same entity set); *how*: "link", "standard name" or "name"."""
    receiver: str
    variable: VariableSpec
    provider: Optional[str]
    source: Optional[VariableSpec]
    factor: float = 1.
    aggregation: Optional[str] = None
    interpolation: str = "hold"
    how: str = "link"
    mapping: Optional[str] = None
    reverse: bool = False                 # the mapping read from its target to its source

    def to_json(self) -> dict:
        value = {"variable": self.variable.name, "entitySet": self.variable.entity_set,
                 "dataStructure": self.variable.data_structure, "provider": self.provider, "how": self.how}
        if self.source is not None:
            value.update(source=self.source.name, sourceEntitySet=self.source.entity_set, factor=self.factor)
            if self.aggregation:
                value["aggregation"] = self.aggregation
            if self.interpolation != "hold":
                value["interpolation"] = self.interpolation
            if self.mapping:
                value["mapping"] = self.mapping
        return value


def ranks(declarations: dict) -> dict:
    """{(data structure, entity set): rank}, the same in every declaration that gives one."""
    found = {}
    for declaration in declarations.values():
        for entity_set in declaration.entity_sets:
            key = (entity_set.data_structure, entity_set.name)
            if entity_set.rank is None:
                continue
            if found.setdefault(key, entity_set.rank) != entity_set.rank:
                raise CouplingError(f"entity set {key[0]}/{key[1]}: ranks {found[key]} and {entity_set.rank} declared")
    return found


def resolve(declarations: dict, links=()) -> list:
    """The couplings of every input of *declarations* ({participant: Declaration}), from *links* (Link) first, then
    by standard name, then by name; CouplingError when an input has none (unless optional) or several."""
    known_ranks = ranks(declarations)
    mappings = {}
    for declaration in declarations.values():
        for mapping in declaration.mappings:
            if mapping.name in mappings:
                raise CouplingError(f"mapping {mapping.name}: provided by {mappings[mapping.name][0]} and "
                                    f"{declaration.participant}")
            mappings[mapping.name] = (declaration.participant, mapping)
    owners = {}
    for declaration in declarations.values():
        for entity_set in declaration.entity_sets:
            if entity_set.rights == "owns":
                key = (entity_set.data_structure, entity_set.name)
                if key in owners:
                    raise CouplingError(f"entity set {key[0]}/{key[1]}: owned by {owners[key]} and "
                                        f"{declaration.participant}")
                owners[key] = declaration.participant
    by_receiver = {}
    for link in links:
        if link.receiver not in declarations:
            raise CouplingError(f"link to {link.receiver}.{link.variable}: no participant {link.receiver}")
        if link.provider not in declarations:
            raise CouplingError(f"link to {link.receiver}.{link.variable}: no participant {link.provider}")
        by_receiver.setdefault(link.receiver, []).append(link)

    couplings = []
    for receiver, declaration in declarations.items():
        for variable in declaration.requires():
            links_here = [link for link in by_receiver.get(receiver, []) if link.variable == variable.name
                          and link.entity_set in (None, variable.entity_set)]
            if len(links_here) > 1:
                raise CouplingError(f"{receiver}.{variable.name}: {len(links_here)} links")
            if links_here:
                link = links_here[0]
                sources = [source for source in declarations[link.provider].provides() if source.name == link.source
                           and link.source_entity_set in (None, source.entity_set)]
                if len(sources) != 1:
                    raise CouplingError(f"link {receiver}.{variable.name} <- {link.provider}.{link.source}: "
                                        f"{len(sources)} such outputs of {link.provider}")
                couplings.append(_coupling(receiver, variable, link.provider, sources[0], known_ranks, "link",
                                           link.factor, link.aggregation, link.interpolation,
                                           mappings.get(link.mapping, (None, link.mapping))[1]))
                continue
            coupling = None
            for how, same in (("standard name", lambda source: variable.standard_name is not None
                               and source.standard_name == variable.standard_name),
                              ("name", lambda source: source.name == variable.name)):
                candidates = [(name, source) for name, other in declarations.items() if name != receiver
                              for source in other.provides()
                              if source.data_structure == variable.data_structure and same(source)]
                if len(candidates) > 1:                  # the same entity set first
                    candidates = [(name, source) for name, source in candidates
                                  if source.entity_set == variable.entity_set] or candidates
                if len(candidates) > 1:
                    raise CouplingError(f"{receiver}.{variable.name}: provided by several outputs (by {how}): "
                                        f"{[f'{name}.{source.name}' for name, source in candidates]}; link it")
                if candidates:
                    coupling = _coupling(receiver, variable, *candidates[0], known_ranks, how)
                    break
            if coupling is None:
                if not variable.optional:
                    raise CouplingError(f"{receiver}.{variable.name}: no participant provides it (link it, or "
                                        "declare it optional)")
                coupling = Coupling(receiver, variable, None, None, how="not provided")
            couplings.append(coupling)
    return couplings


def _coupling(receiver, variable, provider, source, known_ranks, how, factor=1., aggregation=None,
              interpolation="hold", mapping=None) -> Coupling:
    where = f"{receiver}.{variable.name} <- {provider}.{source.name}"
    try:
        factor = factor * conversion_factor(source.unit, variable.unit)
    except UnitError as error:
        raise CouplingError(f"{where}: {error}") from None
    if mapping is not None or source.data_structure != variable.data_structure:
        if mapping is None or isinstance(mapping, str):
            raise CouplingError(f"{where}: different data structures ({source.data_structure}, "
                                f"{variable.data_structure}) need a mapping a participant provides"
                                + (f" ({mapping} is none)" if mapping else ""))
        if (mapping.source, mapping.target) == (source.where, variable.where):
            reverse = False
        elif (mapping.target, mapping.source) == (source.where, variable.where):
            reverse = True
        else:
            raise CouplingError(f"{where}: mapping {mapping.name} joins {mapping.source} and {mapping.target}, not "
                                f"{source.where} and {variable.where}")
        aggregation = aggregation or ("sum" if source.kind == "extensive" else "mean")
        if aggregation not in ("sum", "mean"):
            raise CouplingError(f"{where}: through a mapping, 'sum' or 'mean'")
        return Coupling(receiver, variable, provider, source, factor, aggregation, interpolation, how, mapping.name,
                        reverse)
    if source.entity_set != variable.entity_set:
        source_rank = known_ranks.get(source.where)
        target_rank = known_ranks.get(variable.where)
        if source_rank is None or target_rank is None:
            raise CouplingError(f"{receiver}.{variable.name} <- {provider}.{source.name}: the ranks of "
                                f"{source.entity_set} and {variable.entity_set} are needed (declare them)")
        if source_rank > target_rank:
            aggregation = aggregation or ("sum" if source.kind == "extensive" else "mean")
            if aggregation == "copy":
                raise CouplingError(f"{receiver}.{variable.name}: 'copy' goes from a coarser entity set")
        else:
            if aggregation not in (None, "copy"):
                raise CouplingError(f"{receiver}.{variable.name}: '{aggregation}' goes from a finer entity set")
            if source.kind == "extensive" and aggregation is None:
                raise CouplingError(f"{receiver}.{variable.name} <- {provider}.{source.name}: an extensive "
                                    "variable copied to finer entities counts it several times; link it with "
                                    "aggregation 'copy' if meant")
            aggregation = "copy"
    elif aggregation is not None:
        raise CouplingError(f"{receiver}.{variable.name}: aggregation '{aggregation}' on the same entity set")
    return Coupling(receiver, variable, provider, source, factor, aggregation, interpolation, how)


def stages(declarations: dict, given=None) -> list:
    """The stages: *given* (lists of participant names), else the owners, then the refiners, then the others; and
    the check that no stage holds two participants changing one entity set's topology."""
    if given is None:
        groups = {"owns": [], "refines": [], "follows": []}
        for name, declaration in declarations.items():
            rights = {entity_set.rights for entity_set in declaration.entity_sets}
            groups["owns" if "owns" in rights else "refines" if "refines" in rights else "follows"].append(name)
        given = [group for group in groups.values() if group]
    given = [list(stage) for stage in given]
    listed = [name for stage in given for name in stage]
    if sorted(listed) != sorted(declarations):
        raise CouplingError(f"stages {given}: each participant ({sorted(declarations)}) exactly once")
    for stage in given:
        changing = {}
        for name in stage:
            for entity_set in declarations[name].entity_sets:
                if entity_set.rights != "follows":
                    key = (entity_set.data_structure, entity_set.name)
                    if key in changing:
                        raise CouplingError(f"stage {stage}: {changing[key]} and {name} both change "
                                            f"{key[0]}/{key[1]}'s topology")
                    changing[key] = name
    return given
