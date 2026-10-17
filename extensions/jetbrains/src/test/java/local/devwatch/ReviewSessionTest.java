package local.devwatch;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;
import java.util.ArrayList;
import java.util.List;
import static org.junit.Assert.*;

public class ReviewSessionTest {
    @Test public void unknownSubmissionRetainsExactIntentAndOnlyExplicitRecoveryResubmits() throws Exception {
        List<JsonObject> calls = new ArrayList<>();
        boolean[] failed = {true};
        ReviewSession.Memory memory = new ReviewSession.Memory();
        ReviewSession session = new ReviewSession(request -> {
            calls.add(request.deepCopy());
            if (request.get("action").getAsString().equals("capture")) return JsonParser.parseString("{\"intent\":{\"snapshot_id\":\"" + "a".repeat(32) + "\",\"changed_files\":[\"service.py\"],\"idempotency_key\":\"original\"}}").getAsJsonObject();
            if (failed[0]) throw new IllegalStateException("Unknown reply");
            JsonObject job = new JsonObject(); job.addProperty("job_id", "b".repeat(32)); return job;
        }, memory);
        try { session.review("workspace"); fail(); } catch (IllegalStateException expected) { }
        assertEquals("original", memory.load().getAsJsonObject("intent").get("idempotency_key").getAsString());
        try { session.attach("c".repeat(32)); fail(); } catch (IllegalStateException expected) { }
        failed[0] = false;
        session.recover();
        assertEquals("b".repeat(32), memory.load().get("jobId").getAsString());
        assertEquals(calls.get(1), calls.get(2));
    }

    @Test public void replayCursorCommitsAfterConsumerAndDoesNotControlExecution() throws Exception {
        ReviewSession.Memory memory = new ReviewSession.Memory();
        JsonObject initial = new JsonObject(); initial.addProperty("jobId", "a".repeat(32)); initial.addProperty("cursor", 0); memory.save(initial);
        List<String> calls = new ArrayList<>();
        ReviewSession session = new ReviewSession(request -> {
            String action = request.get("action").getAsString(); calls.add(action);
            if (action.equals("events")) return JsonParser.parseString("{\"events\":[{\"sequence\":1,\"kind\":\"tool_called\"}],\"next_cursor\":1}").getAsJsonObject();
            return JsonParser.parseString("{\"status\":\"running\"}").getAsJsonObject();
        }, memory);
        try { session.observe(event -> { throw new IllegalStateException("Detached"); }); fail(); } catch (IllegalStateException expected) { }
        assertEquals(0, memory.load().get("cursor").getAsInt());
        session.observe(event -> { });
        assertEquals(1, memory.load().get("cursor").getAsInt());
        assertTrue(calls.stream().allMatch(action -> action.equals("events") || action.equals("status")));
    }
}
