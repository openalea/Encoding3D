package org.openalea.encoding3d;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The GLB container: a 12-byte header (magic, version 2, total length), a JSON chunk padded with spaces, a binary chunk
 * padded with zeros, each 8-byte aligned (as EXT_structural_metadata requires). Little-endian throughout.
 */
public final class Glb {
    private static final int MAGIC = 0x46546C67;          // "glTF"
    private static final int VERSION = 2;
    private static final int JSON_CHUNK = 0x4E4F534A;     // "JSON"
    private static final int BINARY_CHUNK = 0x004E4942;   // "BIN\0"
    static final ObjectMapper MAPPER = new ObjectMapper();

    /** A GLB file's JSON document and binary buffer. */
    public record Contents(JsonNode document, byte[] binary) {}

    private Glb() {}

    static int padding(long length) {
        return (int) ((8 - length % 8) % 8);
    }

    /** The bytes of a GLB file from its JSON document and its binary buffer (both padded to 8 bytes). */
    public static byte[] pack(JsonNode document, byte[] binary) {
        byte[] text;
        try {
            text = MAPPER.writeValueAsBytes(document);
        } catch (IOException error) {
            throw new Encoding3dException("the document cannot be written as JSON", error);
        }
        int textLength = text.length + padding(text.length);
        int binaryLength = binary.length + padding(binary.length);
        long total = 12L + 8 + textLength + (binary.length == 0 ? 0 : 8 + binaryLength);
        if (total > 0xFFFFFFFFL) throw new Encoding3dException("a GLB file is at most 4 GiB");
        ByteBuffer buffer = ByteBuffer.allocate((int) total).order(ByteOrder.LITTLE_ENDIAN);
        buffer.putInt(MAGIC).putInt(VERSION).putInt((int) total).putInt(textLength).putInt(JSON_CHUNK).put(text);
        for (int index = text.length; index < textLength; index++) buffer.put((byte) ' ');
        if (binary.length > 0) {
            buffer.putInt(binaryLength).putInt(BINARY_CHUNK).put(binary);
            buffer.put(new byte[binaryLength - binary.length]);
        }
        return buffer.array();
    }

    /** The JSON document (keys in their order) and the binary buffer of a GLB file's bytes. */
    public static Contents unpack(byte[] data) {
        if (data.length < 20) throw new Encoding3dException("not a GLB file: too short");
        ByteBuffer buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        if (buffer.getInt(0) != MAGIC) throw new Encoding3dException("not a GLB file: wrong magic");
        if (buffer.getInt(4) != VERSION) throw new Encoding3dException("GLB version " + buffer.getInt(4) + ", 2 expected");
        long total = Integer.toUnsignedLong(buffer.getInt(8));
        if (total != data.length)
            throw new Encoding3dException("GLB header length " + total + ", the file holds " + data.length + " bytes");
        int offset = 12;
        JsonNode document = null;
        byte[] binary = new byte[0];
        while (offset < total) {
            int length = buffer.getInt(offset), type = buffer.getInt(offset + 4);
            if (length < 0 || offset + 8L + length > total) throw new Encoding3dException("a GLB chunk runs past the end of the file");
            if (type == JSON_CHUNK) {
                try {
                    document = MAPPER.readTree(Arrays.copyOfRange(data, offset + 8, offset + 8 + length));
                } catch (IOException error) {
                    throw new Encoding3dException("the GLB file's JSON chunk is not JSON", error);
                }
            } else if (type == BINARY_CHUNK) {
                binary = Arrays.copyOfRange(data, offset + 8, offset + 8 + length);
            }
            offset += 8 + length;
        }
        if (document == null) throw new Encoding3dException("GLB file without a JSON chunk");
        return new Contents(document, binary);
    }

    /** Appends arrays to one binary buffer, each at an 8-byte aligned offset, and records their buffer views. */
    static final class BufferBuilder {
        final ByteArrayOutputStream data = new ByteArrayOutputStream();
        final com.fasterxml.jackson.databind.node.ArrayNode views = MAPPER.createArrayNode();

        int add(byte[] bytes, int target) {
            data.write(new byte[padding(data.size())], 0, padding(data.size()));
            var view = views.addObject();
            view.put("buffer", 0).put("byteOffset", data.size()).put("byteLength", bytes.length);
            if (target != 0) view.put("target", target);
            data.write(bytes, 0, bytes.length);
            return views.size() - 1;
        }

        int add(byte[] bytes) {
            return add(bytes, 0);
        }
    }
}
