package latency

import (
	"fmt"
	"log/slog"
	"os"
	"sync/atomic"
	"time"
)

var sequence atomic.Uint64

// Start records a stage when DIGGER_COMMENT_TIMING=1. Attributes must not contain secrets or comment bodies.
func Start(stage, writer string, attrs ...any) func(error) {
	if os.Getenv("DIGGER_COMMENT_TIMING") != "1" {
		return func(error) {}
	}
	started := time.Now()
	spanID := fmt.Sprintf("%d-%d-%d", os.Getpid(), started.UnixNano(), sequence.Add(1))
	return func(err error) {
		ended := time.Now()
		outcome := "success"
		if err != nil {
			outcome = "error"
		}
		fields := []any{
			"stage", stage, "writer", writer, "span_id", spanID,
			"start_utc", started.UTC().Format(time.RFC3339Nano),
			"end_utc", ended.UTC().Format(time.RFC3339Nano),
			"duration_ms", float64(ended.Sub(started)) / float64(time.Millisecond),
			"outcome", outcome,
		}
		slog.Info("comment_timing", append(fields, attrs...)...)
	}
}
