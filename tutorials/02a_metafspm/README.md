# Tutorial 2a: metafspm

**What you learn:** how a metafspm scene is saved as encoding3d frames while it runs, how any platform reads them,
how to keep log files small, and how a frame becomes metafspm's data structures again.

**What you need** (not encoding3d's requirements: metafspm's own environment). metafspm is installed from source, in
the environment its repository describes, with encoding3d beside it:

```bash
git clone -b release2026 https://github.com/openalea/metafspm.git
git clone -b other_platforms_bindings https://github.com/openalea/encoding3d.git
mamba env create -n metafspm -f metafspm/conda/environment.yml
mamba activate metafspm
pip install -e encoding3d -e metafspm
pip install jupyter nbmake
```

**How to run it:** open `metafspm.ipynb` in Jupyter, or run `./run.sh`. It writes its files in `outputs/`.

In the notebook you

1. write a small root growth component (a toy: a tip elongating at a constant rate, cut every centimetre);
2. grow two plants in a scene for two days, a frame recorded every six hours (`SceneRecorder`), the frames packed
   into one file at the end (`frames.fspm.zip`);
3. read those frames with encoding3d alone, as any platform would;
4. record smaller frames for logging, keeping two scales and two variables;
5. turn the last frame back into metafspm's data structures, exactly as they were (`import_frame`).
