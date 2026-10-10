package comment_updater

import (
	"fmt"
	"log/slog"
	"strings"

	"github.com/diggerhq/digger/libs/ci"
	"github.com/diggerhq/digger/libs/comment_utils/latency"
	"github.com/diggerhq/digger/libs/scheduler"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
)

type CommentUpdater interface {
	UpdateComment(jobs []scheduler.SerializedJob, prNumber int, prService ci.PullRequestService, prCommentId string) error
}

type BasicCommentUpdater struct {
}

func (b BasicCommentUpdater) UpdateComment(jobs []scheduler.SerializedJob, prNumber int, prService ci.PullRequestService, prCommentId string) error {
	finishRender := latency.Start("summary_render", "cli", "comment_id", prCommentId, "pr_number", prNumber, "job_count", len(jobs))
	jobSpecs, err := scheduler.GetJobSpecs(jobs)
	if err != nil {
		finishRender(err)
		slog.Error("could not get jobspecs", "error", err, "jobCount", len(jobs))
		return err
	}

	if len(jobSpecs) == 0 {
		finishRender(nil)
		slog.Warn("no job specs found, cannot update comment", "jobCount", len(jobs))
		return nil
	}

	firstJobSpec := jobSpecs[0]
	jobType := firstJobSpec.JobType
	jobTypeTitle := cases.Title(language.AmericanEnglish).String(string(jobType))

	slog.Info("updating comment with job results",
		"prNumber", prNumber,
		"commentId", prCommentId,
		"jobCount", len(jobs),
		"jobType", jobType)

	var body strings.Builder
	body.WriteString(fmt.Sprintf("| Project | Status | %v | + | ~ | - |\n", jobTypeTitle))
	body.WriteString("|---------|--------|------|---|---|---|\n")

	for _, job := range jobs {
		prCommentUrl := job.PRCommentUrl

		// Safe handling of WorkflowRunUrl pointer
		workflowUrl := "#"
		if job.WorkflowRunUrl != nil {
			workflowUrl = *job.WorkflowRunUrl
		}

		body.WriteString(fmt.Sprintf("|%v **%v** |<a href='%v'>%v</a> | <a href='%v'>%v</a> | %v | %v | %v|\n",
			job.Status.ToEmoji(),
			scheduler.GetProjectAlias(job),
			workflowUrl,
			job.Status.ToString(),
			prCommentUrl,
			jobTypeTitle,
			job.ResourcesCreated,
			job.ResourcesUpdated,
			job.ResourcesDeleted))
	}

	body.WriteString("\n")
	body.WriteString(formatExampleCommands())
	message := body.String()

	const GithubCommentMaxLength = 65536
	if len(message) > GithubCommentMaxLength {
		// TODO: Handle the case where message is too long by trimming
		slog.Warn("message is too long, trimming",
			"originalLength", len(message),
			"maxLength", GithubCommentMaxLength)

		const footer = "[trimmed]"
		trimLength := len(message) - GithubCommentMaxLength + len(footer)
		message = message[:len(message)-trimLength] + footer

		slog.Debug("trimmed message", "newLength", len(message))
	}

	finishRender(nil)
	finishEdit := latency.Start("summary_edit", "cli", "comment_id", prCommentId, "pr_number", prNumber)
	err = prService.EditComment(prNumber, prCommentId, message)
	finishEdit(err)
	if err != nil {
		slog.Warn("failed to update summary comment",
			"error", err,
			"prNumber", prNumber,
			"commentId", prCommentId)
	} else {
		slog.Info("successfully updated summary comment",
			"prNumber", prNumber,
			"commentId", prCommentId)
	}

	return nil
}

// formatExampleCommands creates a collapsible markdown section with example commands
func formatExampleCommands() string {
	return `
<details>
  <summary>Instructions</summary>

⏩ To apply these changes, run the following command:

` + "```" + `bash
digger apply
` + "```" + `

🚮 To unlock the projects in this PR run the following command:
` + "```" + `bash
digger unlock
` + "```" + `
</details>
`
}

type NoopCommentUpdater struct {
}

func (b NoopCommentUpdater) UpdateComment(jobs []scheduler.SerializedJob, prNumber int, prService ci.PullRequestService, prCommentId string) error {
	slog.Debug("noop comment updater called, no action taken",
		"prNumber", prNumber,
		"commentId", prCommentId,
		"jobCount", len(jobs))
	return nil
}
