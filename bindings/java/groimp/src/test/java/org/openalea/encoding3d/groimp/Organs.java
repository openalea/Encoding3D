package org.openalea.encoding3d.groimp;

import de.grogra.graph.impl.Node;

/** Node classes as GroIMP models declare them (managed fields, as the XL compiler generates them): a plant, internodes
 * and leaves. */
final class Organs {
    private Organs() {}

    static final class Plant extends Node {
        private static final long serialVersionUID = 1L;
        public static final NType $TYPE;
        String species = "";

        static {
            $TYPE = new NType(Plant.class);
            $TYPE.addManagedField(new Field("species", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.STRING, null, 0));
            $TYPE.validate();
        }

        private static final class Field extends NType.Field {
            private final int id;

            Field(String name, int modifiers, de.grogra.reflect.Type<?> type, de.grogra.reflect.Type<?> componentType, int id) {
                super(Plant.$TYPE, name, modifiers, type, componentType);
                this.id = id;
            }

            @Override
            protected void setObjectImpl(Object o, Object value) {
                if (id == 0) ((Plant) o).species = (String) value; else super.setObjectImpl(o, value);
            }

            @Override
            public Object getObject(Object o) {
                return id == 0 ? ((Plant) o).species : super.getObject(o);
            }
        }

        @Override
        protected NType getNTypeImpl() {
            return $TYPE;
        }

        @Override
        protected Node newInstance() {
            return new Plant();
        }
    }

    static final class Internode extends Node {
        private static final long serialVersionUID = 1L;
        public static final NType $TYPE;
        double length;
        float radius;
        int rank;

        static {
            $TYPE = new NType(Internode.class);
            $TYPE.addManagedField(new Field("length", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.DOUBLE, null, 0));
            $TYPE.addManagedField(new Field("radius", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.FLOAT, null, 1));
            $TYPE.addManagedField(new Field("rank", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.INT, null, 2));
            $TYPE.validate();
        }

        private static final class Field extends NType.Field {
            private final int id;

            Field(String name, int modifiers, de.grogra.reflect.Type<?> type, de.grogra.reflect.Type<?> componentType, int id) {
                super(Internode.$TYPE, name, modifiers, type, componentType);
                this.id = id;
            }

            @Override
            public void setDouble(Object o, double value) {
                if (id == 0) ((Internode) o).length = value; else super.setDouble(o, value);
            }

            @Override
            public double getDouble(Object o) {
                return id == 0 ? ((Internode) o).length : super.getDouble(o);
            }

            @Override
            public void setFloat(Object o, float value) {
                if (id == 1) ((Internode) o).radius = value; else super.setFloat(o, value);
            }

            @Override
            public float getFloat(Object o) {
                return id == 1 ? ((Internode) o).radius : super.getFloat(o);
            }

            @Override
            public void setInt(Object o, int value) {
                if (id == 2) ((Internode) o).rank = value; else super.setInt(o, value);
            }

            @Override
            public int getInt(Object o) {
                return id == 2 ? ((Internode) o).rank : super.getInt(o);
            }
        }

        @Override
        protected NType getNTypeImpl() {
            return $TYPE;
        }

        @Override
        protected Node newInstance() {
            return new Internode();
        }
    }

    static final class Leaf extends Node {
        private static final long serialVersionUID = 1L;
        public static final NType $TYPE;
        double length;
        boolean alive = true;

        static {
            $TYPE = new NType(Leaf.class);
            $TYPE.addManagedField(new Field("length", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.DOUBLE, null, 0));
            $TYPE.addManagedField(new Field("alive", Field.PUBLIC | Field.SCO, de.grogra.reflect.Type.BOOLEAN, null, 1));
            $TYPE.validate();
        }

        private static final class Field extends NType.Field {
            private final int id;

            Field(String name, int modifiers, de.grogra.reflect.Type<?> type, de.grogra.reflect.Type<?> componentType, int id) {
                super(Leaf.$TYPE, name, modifiers, type, componentType);
                this.id = id;
            }

            @Override
            public void setDouble(Object o, double value) {
                if (id == 0) ((Leaf) o).length = value; else super.setDouble(o, value);
            }

            @Override
            public double getDouble(Object o) {
                return id == 0 ? ((Leaf) o).length : super.getDouble(o);
            }

            @Override
            public void setBoolean(Object o, boolean value) {
                if (id == 1) ((Leaf) o).alive = value; else super.setBoolean(o, value);
            }

            @Override
            public boolean getBoolean(Object o) {
                return id == 1 ? ((Leaf) o).alive : super.getBoolean(o);
            }
        }

        @Override
        protected NType getNTypeImpl() {
            return $TYPE;
        }

        @Override
        protected Node newInstance() {
            return new Leaf();
        }
    }
}
