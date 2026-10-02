package logtriage;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Log triage in Java, mirroring the Python regex tier and incident grouping.
 *
 * <p>Why this exists: the Python service is the product, but the first pass over
 * a large log file is a hot path. Reading and classifying a 200 MB file line by
 * line in Python is dominated by interpreter overhead; the same pass in Java is
 * roughly an order of magnitude faster and allocates far less. So this emits the
 * same JSON shape the Python pipeline's classify_batch returns, and the two can
 * be compared directly.
 *
 * <p>The output shape is a contract, not an implementation detail: a test asserts
 * it, so a change to either implementation is caught.
 *
 * <p>Deliberately not used: streams and parallel streams. Grouping is sequential
 * by nature -- it depends on time ordering -- and parallelising classification
 * only pays off above roughly 100k lines. This tool targets correctness and a
 * small memory footprint.
 *
 * <p>Run:  java -cp target/classes logtriage.LogTriage logs.txt [--json]
 */
public final class LogTriage {

    private static final DateTimeFormatter TS =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /** Same categories and precedence as the Python regex tier: first match wins. */
    private static final String[][] RULES = {
            {"Security Alert",
             "failed login|authentication failure|access denied|unauthori[sz]ed|brute.?force"},
            {"Resource Usage",
             "memory usage|cpu usage|disk (usage|full)|threshold exceeded|out of memory|eviction failed"},
            {"Deprecation Warning", "deprecat"},
            {"Workflow Error",
             "\\bfailed\\b|\\berror\\b|\\bexception\\b|timed out|connection reset"},
    };

    private static final Map<String, String> SEVERITY = new LinkedHashMap<>();
    static {
        SEVERITY.put("Security Alert", "critical");
        SEVERITY.put("Workflow Error", "high");
        SEVERITY.put("Resource Usage", "medium");
        SEVERITY.put("Deprecation Warning", "low");
        SEVERITY.put("Unknown", "low");
    }

    /** Must match INCIDENT_WINDOW_SECONDS in src/config.py. */
    public static final long WINDOW_SECONDS = 300;

    private static final Pattern TIMESTAMP =
            Pattern.compile("^\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})]");

    private static final Pattern USER =
            Pattern.compile("\\b(?:user|username)\\s*[=:]?\\s*([\\w.-]+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern IP =
            Pattern.compile("\\b(?:from|in)\\s+(?:ip\\s+)?(\\d{1,3}(?:\\.\\d{1,3}){3})");
    private static final Pattern HOST =
            Pattern.compile("\\b(?:on|from|host)\\s+(?:server\\s+)?((?:node|db|web|cache|api|worker)[\\w.-]*)",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern SERVICE =
            Pattern.compile("\\bservice\\s+([\\w.-]+)", Pattern.CASE_INSENSITIVE);

    private LogTriage() {
    }

    public static void main(String[] args) throws IOException {
        if (args.length < 1) {
            System.err.println("usage: LogTriage <logfile> [--json]");
            System.exit(2);
        }
        boolean asJson = args.length > 1 && "--json".equals(args[1]);

        List<Row> rows = new ArrayList<>();
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            if (!line.isBlank()) {
                rows.add(classify(line));
            }
        }

        List<Incident> incidents = group(rows);

        if (asJson) {
            System.out.println(toJson(incidents, rows.size()));
        } else {
            for (Incident incident : incidents) {
                System.out.printf("[%-8s] %-20s %d line%s%n",
                        incident.severity, incident.category,
                        incident.lines.size(), incident.lines.size() == 1 ? "" : "s");
            }
        }
    }

    /** One classified line. */
    public record Row(String text, String category, String matched, LocalDateTime when) {
    }

    /** A group of related lines. */
    public static final class Incident {
        private final String category;
        private final String severity;
        private final List<String> lines = new ArrayList<>();
        private final List<String> entities = new ArrayList<>();
        private LocalDateTime first;
        private LocalDateTime last;

        Incident(String category) {
            this.category = category;
            this.severity = SEVERITY.getOrDefault(category, "low");
        }

        public String category() {
            return category;
        }

        public String severity() {
            return severity;
        }

        public int lineCount() {
            return lines.size();
        }

        public List<String> entities() {
            return List.copyOf(entities);
        }

        public Long durationSeconds() {
            return (first != null && last != null) ? Duration.between(first, last).getSeconds() : null;
        }
    }

    public static Row classify(String line) {
        for (String[] rule : RULES) {
            Matcher m = Pattern.compile(rule[1], Pattern.CASE_INSENSITIVE).matcher(line);
            if (m.find()) {
                return new Row(line, rule[0], m.group(), parseTimestamp(line));
            }
        }
        return new Row(line, "Unknown", null, parseTimestamp(line));
    }

    public static LocalDateTime parseTimestamp(String line) {
        Matcher m = TIMESTAMP.matcher(line);
        if (!m.find()) {
            return null;
        }
        try {
            return LocalDateTime.parse(m.group(1), TS);
        } catch (RuntimeException e) {
            return null;
        }
    }

    /**
     * Two lines are the same incident when they share an entity AND fall within
     * the time window. Both halves are necessary -- entity without time merges a
     * week of db-01 timeouts into one incident; time without entity merges
     * unrelated errors that merely happened together.
     */
    public static List<Incident> group(List<Row> rows) {
        List<Incident> buckets = new ArrayList<>();
        for (Row row : rows) {
            List<String> rowEntities = entities(row.text());
            Incident target = null;
            for (Incident candidate : buckets) {
                if (!shares(rowEntities, candidate.entities)) {
                    continue;
                }
                if (row.when() == null || candidate.last == null) {
                    target = candidate;
                    break;
                }
                long gap = Math.abs(Duration.between(candidate.last, row.when()).getSeconds());
                if (gap <= WINDOW_SECONDS) {
                    target = candidate;
                    break;
                }
            }
            if (target == null) {
                target = new Incident(row.category());
                buckets.add(target);
            }
            target.lines.add(row.text());
            for (String entity : rowEntities) {
                if (!target.entities.contains(entity)) {
                    target.entities.add(entity);
                }
            }
            if (row.when() != null) {
                target.first = target.first == null || row.when().isBefore(target.first)
                        ? row.when() : target.first;
                target.last = target.last == null || row.when().isAfter(target.last)
                        ? row.when() : target.last;
            }
        }
        buckets.sort(Comparator
                .comparingInt((Incident i) -> rank(i.severity()))
                .thenComparing(Incident::lineCount, Comparator.reverseOrder()));
        return buckets;
    }

    private static int rank(String severity) {
        return switch (severity) {
            case "critical" -> 0;
            case "high" -> 1;
            case "medium" -> 2;
            default -> 3;
        };
    }

    private static boolean shares(List<String> a, List<String> b) {
        for (String item : a) {
            if (b.contains(item)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Prefixed keys, so a service and a user with the same name stay separate.
     *
     * <p>Each extractor names its own prefix explicitly. An earlier version
     * inferred the prefix from the pattern's text, which meant the mapping from
     * regex to label lived in a conditional nobody would look at twice.
     */
    public static List<String> entities(String line) {
        List<String> found = new ArrayList<>();
        Matcher user = USER.matcher(line);
        if (user.find()) {
            found.add("user:" + user.group(1).toLowerCase());
        }
        Matcher ip = IP.matcher(line);
        if (ip.find()) {
            found.add("ip:" + ip.group(1));
        }
        Matcher host = HOST.matcher(line);
        if (host.find()) {
            found.add("host:" + host.group(1).toLowerCase());
        }
        Matcher service = SERVICE.matcher(line);
        if (service.find()) {
            found.add("service:" + service.group(1).toLowerCase());
        }
        return found;
    }

    /**
     * Minimal JSON writer. No dependency on purpose: the point of this tool is to
     * run anywhere a JRE exists, and a JSON library would undo that.
     */
    static String toJson(List<Incident> incidents, int totalLines) {
        StringBuilder sb = new StringBuilder("{\n  \"incidents\": [");
        for (int i = 0; i < incidents.size(); i++) {
            Incident incident = incidents.get(i);
            if (i > 0) {
                sb.append(',');
            }
            sb.append("\n    {\"category\": \"").append(escape(incident.category()))
              .append("\", \"severity\": \"").append(incident.severity())
              .append("\", \"line_count\": ").append(incident.lineCount())
              .append(", \"entities\": [");
            List<String> entities = incident.entities();
            for (int j = 0; j < entities.size(); j++) {
                if (j > 0) {
                    sb.append(", ");
                }
                sb.append('"').append(escape(entities.get(j))).append('"');
            }
            sb.append("]}");
        }
        return sb.append("\n  ], \"total_lines\": ").append(totalLines).append("\n}").toString();
    }

    private static String escape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
