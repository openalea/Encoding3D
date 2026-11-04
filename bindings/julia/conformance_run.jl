# The Julia codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
# it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
# Then .github/actions/conformance compares the dumps with the expected values and validates the written files.
#
#     julia --project=bindings/julia/encoding3d bindings/julia/conformance_run.jl CONFORMANCE OUT

using encoding3d

function main(conformance::AbstractString, out::AbstractString)
    for (folder, _, files) in walkdir(conformance)
        for name in sort(files)
            endswith(name, ".glb") || continue
            startswith(relpath(folder, conformance), "coupling") && continue       # the coupling sessions
            relative = relpath(joinpath(folder, name), conformance)
            frame = read_frame(joinpath(conformance, relative))
            dump = joinpath(out, "dumps", relative[1:end-length(".glb")] * ".json")
            written = joinpath(out, "written", relative)
            mkpath(dirname(dump))
            mkpath(dirname(written))
            write_dump(dump, frame)
            write_frame(written, frame)                         # written again from what was read
        end
    end
    index = joinpath(conformance, "growing_sequence", "scene.fspm.json")
    isfile(index) && cp(index, joinpath(out, "written", "growing_sequence", "scene.fspm.json"); force = true)
    return 0
end

main(ARGS[1], ARGS[2])
