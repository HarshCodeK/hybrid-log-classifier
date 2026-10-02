package logtriage;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * These mirror tests/test_classifier.py case for case.
 *
 * <p>That is deliberate. Two implementations of the same rule are only useful if
 * they agree, so the cases are copied rather than invented -- a divergence in
 * behaviour shows up as a failing test instead of a disagreement in production.
 */
class LogTriageTest {

    // --- classification ---------------------------------------------------

    @Test
    @DisplayName("known phrasings map to their category")
    void knownPatterns() {
        assertEquals("Security Alert",
                LogTriage.classify("Failed login for user alice from ip 10.0.0.1").category());
        assertEquals("Resource Usage",
                LogTriage.classify("Memory usage at 94% on server node-12, threshold exceeded").category());
        assertEquals("Deprecation Warning",
                LogTriage.classify("Deprecation warning: legacy_auth is deprecated").category());
        assertEquals("Workflow Error",
                LogTriage.classify("ETL job nightly failed: connection reset by peer").category());
    }

    @Test
    @DisplayName("an unremarkable line is Unknown, not a guess")
    void unknownLine() {
        assertEquals("Unknown", LogTriage.classify("the sky is blue").category());
    }

    @Test
    @DisplayName("specificity wins: login beats the general 'failed'")
    void specificityOrder() {
        assertEquals("Security Alert", LogTriage.classify("failed login attempt").category());
    }

    // --- entities ---------------------------------------------------------

    @Test
    void extractsUserAndIp() {
        List<String> found = LogTriage.entities("Failed login for user admin_42 from ip 203.0.113.7");
        assertTrue(found.contains("user:admin_42"));
        assertTrue(found.contains("ip:203.0.113.7"));
    }

    @Test
    @DisplayName("two spellings of one user produce one entity")
    void userSpellingsAgree() {
        assertEquals(LogTriage.entities("failed login for user=alice"),
                LogTriage.entities("failed login for user alice"));
    }

    @Test
    @DisplayName("a hyphenated hostname is captured whole")
    void hyphenatedHost() {
        // The trap: matching 'node' inside 'node-12' and capturing '12' splits
        // one host's logs across separate incidents.
        assertTrue(LogTriage.entities("Memory usage at 99% on node-12").contains("host:node-12"));
    }

    @Test
    @DisplayName("the 'server' filler word is skipped")
    void serverFillerSkipped() {
        assertTrue(LogTriage.entities("Memory usage at 99% on server node-12").contains("host:node-12"));
    }

    @Test
    void serviceAndUserAreDistinct() {
        assertTrue(LogTriage.entities("service admin restarted").contains("service:admin"));
        assertTrue(LogTriage.entities("login for user admin").contains("user:admin"));
    }

    // --- timestamps -------------------------------------------------------

    @Test
    void parsesLeadingTimestamp() {
        assertNotNull(LogTriage.parseTimestamp("[2026-09-30 02:14:01] something failed"));
        assertNull(LogTriage.parseTimestamp("no timestamp here"));
    }

    // --- grouping ---------------------------------------------------------

    private List<LogTriage.Incident> group(String... lines) {
        return LogTriage.group(java.util.Arrays.stream(lines)
                .map(LogTriage::classify).toList());
    }

    @Test
    @DisplayName("same entity, close in time, merges")
    void sameEntityNearInTime() {
        assertEquals(1, group(
                "[2026-09-30 10:00:00] failed for user alice",
                "[2026-09-30 10:01:00] failed for user alice").size());
    }

    @Test
    @DisplayName("same entity, far apart in time, splits")
    void sameEntityDistantInTime() {
        assertEquals(2, group(
                "[2026-09-30 10:00:00] failed for user alice",
                "[2026-09-30 16:00:00] failed for user alice").size());
    }

    @Test
    @DisplayName("different entities never merge, even at the same instant")
    void differentEntities() {
        assertEquals(2, group(
                "[2026-09-30 10:00:00] failed for user alice",
                "[2026-09-30 10:00:10] failed for user bob").size());
    }

    @Test
    @DisplayName("incidents come back worst-first")
    void sortedWorstFirst() {
        var incidents = group(
                "Memory usage at 99% on node-12",
                "Failed login for user admin_42 from ip 1.2.3.4");
        assertEquals("critical", incidents.get(0).severity());
    }

    @Test
    @DisplayName("the window is 300 seconds, matching the Python config")
    void windowConstant() {
        assertEquals(300, LogTriage.WINDOW_SECONDS);
    }

    // --- output contract --------------------------------------------------

    @Test
    @DisplayName("JSON carries the fields the Python pipeline returns")
    void jsonContract() {
        var incidents = group(
                "Failed login for user admin_42 from ip 203.0.113.7",
                "Failed login for user admin_42 from ip 203.0.113.9",
                "Memory usage at 94% on server node-12");
        String json = LogTriage.toJson(incidents, 3);
        assertTrue(json.contains("\"category\""));
        assertTrue(json.contains("\"severity\""));
        assertTrue(json.contains("\"line_count\""));
        assertTrue(json.contains("\"entities\""));
        assertTrue(json.contains("\"total_lines\": 3"));
    }

    @Test
    @DisplayName("the security burst collapses into one critical incident")
    void securityBurstCollapses() {
        var incidents = group(
                "[2026-09-30 02:14:01] Multiple failed login attempts detected for user admin_42",
                "[2026-09-30 02:14:09] Failed login for user admin_42 from ip 203.0.113.7",
                "[2026-09-30 02:16:44] Failed login for user admin_42 from ip 203.0.113.9",
                "[2026-09-30 08:40:00] Memory usage at 94% on server node-12, threshold exceeded");
        assertEquals(2, incidents.size());
        assertEquals("critical", incidents.get(0).severity());
        assertEquals(3, incidents.get(0).lineCount());
    }

    @Test
    void blankLinesCarryNoEntities() {
        assertTrue(LogTriage.entities("").isEmpty());
        assertFalse(LogTriage.classify("").category().isEmpty());
    }
}
