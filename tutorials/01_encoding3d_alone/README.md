# Tutorial 1: encoding3d on its own

**What you learn:** what an encoding3d file holds, and how to write, check, read and view one, with no plant
modelling platform at all.

**What you need:** Python with `openalea.encoding3d` (from the repository's root: `pip install -e .`), numpy, pandas
and Jupyter; ParaView 5.11 or later to look at the result (optional).

**How to run it:** open `encoding3d_alone.ipynb` in Jupyter and run the cells one after the other, or run it all at
once with `./run.sh`. It writes its files in `outputs/`.

In the notebook you

1. describe a small root system at three scales (plant, axes, segments), its parts with ids that never change, and
   its variables with their units and standard names, then write it as a frame and check it with the validator;
2. let it grow for five days and write a frame per day, a sequence, with its index `scene.fspm.json`;
3. read the sequence back, follow one segment from day to day, and read a frame lazily (only the columns you use);
4. say how viewers should draw it (`views.json`) and open it in ParaView.

Next: tutorial 2 shows the same kind of files written and read by the platforms themselves.
