package github

type MockGithubPullrequestManager struct {
	commands []string
}

func (mockGithubPullrequestManager *MockGithubPullrequestManager) GetChangedFiles(prNumber int) ([]string, error) {
	mockGithubPullrequestManager.commands = append(mockGithubPullrequestManager.commands, "GetChangedFiles")
	return nil, nil
}

func (mockGithubPullrequestManager *MockGithubPullrequestManager) PublishComment(prNumber int, comment string) {
	mockGithubPullrequestManager.commands = append(mockGithubPullrequestManager.commands, "PublishComment")
}

func (mockGithubPullrequestManager *MockGithubPullrequestManager) ReplyComment(prNumber int, reply string) {
	mockGithubPullrequestManager.commands = append(mockGithubPullrequestManager.commands, "ReplyComment")
}
