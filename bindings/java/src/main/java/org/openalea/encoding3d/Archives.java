package org.openalea.encoding3d;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.zip.CRC32;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import org.tukaani.xz.LZMAInputStream;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Archives (specification §8.2): a sequence packed into one .fspm.zip file, a ZIP archive (ZIP64 when it needs to be)
 * whose members are the folder's files, each compressed alone (stored, deflate or lzma, ZIP's methods 0, 8 and 14). A
 * file inside an archive is named "&lt;archive&gt;.fspm.zip/&lt;member&gt;"; {@link #readBytes} and {@link #exists} read such
 * paths as they read a folder's files.
 *
 * <p>Reading: the central directory and its ZIP64 records read here; deflate through java.util.zip.Inflater, lzma
 * through xz-java's LZMAInputStream, each member's CRC-32 checked. Packing: java.util.zip.ZipOutputStream (stored or
 * deflate, ZIP64 when needed).
 */
public final class Archives {
    /** The end of an archive's name. */
    public static final String SUFFIX = ".fspm.zip";
    private static final int STORED = 0, DEFLATE = 8, LZMA = 14;
    private static final long FULL = 0xFFFFFFFFL;
    private static final int KEPT_OPEN = 4;
    /** The central directories last read: {archive: (its modification time and size, its members)}. */
    private static final Map<Path, Directory> DIRECTORIES = new LinkedHashMap<>();

    /** A member: its method, general purpose flags, CRC-32, sizes and local header's offset. */
    private record Member(int method, int flags, long crc, long compressedSize, long size, long localHeader) {}

    /** The general purpose flag of an lzma member whose data ends with LZMA's end of payload marker. */
    private static final int LZMA_END_MARKER = 0x2;

    private record Directory(long modified, long length, Map<String, Member> members) {}

    /** (archive, member) of a path inside an archive, or of an archive itself (its index); null otherwise. */
    record Inside(Path archive, String member) {}

    private Archives() {}

    static Inside split(Path path) {
        String normalised = path.toString().replace('\\', '/');
        if (normalised.endsWith(SUFFIX) && Files.isRegularFile(path)) return new Inside(path, Sequences.INDEX_FILE);
        for (int position = normalised.indexOf(SUFFIX + "/"); position >= 0; position = normalised.indexOf(SUFFIX + "/", position + 1)) {
            Path archive = Path.of(path.toString().substring(0, position + SUFFIX.length()));
            if (!Files.isRegularFile(archive)) continue;
            List<String> parts = new ArrayList<>();
            for (String part : normalised.substring(position + SUFFIX.length() + 1).split("/")) {
                if (part.equals("..")) throw new Encoding3dException("member '" + normalised + "': no '..' in an archive's paths");
                if (!part.isEmpty() && !part.equals(".")) parts.add(part);
            }
            return new Inside(archive, String.join("/", parts));
        }
        return null;
    }

    /** The bytes of the file {@code path}, in a folder or in an archive ("x.fspm.zip/member"). */
    public static byte[] readBytes(Path path) throws IOException {
        Inside inside = split(path);
        if (inside == null) return Files.readAllBytes(path);
        Member member = directory(inside.archive()).members().get(inside.member());
        if (member == null) throw new java.nio.file.NoSuchFileException(inside.archive() + " holds no '" + inside.member() + "'");
        if (member.size() > Integer.MAX_VALUE - 16)
            throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + ": over 2 GB, more than a Java array holds");
        byte[] bytes;
        try (FileChannel channel = FileChannel.open(inside.archive(), StandardOpenOption.READ)) {
            ByteBuffer header = read(channel, member.localHeader(), 30);
            if (header.getInt(0) != 0x04034B50) throw new Encoding3dException(inside.archive() + ": a member's local header is missing");
            long start = member.localHeader() + 30 + Short.toUnsignedInt(header.getShort(26)) + Short.toUnsignedInt(header.getShort(28));
            if (member.compressedSize() > Integer.MAX_VALUE - 16)
                throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + ": over 2 GB compressed");
            byte[] compressed = new byte[(int) member.compressedSize()];
            read(channel, start, compressed.length).get(compressed);
            bytes = decompress(compressed, member, inside);
        }
        CRC32 crc = new CRC32();
        crc.update(bytes);
        if (crc.getValue() != member.crc())
            throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + " is corrupt (its CRC-32 differs)");
        return bytes;
    }

    /** Whether the file {@code path} exists, in a folder or in an archive. */
    public static boolean exists(Path path) throws IOException {
        Inside inside = split(path);
        if (inside == null) return Files.exists(path);
        return directory(inside.archive()).members().containsKey(inside.member());
    }

    private static byte[] decompress(byte[] compressed, Member member, Inside inside) throws IOException {
        int size = (int) member.size();
        switch (member.method()) {
            case STORED -> {
                return compressed;
            }
            case DEFLATE -> {
                Inflater inflater = new Inflater(true);
                try {
                    inflater.setInput(compressed);
                    byte[] bytes = new byte[size];
                    int done = 0;
                    while (done < size && !inflater.finished()) {
                        int read = inflater.inflate(bytes, done, size - done);
                        if (read == 0 && (inflater.needsInput() || inflater.needsDictionary())) break;
                        done += read;
                    }
                    if (done != size) throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + ": truncated");
                    return bytes;
                } catch (DataFormatException error) {
                    throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + ": " + error.getMessage(), error);
                } finally {
                    inflater.end();
                }
            }
            case LZMA -> {                    // ZIP's LZMA: version (2 bytes), properties' size (2), properties, data
                ByteBuffer header = ByteBuffer.wrap(compressed).order(ByteOrder.LITTLE_ENDIAN);
                int propertiesSize = Short.toUnsignedInt(header.getShort(2));
                if (propertiesSize != 5) throw new Encoding3dException("'" + inside.member() + "': LZMA properties of 5 bytes expected");
                byte properties = compressed[4];
                int dictionarySize = header.getInt(5);
                long known = (member.flags() & LZMA_END_MARKER) != 0 ? -1 : member.size();   // -1: up to its end marker
                try (InputStream stream = new LZMAInputStream(new ByteArrayInputStream(compressed, 9, compressed.length - 9),
                        known, properties, dictionarySize)) {
                    return stream.readNBytes(size);
                }
            }
            default -> throw new Encoding3dException("'" + inside.member() + "' in " + inside.archive() + ": ZIP method "
                    + member.method() + " (an archive's members are stored, deflate or lzma)");
        }
    }

    private static ByteBuffer read(FileChannel channel, long position, int length) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(length).order(ByteOrder.LITTLE_ENDIAN);
        while (buffer.hasRemaining()) {
            if (channel.read(buffer, position + buffer.position()) < 0) throw new Encoding3dException("a ZIP archive ends too soon");
        }
        return buffer.flip();
    }

    /** The members of an archive, from its central directory (its ZIP64 records when it has them). */
    private static synchronized Directory directory(Path archive) throws IOException {
        long modified = Files.getLastModifiedTime(archive).toMillis(), length = Files.size(archive);
        Directory known = DIRECTORIES.get(archive);
        if (known != null && known.modified() == modified && known.length() == length) return known;
        Map<String, Member> members = new HashMap<>();
        try (FileChannel channel = FileChannel.open(archive, StandardOpenOption.READ)) {
            int tail = (int) Math.min(length, 22 + 65535);
            ByteBuffer end = read(channel, length - tail, tail);
            int record = -1;
            for (int position = tail - 22; position >= 0; position--)
                if (end.getInt(position) == 0x06054B50) {
                    record = position;
                    break;
                }
            if (record < 0) throw new Encoding3dException("'" + archive + "' is not a ZIP archive");
            long count = Short.toUnsignedInt(end.getShort(record + 10));
            long directorySize = Integer.toUnsignedLong(end.getInt(record + 12));
            long directoryStart = Integer.toUnsignedLong(end.getInt(record + 16));
            long recordPosition = length - tail + record;
            if (recordPosition >= 20) {                       // a ZIP64 end of central directory, through its locator
                ByteBuffer locator = read(channel, recordPosition - 20, 20);
                if (locator.getInt(0) == 0x07064B50) {
                    ByteBuffer zip64 = read(channel, locator.getLong(8), 56);
                    if (zip64.getInt(0) != 0x06064B50) throw new Encoding3dException("'" + archive + "': a broken ZIP64 record");
                    count = zip64.getLong(32);
                    directorySize = zip64.getLong(40);
                    directoryStart = zip64.getLong(48);
                }
            }
            if (directorySize > Integer.MAX_VALUE) throw new Encoding3dException("'" + archive + "': a central directory over 2 GB");
            ByteBuffer entries = read(channel, directoryStart, (int) directorySize);
            int position = 0;
            for (long entry = 0; entry < count; entry++) {
                if (entries.getInt(position) != 0x02014B50) throw new Encoding3dException("'" + archive + "': a broken central directory");
                int flags = Short.toUnsignedInt(entries.getShort(position + 8));
                int method = Short.toUnsignedInt(entries.getShort(position + 10));
                long crc = Integer.toUnsignedLong(entries.getInt(position + 16));
                long compressedSize = Integer.toUnsignedLong(entries.getInt(position + 20));
                long size = Integer.toUnsignedLong(entries.getInt(position + 24));
                int nameLength = Short.toUnsignedInt(entries.getShort(position + 28));
                int extraLength = Short.toUnsignedInt(entries.getShort(position + 30));
                int commentLength = Short.toUnsignedInt(entries.getShort(position + 32));
                long localHeader = Integer.toUnsignedLong(entries.getInt(position + 42));
                byte[] name = new byte[nameLength];
                entries.get(position + 46, name);
                for (int extra = position + 46 + nameLength; extra + 4 <= position + 46 + nameLength + extraLength; ) {
                    int identifier = Short.toUnsignedInt(entries.getShort(extra)), extraSize = Short.toUnsignedInt(entries.getShort(extra + 2));
                    if (identifier == 0x0001) {               // ZIP64: the sizes and offset the header could not hold, in order
                        int field = extra + 4;
                        if (size == FULL) { size = entries.getLong(field); field += 8; }
                        if (compressedSize == FULL) { compressedSize = entries.getLong(field); field += 8; }
                        if (localHeader == FULL) localHeader = entries.getLong(field);
                    }
                    extra += 4 + extraSize;
                }
                members.put(new String(name, StandardCharsets.UTF_8), new Member(method, flags, crc, compressedSize, size, localHeader));
                position += 46 + nameLength + extraLength + commentLength;
            }
        }
        Directory read = new Directory(modified, length, members);
        while (DIRECTORIES.size() >= KEPT_OPEN) DIRECTORIES.remove(DIRECTORIES.keySet().iterator().next());
        DIRECTORIES.put(archive, read);
        return read;
    }

    /**
     * Packs the sequence of {@code folder} (a folder, or its index) into the archive {@code path} (x.fspm.zip, ZIP64 when
     * needed): its index, views.json, its frames and the parts they use, unchanged, each compressed alone
     * ({@code compression}: "deflate" or "stored"). Returns {@code path}.
     */
    public static Path pack(Path folder, Path path, String compression) throws IOException {
        int method = switch (compression) {
            case "deflate" -> ZipEntry.DEFLATED;
            case "stored" -> ZipEntry.STORED;
            default -> throw new Encoding3dException("compression '" + compression + "': deflate or stored (lzma: read only, in Java)");
        };
        if (!path.toString().endsWith(SUFFIX)) throw new Encoding3dException("'" + path + "': an archive's name ends in " + SUFFIX);
        Path indexPath = Files.isDirectory(folder) ? folder.resolve(Sequences.INDEX_FILE) : folder;
        Path base = indexPath.toAbsolutePath().getParent();
        Sequences.Index index = Sequences.readIndex(indexPath);
        List<String> members = new ArrayList<>(List.of(Sequences.INDEX_FILE));
        if (Files.exists(base.resolve("views.json"))) members.add("views.json");
        TreeSet<String> keys = new TreeSet<>(index.parts());
        for (Sequences.Entry entry : index.frames()) {
            members.add(entry.file());
            JsonNode scene = Glb.unpack(readBytes(entry.path())).document().path("extensions").path("FSPM_scene");
            for (JsonNode dataStructure : scene.path("dataStructures"))
                for (JsonNode instanceSet : dataStructure.path("instanceSets"))
                    for (JsonNode key : instanceSet.path("parts")) keys.add(key.asText());
        }
        for (String key : keys) members.add(Parts.FOLDER + "/" + key + ".glb");
        for (String member : members)
            if (!Files.exists(base.resolve(member))) {
                if (member.startsWith(Parts.FOLDER + "/"))
                    throw new MissingPartException(member.substring(6, member.length() - 4), List.of(base.resolve(member).toString()));
                throw new java.nio.file.NoSuchFileException(base.resolve(member).toString());
            }
        Path temporary = Path.of(path + ".part");
        try (OutputStream file = Files.newOutputStream(temporary); ZipOutputStream zip = new ZipOutputStream(file)) {
            for (String member : members) {
                byte[] bytes = Files.readAllBytes(base.resolve(member));
                ZipEntry entry = new ZipEntry(member);
                entry.setMethod(method);
                if (method == ZipEntry.STORED) {
                    CRC32 crc = new CRC32();
                    crc.update(bytes);
                    entry.setSize(bytes.length);
                    entry.setCompressedSize(bytes.length);
                    entry.setCrc(crc.getValue());
                }
                zip.putNextEntry(entry);
                zip.write(bytes);
                zip.closeEntry();
            }
        }
        Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING);
        return path;
    }

    public static Path pack(Path folder, Path path) throws IOException {
        return pack(folder, path, "deflate");
    }
}
