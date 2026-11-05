# Tutorial 4, VirtualPlantLab's side: light and photosynthesis (functional, a toy). Each turn, the shoot's phytomers
# (GroIMP's, sent by the session) become a PlantGraphs graph (to_graph); a query then gives each leaf the light left
# under the leaves above it (Beer-Lambert) and its photosynthesis (a light-use efficiency). The plant's total
# assimilation goes to the plant, for metafspm.
using encoding3d
using PlantGraphs
using ZMQ

const INCIDENT = 1000.0          # umol/s of light (PAR) falling on the plant's ground area
const GROUND = 0.01              # m2: the plant's ground area
const EXTINCTION = 0.6           # the canopy's light extinction coefficient
const EFFICIENCY = 0.05          # mol CO2 fixed per mol of light absorbed

mutable struct Leaf <: Node     # a phytomer's leaf, as the session sends it (to_graph fills its fields)
    area::Float64                # m2
    height::Float64              # m
end

declaration = Declaration("virtualplantlab"; platform = "VirtualPlantLab",
    entity_sets = [EntitySetSpec("plant", "Plant"; rank = 1), EntitySetSpec("plant", "Phytomer"; rank = 4)],
    variables = [VariableSpec("plant", "Phytomer", "area", "requires"; unit = "m2", kind = "extensive"),
                 VariableSpec("plant", "Phytomer", "height", "requires"; unit = "m", kind = "descriptor"),
                 VariableSpec("plant", "Phytomer", "absorbed_light", "provides"; unit = "umol/s", kind = "extensive"),
                 VariableSpec("plant", "Phytomer", "assimilation", "provides"; unit = "umol/s", kind = "extensive"),
                 VariableSpec("plant", "Plant", "plant_assimilation", "provides"; unit = "umol/s", kind = "extensive")])
participant = Participant(declaration; timeout = 600)

for turn in turns(participant)
    plant = data_structure(turn.frame, "plant")
    if !any(set -> set.name == "Phytomer", plant.entity_sets) || row_count(entity_set(plant, "Phytomer")) == 0
        send_update(participant, Frame())
        continue
    end
    shoot = entity_set(plant, "Phytomer")
    # the phytomers as a VirtualPlantLab graph: each row a Leaf node, its fields from the columns
    static, graph_ids = to_graph(plant; entity_set = "Phytomer", types = Dict("Phytomer" => Leaf))
    canopy = Graph(axiom = static)
    # Beer-Lambert down the canopy, by a query: a leaf receives the light the leaves above it let through
    leaves = sort(apply(canopy, Query(Leaf)); by = leaf -> -leaf.height)
    absorbed, assimilation = IdDict{Leaf,Float64}(), IdDict{Leaf,Float64}()
    area_above = 0.0
    for leaf in leaves
        light = INCIDENT * exp(-EXTINCTION * area_above / GROUND)
        absorbed[leaf] = light * (1 - exp(-EXTINCTION * leaf.area / GROUND))
        assimilation[leaf] = EFFICIENCY * absorbed[leaf]
        area_above += leaf.area
    end
    # sent: each phytomer's light and assimilation (its row's leaf, by its id), the plant's total
    leaf_of = [static_graph(canopy)[graph_ids[id]].data for id in shoot.columns["id"]]   # the graph holds a copy
    phytomers = EntitySet("Phytomer"; rank = 4, columns = encoding3d.Columns(
        "id" => shoot.columns["id"],
        "absorbed_light" => [absorbed[leaf] for leaf in leaf_of],
        "assimilation" => [assimilation[leaf] for leaf in leaf_of]))
    total = sum(values(assimilation))
    plants = EntitySet("Plant"; rank = 1, columns = encoding3d.Columns(
        "id" => entity_set(plant, "Plant").columns["id"], "plant_assimilation" => [total]))
    send_update(participant, Frame(data_structures = [DataStructure("plant"; entity_sets = [plants, phytomers])]))
    println("virtualplantlab: ", length(leaves), " leaves, assimilation ", round(total; digits = 2), " umol/s")
end
println("virtualplantlab: the session ended (", participant.stopped, ")")
