"""Record the local backend setup page without submitting the GitHub App form."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", help="Existing Chromium executable; otherwise use Playwright's default")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = root / "results" / "local-startup"
    output.mkdir(parents=True, exist_ok=True)
    env = dict(
        line.split("=", 1)
        for line in (root / "backend.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=args.chromium)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            http_credentials={
                "username": env["HTTP_BASIC_AUTH_USERNAME"],
                "password": env["HTTP_BASIC_AUTH_PASSWORD"],
                "origin": "http://127.0.0.1:3101",
            },
            record_video_dir=str(output),
        )
        page = context.new_page()
        response = page.goto("http://127.0.0.1:3101/health")
        assert response.status == 200, f"Health returned {response.status}"
        health = response.json()
        response = page.goto("http://127.0.0.1:3101/github/setup")
        assert response.status == 200, f"Setup returned {response.status}"
        manifest = json.loads(page.locator('textarea[name="manifest"]').input_value())
        assert manifest["hook_attributes"]["url"].endswith("/github/webhook")
        page.screenshot(path=str(output / "backend-setup.png"), full_page=True)
        video = page.video
        context.close()
        video.save_as(str(output / "backend-setup.webm"))
        video.delete()
        browser.close()
    result = {
        "health": health,
        "setup_http_status": 200,
        "webhook_url": manifest["hook_attributes"]["url"],
        "github_app_created": False,
        "live_workflow_measured": False,
    }
    (output / "browser-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
