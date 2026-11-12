package tutorial;

import java.lang.reflect.Field;

import de.grogra.graph.impl.Node;
import de.grogra.graph.impl.Node.NType;
import de.grogra.reflect.Type;

/**
 * GroIMP's "managed fields": the fields of a node class GroIMP knows by name, as its XL compiler declares them for the
 * classes of an RGG model. GroIMP's adapter writes them as columns. Here they are declared from plain Java fields by
 * reflection, so that the tutorial's node classes stay short.
 */
final class Managed {
    private Managed() {}

    /** The NType of {@code type}, with its fields {@code names} managed. */
    static NType type(Class<? extends Node> type, String... names) {
        NType nodeType = new NType(type);
        for (String name : names) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                nodeType.addManagedField(new ManagedField(nodeType, field));
            } catch (NoSuchFieldException error) {
                throw new IllegalArgumentException(type.getSimpleName() + " has no field " + name, error);
            }
        }
        nodeType.validate();
        return nodeType;
    }

    private static final class ManagedField extends NType.Field {
        private final Field field;

        ManagedField(NType type, Field field) {
            super(type, field.getName(), PUBLIC | SCO, typeOf(field.getType()), null);
            this.field = field;
        }

        private static Type<?> typeOf(Class<?> type) {
            if (type == double.class) return Type.DOUBLE;
            if (type == float.class) return Type.FLOAT;
            if (type == int.class) return Type.INT;
            if (type == boolean.class) return Type.BOOLEAN;
            if (type == String.class) return Type.STRING;
            throw new IllegalArgumentException("a managed field of type " + type);
        }

        private Object read(Object node) {
            try {
                return field.get(node);
            } catch (IllegalAccessException error) {
                throw new IllegalStateException(error);
            }
        }

        private void write(Object node, Object value) {
            try {
                field.set(node, value);
            } catch (IllegalAccessException error) {
                throw new IllegalStateException(error);
            }
        }

        @Override public double getDouble(Object node) { return (double) read(node); }
        @Override public void setDouble(Object node, double value) { write(node, value); }
        @Override public float getFloat(Object node) { return (float) read(node); }
        @Override public void setFloat(Object node, float value) { write(node, value); }
        @Override public int getInt(Object node) { return (int) read(node); }
        @Override public void setInt(Object node, int value) { write(node, value); }
        @Override public boolean getBoolean(Object node) { return (boolean) read(node); }
        @Override public void setBoolean(Object node, boolean value) { write(node, value); }
        @Override public Object getObject(Object node) { return read(node); }
        @Override protected void setObjectImpl(Object node, Object value) { write(node, value); }
    }
}
