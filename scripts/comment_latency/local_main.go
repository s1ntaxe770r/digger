package main

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"github.com/diggerhq/digger/backend/bootstrap"
	"github.com/diggerhq/digger/backend/ci_backends"
	"github.com/diggerhq/digger/backend/controllers"
	"github.com/diggerhq/digger/backend/utils"
	"github.com/diggerhq/digger/libs/spec"
	"github.com/google/go-github/v61/github"
	"log"
	"os"
	"path/filepath"
)

type profileProvider struct{}

func (profileProvider) GetCiBackend(options ci_backends.CiBackendOptions) (ci_backends.CiBackend, error) {
	client, _, err := utils.GetGithubClientFromAppId(options.GithubClientProvider, options.GithubInstallationId, options.GithubAppId, options.RepoFullName)
	if err != nil {
		return nil, err
	}
	return profileCI{&ci_backends.GithubActionCi{Client: client}}, nil
}

type profileCI struct{ *ci_backends.GithubActionCi }

func (ci profileCI) TriggerWorkflow(job spec.Spec, runName, vcsToken string) error {
	var settings struct {
		WorkflowRef string `json:"workflow_ref"`
		SourceRef   string `json:"source_ref"`
		Phase       string `json:"phase"`
		Results     string `json:"results"`
	}
	data, err := os.ReadFile(os.Getenv("DIGGER_PROFILE_SETTINGS"))
	if err != nil {
		return err
	}
	if err = json.Unmarshal(data, &settings); err != nil {
		return err
	}
	if settings.WorkflowRef == "" || settings.SourceRef == "" || (settings.Phase != "before" && settings.Phase != "after") {
		return fmt.Errorf("invalid local profiling settings")
	}
	payload, err := json.Marshal(job)
	if err != nil {
		return err
	}
	metadata, err := json.Marshal(map[string]string{"job_id": job.JobId, "comment_id": job.CommentId, "phase": settings.Phase, "source_ref": settings.SourceRef})
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(settings.Results, job.JobId+".json"), metadata, 0600); err != nil {
		return err
	}
	// Only the workflow definition ref changes; the job payload keeps the real PR branch.
	_, err = ci.Client.Actions.CreateWorkflowDispatchEventByFileName(context.Background(), job.VCS.RepoOwner, job.VCS.RepoName, job.VCS.WorkflowFile, github.CreateWorkflowDispatchEventRequest{
		Ref:    settings.WorkflowRef,
		Inputs: map[string]interface{}{"spec": string(payload), "run_name": "latency-" + settings.Phase + "-" + runName, "phase": settings.Phase, "source_ref": settings.SourceRef},
	})
	return err
}

func main() {
	var provider ci_backends.CiBackendProvider = ci_backends.DefaultBackendProvider{}
	if os.Getenv("DIGGER_PROFILE_SETTINGS") != "" {
		provider = profileProvider{}
	}
	controller := controllers.DiggerController{
		CiBackendProvider:                  provider,
		GithubClientProvider:               utils.DiggerGithubRealClientProvider{},
		GithubWebhookPostIssueCommentHooks: make([]controllers.IssueCommentHook, 0),
	}
	// Run from backend/ so Bootstrap loads its templates directory.
	r := bootstrap.Bootstrap(embed.FS{}, controller)
	r.GET("/", controllers.Home)
	log.Fatal(r.Run("127.0.0.1:3101"))
}
