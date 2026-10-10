package comment_updater

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"testing"

	"github.com/diggerhq/digger/libs/ci"
	"github.com/diggerhq/digger/libs/scheduler"
)

type commentSpy struct {
	ci.PullRequestService
	err   error
	calls int
	body  string
}

func (s *commentSpy) EditComment(_ int, _ string, body string) error {
	s.calls++
	s.body = body
	return s.err
}

func syntheticJobs(count int) []scheduler.SerializedJob {
	jobs := make([]scheduler.SerializedJob, count)
	for i := range jobs {
		jobs[i] = scheduler.SerializedJob{
			DiggerJobId: fmt.Sprintf("job-%d", i), ProjectName: fmt.Sprintf("project-%d", i),
			Status: scheduler.DiggerJobSucceeded, JobString: []byte(`{"job_type":"plan"}`),
			ResourcesCreated: 1,
		}
	}
	return jobs
}

func TestUpdateCommentTiming(t *testing.T) {
	for _, failure := range []bool{false, true} {
		t.Run(fmt.Sprintf("edit_failure=%t", failure), func(t *testing.T) {
			t.Setenv("DIGGER_COMMENT_TIMING", "1")
			var logs bytes.Buffer
			previous := slog.Default()
			slog.SetDefault(slog.New(slog.NewJSONHandler(&logs, nil)))
			t.Cleanup(func() { slog.SetDefault(previous) })
			spy := &commentSpy{}
			if failure {
				spy.err = errors.New("simulated GitHub failure")
			}
			if err := (BasicCommentUpdater{}).UpdateComment(syntheticJobs(2), 7, spy, "42"); err != nil {
				t.Fatalf("existing edit failure behavior changed: %v", err)
			}
			if spy.calls != 1 || !strings.Contains(spy.body, "project-1") {
				t.Fatalf("expected one rendered comment, got %d calls", spy.calls)
			}
			events := map[string]map[string]any{}
			decoder := json.NewDecoder(&logs)
			for {
				var event map[string]any
				err := decoder.Decode(&event)
				if err == io.EOF {
					break
				}
				if err != nil {
					t.Fatal(err)
				}
				if event["msg"] == "comment_timing" {
					events[event["stage"].(string)] = event
				}
			}
			editOutcome := "success"
			if failure {
				editOutcome = "error"
			}
			for stage, outcome := range map[string]string{"summary_render": "success", "summary_edit": editOutcome} {
				event := events[stage]
				if event["writer"] != "cli" || event["comment_id"] != "42" || event["outcome"] != outcome {
					t.Fatalf("unexpected %s timing: %v", stage, event)
				}
				if duration, ok := event["duration_ms"].(float64); !ok || duration < 0 {
					t.Fatalf("invalid duration: %v", event)
				}
			}
			if len(events) != 2 {
				t.Fatalf("expected two timing stages, got %v", events)
			}
		})
	}
}

// Synthetic CPU/allocation benchmark; no GitHub or backend requests are made.
func BenchmarkSummarySynthetic(b *testing.B) {
	b.Setenv("DIGGER_COMMENT_TIMING", "0")
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	b.Cleanup(func() { slog.SetDefault(previous) })
	for _, count := range []int{10, 100, 1000} {
		b.Run(fmt.Sprintf("jobs_%d", count), func(b *testing.B) {
			jobs := syntheticJobs(count)
			spy := &commentSpy{}
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				if err := (BasicCommentUpdater{}).UpdateComment(jobs, 7, spy, "42"); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func TestSummaryOutputGolden(t *testing.T) {
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })
	small := syntheticJobs(2)
	workflow := "https://example.com/actions/123"
	small[0].ProjectAlias = "production"
	small[0].WorkflowRunUrl = &workflow
	small[0].PRCommentUrl = "https://example.com/comment/42"
	small[0].ResourcesCreated = 2
	small[0].ResourcesUpdated = 3
	small[0].ResourcesDeleted = 4
	small[1].Status = scheduler.DiggerJobFailed
	for _, test := range []struct {
		name   string
		jobs   []scheduler.SerializedJob
		digest string
	}{
		{"small", small, "6b1836eb553e0bd461bb913a2a367346431243ffd0edcbb956c878903b2d42bf"}, {"truncated", syntheticJobs(1000), "87c15d0c598351824a045bbfef4bd021aba5f470159f826d259fef78525e358b"},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &commentSpy{}
			if err := (BasicCommentUpdater{}).UpdateComment(test.jobs, 7, spy, "42"); err != nil {
				t.Fatal(err)
			}
			digest := fmt.Sprintf("%x", sha256.Sum256([]byte(spy.body)))
			t.Logf("golden %s length=%d sha256=%s", test.name, len(spy.body), digest)
			if digest != test.digest {
				t.Fatalf("comment output changed: sha256=%s", digest)
			}
			if test.name == "truncated" && (len(spy.body) != 65536 || !strings.HasSuffix(spy.body, "[trimmed]")) {
				t.Fatal("truncation changed")
			}
		})
	}
}
