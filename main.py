import argparse
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta
from enum import Enum


class GithubResponse:
    def __init__(self, response: bytes) -> None:
        self.body = json.loads(response)


class GithubClient:
    GITHUB_APP = "application/vnd.github.v3+json"
    header: dict
    base_url: str

    def __init__(self, token: str, base_url: str) -> None:
        self.header = {"Accept": self.GITHUB_APP, "authorization": f"Bearer {token}"}
        self.base_url = base_url

    def get_response(self, url: str) -> GithubResponse:
        request = urllib.request.Request(url, headers=self.header)
        with urllib.request.urlopen(request) as res:
            github_response = GithubResponse(res.read())
        return github_response

    def get_workflow_run(self, repo: str, run_id: str) -> GithubResponse:
        url = f"{self.base_url}/repos/{repo}/actions/runs/{run_id}"
        return self.get_response(url)

    def get_jobs(self, jobs_url: str) -> GithubResponse:
        return self.get_response(jobs_url)


DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def calc_duration(started_at: str, completed_at: str) -> timedelta:
    dt_started_at = datetime.strptime(started_at, DATETIME_FORMAT)
    dt_completed_at = datetime.strptime(completed_at, DATETIME_FORMAT)
    return dt_completed_at - dt_started_at


class WorkflowStatus(Enum):
    SUCCESS = True
    FAILURE = False


class SlackAttachmentFields:
    data: list[dict]
    workflow_status: WorkflowStatus

    def __init__(self, jobs: GithubResponse) -> None:
        self.data = []
        self.workflow_status = WorkflowStatus.SUCCESS
        for job in jobs.body["jobs"]:
            job_field = {}
            job_field["title"] = f'{job["conclusion"]}: {job["name"]}'
            job_field["short"] = "true"
            if job["conclusion"] == "success":
                job_field["value"] = str(calc_duration(job["started_at"], job["completed_at"]))
            if job["conclusion"] == "failure":
                self.workflow_status = WorkflowStatus.FAILURE
            if job["conclusion"] in ["success", "failure"]:
                self.data.append(job_field)


class SlackNotifier:
    __web_hook_url: str
    payload: dict
    attachments: dict
    HEADER = {"Content-type": "application/json"}

    def __init__(self, web_hook_url: str) -> None:
        self.__web_hook_url = web_hook_url
        self.payload = {}
        self.attachments = {}

    def build_attachments(self, sub_text: str, fields: SlackAttachmentFields) -> None:
        self.attachments["mrkdwn_in"] = ["text"]
        self.attachments["color"] = "good" if fields.workflow_status.value else "danger"
        self.attachments["text"] = sub_text
        self.attachments["fields"] = fields.data

    def build_payload(
        self, user_name: str, icon_emoji: str, main_text: str, sub_text: str, fields: SlackAttachmentFields
    ) -> None:
        self.payload["username"] = user_name
        self.payload["text"] = main_text
        self.payload["icon_emoji"] = icon_emoji
        self.build_attachments(sub_text, fields)
        self.payload["attachments"] = [self.attachments]

    def post_notification(self, verbose: bool = False) -> None:
        req = urllib.request.Request(
            self.__web_hook_url, data=json.dumps(self.payload).encode("utf-8"), headers=self.HEADER
        )
        with urllib.request.urlopen(req) as res:
            if verbose:
                print(res.read())


RE_BRANCH = re.compile(r".*heads/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.getenv("INPUT_GITHUB_TOKEN"))
    parser.add_argument("--webhook-url", default=os.getenv("INPUT_SLACK_WEBHOOK_URL"))
    parser.add_argument("--mention-map", default=os.getenv("INPUT_MENTION_MAP"))
    parser.add_argument("--status-emoji-map", default=os.getenv("INPUT_STATUS_EMOJI_MAP"))
    parser.add_argument("--name", default=os.getenv("INPUT_NAME", "Bot"))
    parser.add_argument("--base-url", default=os.getenv("GITHUB_API_URL"))
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID"))
    parser.add_argument("--event", default=os.getenv("GITHUB_EVENT_NAME"))
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--branch", default=RE_BRANCH.sub("", os.getenv("GITHUB_REF")))
    parser.add_argument("--actor", default=os.getenv("GITHUB_ACTOR"))
    parser.add_argument("--workflow-name", default=os.getenv("GITHUB_WORKFLOW"))
    args = parser.parse_args()

    github_client = GithubClient(args.token, args.base_url)
    workflow = github_client.get_workflow_run(args.repo, args.run_id)
    jobs = github_client.get_jobs(workflow.body["jobs_url"])
    fields = SlackAttachmentFields(jobs)
    workflow_status = fields.workflow_status.name

    actor = args.actor
    head_notification = ""
    if args.mention_map:
        args.mention_map = json.loads(args.mention_map)
        actor = args.mention_map.get(args.actor, args.actor)
        if isinstance(actor, dict):
            actor = actor.get(workflow_status, args.actor)
        head_notification = args.mention_map.get(args.branch, "")
        if isinstance(head_notification, dict):
            head_notification = head_notification.get(workflow_status, "")

    workflow_duration = calc_duration(workflow.body["created_at"], workflow.body["updated_at"])
    main_text = f"{head_notification}[{args.branch.replace('/', '_')}] "
    main_text += f"{actor}'s `{args.event}` -> "
    main_text += f"{workflow_status} (in *{workflow_duration}*)"

    sub_text = f"Workflow: {args.workflow_name} "
    sub_text += f"<{workflow.body['html_url']}|#{workflow.body['run_number']}>"
    icon_emoji = ":github_actions:"
    if args.status_emoji_map:
        args.status_emoji_map = json.loads(args.status_emoji_map)
        icon_emoji = args.status_emoji_map[workflow_status]

    notify = SlackNotifier(args.webhook_url)
    notify.build_payload(args.name, icon_emoji, main_text, sub_text, fields)
    notify.post_notification()


if __name__ == "__main__":
    main()
