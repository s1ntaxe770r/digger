package latency

import (
	"bytes"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"
)

func TestTiming(t *testing.T) {
	var output bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewJSONHandler(&output, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })
	t.Setenv("DIGGER_COMMENT_TIMING", "0")
	Start("disabled", "test")(nil)
	if output.Len() != 0 {
		t.Fatal("disabled instrumentation logged")
	}
	t.Setenv("DIGGER_COMMENT_TIMING", "1")
	finish := Start("render", "cli", "job_id", "job-1", "comment_id", "42")
	time.Sleep(time.Millisecond)
	finish(nil)
	Start("edit", "backend")(errors.New("secret error detail"))
	if strings.Contains(output.String(), "secret") {
		t.Fatal("error contents leaked")
	}
	decoder := json.NewDecoder(&output)
	var success, failure map[string]any
	if err := decoder.Decode(&success); err != nil {
		t.Fatal(err)
	}
	if err := decoder.Decode(&failure); err != nil {
		t.Fatal(err)
	}
	if success["msg"] != "comment_timing" || success["outcome"] != "success" || failure["outcome"] != "error" {
		t.Fatalf("unexpected events: %v %v", success, failure)
	}
	if success["job_id"] != "job-1" || success["comment_id"] != "42" || success["writer"] != "cli" || success["stage"] != "render" {
		t.Fatalf("missing correlation fields: %v", success)
	}
	if success["span_id"] == failure["span_id"] || success["span_id"] == "" {
		t.Fatal("span IDs must be unique")
	}
	if success["duration_ms"].(float64) < 1 {
		t.Fatal("duration did not include stage execution")
	}
	start, err := time.Parse(time.RFC3339Nano, success["start_utc"].(string))
	if err != nil {
		t.Fatal(err)
	}
	end, err := time.Parse(time.RFC3339Nano, success["end_utc"].(string))
	if err != nil || end.Before(start) {
		t.Fatal("invalid timestamps")
	}
}
